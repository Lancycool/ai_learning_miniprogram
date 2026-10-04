"""Traverse the selected full text. Answers are copied, never inferred by a model."""

import asyncio
from collections import Counter, defaultdict
import re
import logging

from app.core.knowledge_errors import KnowledgeError
from app.services.auth_service import public_id

QUESTION = re.compile(r"^\s*(?:第\s*(\d+)\s*题[：:.、]?|(\d+)[.．、)）]\s*|Q(\d+)[.：:]?\s*)(.*)$", re.IGNORECASE)
OPTION = re.compile(r"^\s*([A-Z])[.．、:：)）]\s?(.*)$")
ANSWER = re.compile(r"^\s*(?:【|\[)?(?:参考|标准|正确)?答案(?:】|\])?\s*[：:]?\s*(.*)$")
EXPLANATION = re.compile(r"^\s*(?:【|\[)?(?:解析|讲解|解答)(?:】|\])?\s*[：:]?\s*(.*)$")
TYPE = re.compile(r"^\s*[\[【（(]?(单选题?|多选题?|判断题?|填空题?|简答题?|问答题?|计算题?)[\]】）)]?\s*[：:]?\s*")


def answer_keys(raw, judge=False):
    raw = raw.strip().strip("。.")
    if judge:
        if raw in ("正确", "对", "是", "√", "True", "true", "T"):
            return ["A"]
        if raw in ("错误", "错", "否", "×", "False", "false", "F"):
            return ["B"]
    compact = re.sub(r"[\s,，、;；]+", "", raw)
    return list(compact) if re.fullmatch(r"[A-Z]{1,26}", compact) else []


def merged_ranges(chapters, selected_ids=None):
    chosen = chapters if selected_ids is None else [c for c in chapters if c["chapter_id"] in selected_ids]
    if selected_ids is not None and set(selected_ids) != {c["chapter_id"] for c in chosen}:
        raise KnowledgeError("invalid_scope", "所选章节已变化，请重新选择", 409)
    ranges = []
    for c in sorted(chosen, key=lambda c: c["start_offset"]):
        start, end = c["start_offset"], c["end_offset"]
        if ranges and start <= ranges[-1][1]:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])
    return ranges


class OriginalQuestionParser:
    def __init__(self, settings, *, helper=None):
        self.settings, self.helper = settings, helper

    async def parse(self, text, chapters, selected_ids=None, progress=None):
        ranges = merged_ranges(chapters, selected_ids)
        items, coverage, answers = [], [], defaultdict(list)
        def chapter_at(offset):
            matching = [c for c in chapters if c["start_offset"] <= offset < c["end_offset"]]
            return max(matching, key=lambda c: c["level"])["chapter_id"] if matching else None
        for range_start, range_end in ranges:
            lines, offset = [], range_start
            for line in text[range_start:range_end].splitlines(keepends=True):
                lines.append((offset, offset+len(line), line.rstrip("\n")))
                offset += len(line)
            starts, breaks, table = [], [], False
            table_spans = []
            for start, end, line in lines:
                is_heading = any(c["start_offset"] == start for c in chapters) and not QUESTION.match(line)
                if is_heading:
                    table = False
                    breaks.append(start)
                if re.match(r"^\s*(?:参考|标准)?答案(?:汇总|表)?\s*[：:]?\s*$", line):
                    table = True
                    breaks.append(start)
                if table:
                    table_spans.append((start, end))
                    for match in re.finditer(r"(\d+)\s*[.．、:：)）]\s*([A-Z][A-Z\s,，、]*|正确|错误|对|错|√|×)(?=\s*\d+\s*[.．、:：)）]|$)", line):
                        answers[(chapter_at(start), match[1])].append(match[2].strip())
                    continue
                match = QUESTION.match(line)
                if match:
                    starts.append((start, match, line))
            recognized = []
            for index, (start, match, _) in enumerate(starts):
                end = starts[index+1][0] if index+1 < len(starts) else range_end
                end = min([end] + [boundary for boundary in breaks if start < boundary < end])
                raw = text[start:end]
                item = self.parse_question(raw, match, chapter_at(start), start, end)
                items.append(item)
                recognized.append((start, end, "unsupported" if item["type"] == "unsupported" else "recognized"))
                if len(items) > self.settings.knowledge_max_import_questions:
                    raise KnowledgeError("import_limit", "原题数量超过处理上限，请按章节拆分导入")
                if index % 50 == 0:
                    if progress:
                        await progress("extracting", len(items))
                    await asyncio.sleep(0)
            # Every selected character is accounted for, including unrecognized passages.
            boundaries = sorted({range_start, range_end} | {p for a, b, _ in recognized for p in (a, b)}
                                | {p for a, b in table_spans for p in (a, b)})
            for a, b in zip(boundaries, boundaries[1:]):
                status = next((kind for start, end, kind in recognized if start <= a and b <= end), None)
                if status is None:
                    status = "answer_table" if any(start <= a and b <= end for start, end in table_spans) else "unrecognized"
                if coverage and coverage[-1]["status"] == status and coverage[-1]["end_offset"] == a:
                    coverage[-1]["end_offset"] = b
                    coverage[-1]["quote"] += text[a:b]
                else:
                    coverage.append({"start_offset": a, "end_offset": b, "status": status, "quote": text[a:b]})
        numbers = Counter((q["chapter_id"], q["source"]["number"]) for q in items)
        doc_numbers = Counter(q["source"]["number"] for q in items)
        for item in items:
            number, chapter_id = item["source"]["number"], item["chapter_id"]
            if numbers[(chapter_id, number)] > 1:
                item["issues"].append("duplicate_number")
            matches = answers.get((chapter_id, number), [])
            if not matches and doc_numbers[number] == 1:
                matches = [a for (_, n), values in answers.items() if n == number for a in values]
            candidates = [tuple(a) for a in [item["answer"]] if a]
            candidates.extend(tuple(answer_keys(a, item["type"] == "judge")) for a in matches)
            candidates = set(candidates)-{()}
            if len(candidates) > 1:
                item["answer"] = []
                item["issues"].append("conflicting_answer")
            elif candidates:
                item["answer"] = list(next(iter(candidates)))
            self.validate_review(item)
        issues = []
        if self.helper:
            issues = await self.locate_unrecognized(text, chapters, coverage, items)
        items.sort(key=lambda q: q['source']['start_offset'])
        return {"items": items, "coverage": coverage, "issues": issues}

    def parse_question(self, raw, match, chapter_id, start, end):
        number = next(value for value in match.groups()[:3] if value is not None) if match else f"source-{start}"
        first = match[4] if match else raw.splitlines()[0]
        marker = TYPE.match(first)
        kind = {"单选": "single", "多选": "multiple", "判断": "judge"}.get(marker[1][:2], "unsupported") if marker else "unknown"
        if marker:
            first = first[marker.end():]
        stem, options, answer_candidates, explanation = [first], [], [], None
        state = "stem"
        for line in raw.splitlines()[1:]:
            option, answer, explain = OPTION.match(line), ANSWER.match(line), EXPLANATION.match(line)
            if answer:
                answer_candidates.append(answer_keys(answer[1], kind == "judge"))
                state = "answer"
            elif explain:
                explanation, state = explain[1], "explanation"
            elif option and state not in ("explanation",):
                options.append({"key": option[1], "text": option[2], "source_label": option[1]})
                state = "option"
            elif state == "option" and options:
                options[-1]["text"] += "\n"+line
            elif state == "explanation":
                explanation += "\n"+line
            elif state == "stem":
                stem.append(line)
        stem_text = "\n".join(stem).rstrip("\n")
        issues = []
        if re.search(r"下图|图中|看图|!\[|<img\b", raw, re.IGNORECASE):
            kind = "unsupported"
            issues.append("image_dependent")
        if kind == "judge" and not options:
            options = [{"key": "A", "text": "正确", "source_label": "判断"}, {"key": "B", "text": "错误", "source_label": "判断"}]
        candidates = {tuple(a) for a in answer_candidates if a}
        answer = list(next(iter(candidates))) if len(candidates) == 1 else []
        if len(candidates) > 1:
            issues.append("conflicting_answer")
        if kind == "unknown" and options and answer:
            kind = "multiple" if len(answer) > 1 else "single"
        if len(stem_text) > 32000 or any(len(o["text"]) > 8000 for o in options) or (explanation and len(explanation) > 32000) or len(options) > 26:
            raise KnowledgeError("import_limit", "原题字段超过处理上限，请拆分或调整文档；系统没有截断原文")
        return {"id": public_id("draftq"), "type": kind, "stem": stem_text, "options": options,
            "answer": answer, "explanation": explanation.rstrip("\n") if explanation is not None else None,
            "chapter_id": chapter_id, "source": {"start_offset": start, "end_offset": end, "quote": raw, "number": number},
            "issues": issues, "excluded": False, "manually_edited": False}

    @staticmethod
    def validate_review(item):
        issues = item["issues"]
        if item["type"] == "unsupported":
            issues.append("unsupported_type")
        if item["type"] == "unknown":
            issues.append("unknown_type")
        if not item["answer"]:
            issues.append("missing_answer")
        if item["explanation"] is None:
            issues.append("missing_explanation")
        keys = [o["key"] for o in item["options"]]
        if len(keys) < 2 or len(keys) != len(set(keys)) or any(not o["text"].strip() for o in item["options"]):
            issues.append("invalid_options")
        if (not set(item["answer"]).issubset(keys) or len(item["answer"]) != len(set(item["answer"]))
            or (item["type"] in ("single", "judge") and len(item["answer"]) > 1)):
            issues.append("invalid_answer")
        item["issues"] = list(dict.fromkeys(issues))

    async def locate_unrecognized(self, text, chapters, coverage, items):
        # A locator supplies only source spans. This contract prevents the helper
        # from returning a made-up stem, option or answer.
        issues, calls, accepted = [], 0, []
        for block in list(coverage):
            if block['status'] != 'unrecognized' or not block['quote'].strip():
                continue
            # Plain headings do not need a model call. Larger blocks retain all
            # unexamined text in the review coverage rather than silently vanish.
            if not re.search(r'单选|多选|判断|填空|简答|^[A-Z][.．、:：)）]', block['quote'], re.MULTILINE):
                continue
            if calls >= 4:
                issues.append({'code': 'locator_limit', 'message': '结构定位达到次数限制，剩余原文需要你核对或按章节重新导入'})
                break
            calls += 1
            try:
                async with asyncio.timeout(15):
                    located = await self.helper(block["quote"][:8000])
            except Exception as exc:
                logging.getLogger(__name__).warning('original_locator_failed type=%s', type(exc).__name__)
                issues.append({'code': 'locator_unavailable', 'message': '结构定位暂时不可用，未识别原文已保留，请你补题或重新导入'})
                continue
            if not isinstance(located, list):
                continue
            for entry in located:
                if not isinstance(entry, dict) or any(k not in ("start_offset", "end_offset") for k in entry):
                    continue
                a, b = entry.get("start_offset"), entry.get("end_offset")
                if type(a) is not int or type(b) is not int or not 0 <= a < b <= min(8000, len(block["quote"])):
                    continue
                raw = block["quote"][a:b]
                match = QUESTION.match(raw.splitlines()[0])
                start, end = block['start_offset']+a, block['start_offset']+b
                if any(start < old_end and old_start < end for old_start, old_end, _ in accepted):
                    continue
                if match or TYPE.match(raw.splitlines()[0]):
                    # Rule extraction remains the authority for all actual fields.
                    start = block["start_offset"]+a
                    matching = [c for c in chapters if c["start_offset"] <= start < c["end_offset"]]
                    identity = max(matching, key=lambda c: c["level"])["chapter_id"] if matching else None
                    item = self.parse_question(raw, match, identity, start, end)
                    self.validate_review(item)
                    items.append(item)
                    accepted.append((start, end, 'unsupported' if item['type'] == 'unsupported' else 'recognized'))
                    if len(items) > self.settings.knowledge_max_import_questions:
                        raise KnowledgeError('import_limit', '原题数量超过处理上限，请按章节拆分导入')
        revised = []
        for block in coverage:
            boundaries = sorted({block['start_offset'], block['end_offset']} | {p for a, b, _ in accepted
                if block['start_offset'] <= a < b <= block['end_offset'] for p in (a, b)})
            for a, b in zip(boundaries, boundaries[1:]):
                status = next((kind for x, y, kind in accepted if x <= a and b <= y), block['status'])
                revised.append({'start_offset': a, 'end_offset': b, 'status': status, 'quote': text[a:b]})
        coverage[:] = revised
        return issues
