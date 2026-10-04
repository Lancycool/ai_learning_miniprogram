import pytest

from app.core.config import Settings
from app.core.knowledge_errors import KnowledgeError


def chapter(text, identity="chapter-one", title="第一章"):
    return {"chapter_id": identity, "title": title, "level": 1, "start_offset": 0, "end_offset": len(text)}


async def test_twelve_questions_and_end_answer_table_are_not_top_k():
    from app.services.original_question_parser import OriginalQuestionParser
    text = "第一章\n" + "\n".join(f"{i}. [单选题] 客服流程第{i}题应如何处理？\nA. 核对订单\nB. 跳过检查\nC. 删除资料\nD. 关闭会话\nE. 交给主管" for i in range(1, 13))
    text += "\n参考答案\n" + " ".join(f"{i}.A" for i in range(1, 13))
    parsed = await OriginalQuestionParser(Settings(_env_file=None)).parse(text, [chapter(text)])
    assert len(parsed["items"]) == 12
    assert all(q["answer"] == ["A"] and len(q["options"]) == 5 for q in parsed["items"])
    assert parsed["items"][11]["stem"].endswith("第12题应如何处理？")
    assert all(q["explanation"] is None and "missing_explanation" in q["issues"] for q in parsed["items"])
    assert parsed["coverage"] and sum(c["end_offset"]-c["start_offset"] for c in parsed["coverage"]) == len(text)


async def test_long_original_multiple_and_judge_are_preserved():
    from app.services.original_question_parser import OriginalQuestionParser
    long_stem = "情景说明" * 1000 + "请选择全部正确的处理步骤。"
    text = f"1. [多选题] {long_stem}\nA. 原文一\nB. 原文二\nC. 原文三\nD. 原文四\nE. 原文五\n答案：ACE\n解析：原有讲解\n2. [判断题] 客服需要核对订单。\n答案：正确\n"
    parsed = await OriginalQuestionParser(Settings(_env_file=None)).parse(text, [chapter(text)])
    multiple, judge = parsed["items"]
    assert multiple["stem"] == long_stem and multiple["answer"] == ["A", "C", "E"]
    assert multiple["explanation"] == "原有讲解"
    assert judge["type"] == "judge" and judge["answer"] == ["A"]
    assert judge["options"] == [{"key": "A", "text": "正确", "source_label": "判断"}, {"key": "B", "text": "错误", "source_label": "判断"}]
    for q in parsed["items"]:
        source = q["source"]
        assert text[source["start_offset"]:source["end_offset"]] == source["quote"]


async def test_missing_conflicting_duplicate_and_unsupported_are_reviewable():
    from app.services.original_question_parser import OriginalQuestionParser
    text = "1. [单选题] 没有答案的原题？\nA. 一\nB. 二\n1. [单选题] 重复题号？\nA. 一\nB. 二\n答案：A\n2. [单选题] 答案冲突？\nA. 一\nB. 二\n答案：A\n答案：B\n3. [简答题] 请解释流程。\n4. [单选题] 请看下图选择答案。\nA. 一\nB. 二\n答案：A\n"
    parsed = await OriginalQuestionParser(Settings(_env_file=None)).parse(text, [chapter(text)])
    assert len(parsed["items"]) == 5
    assert "missing_answer" in parsed["items"][0]["issues"]
    assert "duplicate_number" in parsed["items"][0]["issues"] and "duplicate_number" in parsed["items"][1]["issues"]
    assert "conflicting_answer" in parsed["items"][2]["issues"] and parsed["items"][2]["answer"] == []
    assert all(q["type"] == "unsupported" for q in parsed["items"][3:])


async def test_chapter_scoped_answers_and_selection_do_not_leak():
    from app.services.original_question_parser import OriginalQuestionParser
    first = "第一章\n1. [单选题] 客服处理？\nA. 一\nB. 二\n参考答案\n1.A\n"
    second = "第二章\n1. [单选题] 退款处理？\nA. 三\nB. 四\n参考答案\n1.B\n"
    text = first+second
    chapters = [chapter(first), {**chapter(text, "chapter-two", "第二章"), "start_offset": len(first)}]
    parsed = await OriginalQuestionParser(Settings(_env_file=None)).parse(text, chapters)
    assert [q["answer"] for q in parsed["items"]] == [["A"], ["B"]]
    selected = await OriginalQuestionParser(Settings(_env_file=None)).parse(text, chapters, selected_ids=["chapter-two"])
    assert len(selected["items"]) == 1 and "客服" not in str(selected)


async def test_unrecognized_text_is_retained_and_limit_fails_without_partial_result():
    from app.services.original_question_parser import OriginalQuestionParser
    text = "自定义未编号原题\n选项甲：核对订单\n选项乙：直接退款\n标准答案尚未提供"
    parsed = await OriginalQuestionParser(Settings(_env_file=None)).parse(text, [chapter(text)])
    assert parsed["items"] == [] and any(c["status"] == "unrecognized" and c["quote"] == text for c in parsed["coverage"])
    text = "1. [单选题] 第一题？\nA. 一\nB. 二\n2. [单选题] 第二题？\nA. 一\nB. 二\n"
    with pytest.raises(KnowledgeError) as caught:
        await OriginalQuestionParser(Settings(_env_file=None, KNOWLEDGE_MAX_IMPORT_QUESTIONS=1)).parse(text, [chapter(text)])
    assert caught.value.reason == "import_limit"


async def test_helper_cannot_invent_original_content_or_missing_answers():
    from app.services.original_question_parser import OriginalQuestionParser
    async def helper(text):
        return [{"start_offset": 0, "end_offset": len(text), "stem": "模型编造的题目", "answer": ["A"]}]
    text = "没有编号但需要用户查看的原文"
    parsed = await OriginalQuestionParser(Settings(_env_file=None), helper=helper).parse(text, [chapter(text)])
    assert parsed["items"] == []
    assert any(c["status"] == "unrecognized" for c in parsed["coverage"])
    assert "模型编造" not in str(parsed)


async def test_source_locator_supports_unnumbered_originals_without_answer_invention():
    from app.services.original_question_parser import OriginalQuestionParser
    text = '[多选题] 原文要求选择全部步骤。\nA. 核对订单\nB. 确认权限\nC. 保留记录\nD. 忽略权限\nE. 提交主管\n答案：ABCE\n解析：原文讲解'
    async def helper(raw):
        return [{'start_offset': 0, 'end_offset': len(raw)}]
    parsed = await OriginalQuestionParser(Settings(_env_file=None), helper=helper).parse(text, [chapter(text)])
    assert len(parsed['items']) == 1 and parsed['items'][0]['answer'] == list('ABCE')
    assert parsed['items'][0]['stem'] == '原文要求选择全部步骤。' and len(parsed['items'][0]['options']) == 5
    assert parsed['coverage'][0]['status'] == 'recognized'
    assert sum(b['end_offset']-b['start_offset'] for b in parsed['coverage']) == len(text)
    without_answer = text.split('答案：')[0]
    parsed = await OriginalQuestionParser(Settings(_env_file=None), helper=helper).parse(without_answer, [chapter(without_answer)])
    assert parsed['items'][0]['answer'] == [] and 'missing_answer' in parsed['items'][0]['issues']


async def test_failed_locator_leaves_all_unrecognized_text_reviewable():
    from app.services.original_question_parser import OriginalQuestionParser
    async def broken(raw):
        raise RuntimeError('secret provider content')
    text = '[单选题] 尚未定位的题目\nA. 第一项\nB. 第二项'
    parsed = await OriginalQuestionParser(Settings(_env_file=None), helper=broken).parse(text, [chapter(text)])
    assert parsed['items'] == [] and parsed['coverage'][0]['quote'] == text
    assert parsed['issues'][0]['code'] == 'locator_unavailable' and 'secret' not in str(parsed)
