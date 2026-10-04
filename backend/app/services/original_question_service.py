"""Original-question drafts are editable, versioned, and explicitly confirmed."""

from copy import deepcopy
from hashlib import sha256
import json

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.core.knowledge_errors import KnowledgeError
from app.db.base import utc_now
from app.db.models import (KnowledgeDocument, KnowledgeDocumentVersion, KnowledgeProcessingTask, QuestionBank,
                           QuestionBankItem, QuestionImportDraft, User)
from app.db.models import LearningAttempt, Question, QuestionPracticeGroup, Quiz
from app.services.learning_service import LearningService, question_view
from app.models.knowledge import OriginalDraftItem, OriginalQuestion
from app.services.auth_service import public_id
from app.services.knowledge_service import KnowledgeService, chapter_view
from app.services.original_question_parser import OriginalQuestionParser, merged_ranges


BLOCKING_ISSUES = {"missing_answer", "conflicting_answer", "duplicate_number", "unsupported_type",
                   "unknown_type", "invalid_options", "invalid_answer", "image_dependent"}


class OriginalQuestionService:
    def __init__(self, db, settings):
        self.db, self.settings = db, settings
        self.knowledge = KnowledgeService(db, settings)

    async def selected_chapters(self, user_id, version, chapter_ids):
        chapters = await self.knowledge.chapters(user_id, version)
        selected = None if chapter_ids is None else sorted(set(chapter_ids))
        if selected is not None and not set(selected).issubset({c.public_id for c in chapters}):
            raise ConflictError("所选章节已变化，请重新选择")
        return chapters, selected

    async def create_import(self, user, document_id, request):
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        doc = await self.knowledge.document(user.id, document_id, lock=True)
        version = await self.knowledge.version(user.id, doc, request.version_id)
        if not version.parsed_key or doc.parse_status != "ready":
            raise ConflictError("请先等待资料文字解析完成")
        _, selected = await self.selected_chapters(user.id, version, request.chapter_ids)
        payload = {"action": "original_import", "document_id": document_id, "version_id": version.public_id,
                   "chapter_ids": selected}
        previous = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.request_id == request.request_id))
        if previous:
            if previous.request_json != payload:
                raise ConflictError("同一请求编号不能用于不同导入范围")
            await self.db.commit()
            return await self.knowledge.task_view(user, previous.public_id)
        active = await self.db.scalar(select(KnowledgeProcessingTask.id).where(
            KnowledgeProcessingTask.document_id == doc.id, KnowledgeProcessingTask.user_id == user.id,
            KnowledgeProcessingTask.task_type == "original_import", KnowledgeProcessingTask.status.in_(("queued", "running"))))
        if active:
            raise ConflictError("原题正在提取，请等待任务完成")
        task = self.knowledge.new_task(user.id, doc.knowledge_base_id, doc.id, version.id,
                                       request.request_id, "original_import", payload)
        await self.db.commit()
        return await self.knowledge.task_view(user, task.public_id)

    async def owned_draft(self, user, draft_id, *, lock=False):
        self.knowledge.ensure_enabled()
        draft = await self.db.scalar(select(QuestionImportDraft).where(
            QuestionImportDraft.public_id == draft_id, QuestionImportDraft.user_id == user.id))
        if draft is None:
            raise ResourceNotFoundError()
        doc = await self.db.get(KnowledgeDocument, draft.document_id)
        await self.knowledge.document(user.id, doc.public_id, lock=lock)
        if lock:
            draft = await self.db.scalar(select(QuestionImportDraft).where(
                QuestionImportDraft.id == draft.id).with_for_update().execution_options(populate_existing=True))
        return draft, doc

    @staticmethod
    def confirmable(items):
        included = [q for q in items if not q["excluded"]]
        if not included or any(set(q["issues"]) & BLOCKING_ISSUES for q in included):
            return False
        try:
            for item in included:
                OriginalQuestion.model_validate(item)
        except ValidationError:
            return False
        return True

    async def draft_view(self, user, draft_id, page=1, page_size=20, coverage_page=1):
        draft, doc = await self.owned_draft(user, draft_id)
        version = await self.db.get(KnowledgeDocumentVersion, draft.version_id)
        chapters = await self.knowledge.chapters(user.id, version)
        return {"draft_id": draft.public_id, "document_id": doc.public_id, "version_id": version.public_id,
            "title": draft.title, "revision": draft.revision, "total": len(draft.items_json), "page": page,
            "items": draft.items_json[(page-1)*page_size:page*page_size], "can_confirm": self.confirmable(draft.items_json),
            "included_count": sum(not q["excluded"] for q in draft.items_json),
            "coverage": draft.coverage_json[(coverage_page-1)*20:coverage_page*20], "coverage_total": len(draft.coverage_json),
            "issues": draft.issues_json, "chapters": [chapter_view(c) for c in chapters],
            "selected_chapter_ids": draft.chapter_ids_json, "is_current_version": doc.current_version_id == draft.version_id}

    async def patch_draft(self, user, draft_id, request):
        draft, doc = await self.owned_draft(user, draft_id, lock=True)
        if draft.revision != request.revision or doc.current_version_id != draft.version_id:
            raise ConflictError("原题草稿或资料版本已经变化，请重新加载")
        version = await self.db.get(KnowledgeDocumentVersion, draft.version_id)
        chapters = await self.knowledge.chapters(user.id, version)
        legal_chapters = {c.public_id for c in chapters}
        existing = deepcopy(draft.items_json)
        positions = {item["id"]: index for index, item in enumerate(existing)}
        if len({item.id for item in request.items}) != len(request.items):
            raise KnowledgeError("duplicate_item", "同次修改不能重复提交同一道题")
        for model in request.items:
            item = model.model_dump(mode="json")
            if item["chapter_id"] is not None and item["chapter_id"] not in legal_chapters:
                raise ConflictError("原题章节不属于当前资料版本")
            old = existing[positions[item["id"]]] if item["id"] in positions else None
            fields = ("type", "stem", "options", "answer", "explanation", "chapter_id")
            edited = old is None or model.manually_edited or any(item[k] != old[k] for k in fields)
            item["source"] = deepcopy(old["source"]) if old else {"manual": True}
            item["manually_edited"] = bool(edited or (old and old["manually_edited"]))
            item["issues"] = [issue for issue in (old["issues"] if old else [])
                              if issue in ("duplicate_number", "conflicting_answer", "image_dependent") and not edited]
            OriginalQuestionParser.validate_review(item)
            OriginalDraftItem.model_validate(item)
            if old:
                existing[positions[item["id"]]] = item
            else:
                positions[item["id"]] = len(existing)
                existing.append(item)
        if len(existing) > self.settings.knowledge_max_import_questions:
            raise KnowledgeError("import_limit", "原题数量超过处理上限")
        draft.items_json = existing
        await self.db.commit()
        return await self.draft_view(user, draft_id)

    async def confirm(self, user, draft_id, request):
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        draft, doc = await self.owned_draft(user, draft_id, lock=True)
        payload = {"action": "confirm_original", "draft_id": draft_id, "revision": request.revision}
        recorded = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.request_id == request.request_id))
        if recorded:
            if recorded.request_json != payload or recorded.task_type != "confirm_original":
                raise ConflictError("同一确认编号不能用于不同草稿版本")
            await self.db.commit()
            return await self.bank_view(user, recorded.result_json["bank_id"])
        previous = await self.db.scalar(select(QuestionBank).where(
            QuestionBank.user_id == user.id, QuestionBank.confirm_request_id == request.request_id))
        if previous:
            if previous.draft_id != draft.id or previous.draft_revision != request.revision:
                raise ConflictError("同一确认编号不能用于不同草稿版本")
            await self.db.commit()
            return await self.bank_view(user, previous.public_id)
        previous = await self.db.scalar(select(QuestionBank).where(QuestionBank.user_id == user.id,
            QuestionBank.draft_id == draft.id, QuestionBank.draft_revision == request.revision))
        if previous:
            self.record_confirmation(user.id, doc, draft, request.request_id, payload, previous.public_id)
            await self.db.commit()
            return await self.bank_view(user, previous.public_id)
        if draft.revision != request.revision or doc.current_version_id != draft.version_id:
            raise ConflictError("原题草稿或资料版本已经变化，请重新加载")
        if not self.confirmable(draft.items_json):
            raise ConflictError("请补齐答案、核对问题或排除暂不支持的题目后，再确认入库")
        included = [q for q in draft.items_json if not q["excluded"]]
        bank = QuestionBank(public_id=public_id("bank"), user_id=user.id, document_id=doc.id,
            version_id=draft.version_id, draft_id=draft.id, draft_revision=draft.revision,
            confirm_request_id=request.request_id, title=draft.title, question_count=len(included))
        self.db.add(bank)
        await self.db.flush()
        for number, item in enumerate(included, 1):
            checked = OriginalQuestion.model_validate(item)
            self.db.add(QuestionBankItem(public_id=public_id("original"), user_id=user.id, bank_id=bank.id,
                sequence_no=number, chapter_id=checked.chapter_id, question_type=checked.type.value,
                stem=checked.stem, options_json=[o.model_dump(mode="json") for o in checked.options],
                answer_json=checked.answer, explanation=checked.explanation,
                source_json={**item["source"], "manually_edited": item["manually_edited"]}))
        self.record_confirmation(user.id, doc, draft, request.request_id, payload, bank.public_id)
        await self.db.commit()
        return await self.bank_view(user, bank.public_id)

    def record_confirmation(self, user_id, doc, draft, request_id, payload, bank_id):
        task = self.knowledge.new_task(user_id, doc.knowledge_base_id, doc.id, draft.version_id,
            request_id, "confirm_original", payload)
        task.status, task.stage, task.completed_at = "succeeded", "complete", utc_now()
        task.result_json = {"bank_id": bank_id}

    async def list_banks(self, user, document_id, page=1, page_size=20):
        doc = await self.knowledge.document(user.id, document_id)
        condition = (QuestionBank.user_id == user.id, QuestionBank.document_id == doc.id)
        total = await self.db.scalar(select(func.count()).select_from(QuestionBank).where(*condition))
        banks = (await self.db.scalars(select(QuestionBank).where(*condition).order_by(
            QuestionBank.id.desc()).offset((page-1)*page_size).limit(page_size))).all()
        return {"items": [{"bank_id": b.public_id, "title": b.title,
            "question_count": b.question_count, "draft_revision": b.draft_revision,
            "is_current_version": b.version_id == doc.current_version_id} for b in banks],
            "total": total, "page": page}

    async def owned_bank(self, user, bank_id):
        bank = await self.db.scalar(select(QuestionBank).where(QuestionBank.public_id == bank_id,
                                                              QuestionBank.user_id == user.id))
        if bank is None:
            raise ResourceNotFoundError()
        doc = await self.db.get(KnowledgeDocument, bank.document_id)
        await self.knowledge.document(user.id, doc.public_id)
        return bank, doc

    async def bank_view(self, user, bank_id, chapter_ids=None):
        bank, doc = await self.owned_bank(user, bank_id)
        version = await self.db.get(KnowledgeDocumentVersion, bank.version_id)
        chapters, selected = await self.selected_chapters(user.id, version, chapter_ids)
        allowed = None
        if selected is not None:
            ranges = merged_ranges([chapter_view(c) for c in chapters], selected)
            allowed = {c.public_id for c in chapters if any(a <= c.start_offset < c.end_offset <= b for a, b in ranges)}
        query = select(QuestionBankItem).where(QuestionBankItem.bank_id == bank.id, QuestionBankItem.user_id == user.id)
        if allowed is not None:
            query = query.where(QuestionBankItem.chapter_id.in_(allowed))
        items = (await self.db.scalars(query.order_by(QuestionBankItem.sequence_no))).all()
        return {"bank_id": bank.public_id, "document_id": doc.public_id, "version_id": version.public_id,
            "title": bank.title, "question_count": len(items), "selected_chapter_ids": selected,
            "chapters": [chapter_view(c) for c in chapters], "groups": [
                {"group_index": i//5, "question_count": len(items[i:i+5])} for i in range(0, len(items), 5)]}

    async def create_practice(self, user, bank_id, request):
        await self.db.scalar(select(User.id).where(User.id == user.id).with_for_update())
        bank, doc = await self.owned_bank(user, bank_id)
        view = await self.bank_view(user, bank_id, request.chapter_ids)
        if request.group_index >= len(view["groups"]):
            raise ResourceNotFoundError("没有找到该章节练习分组")
        payload = {"action": "original_practice", "bank_id": bank_id,
            "chapter_ids": view["selected_chapter_ids"], "group_index": request.group_index}
        previous = await self.db.scalar(select(KnowledgeProcessingTask).where(
            KnowledgeProcessingTask.user_id == user.id, KnowledgeProcessingTask.request_id == request.request_id))
        if previous:
            if previous.request_json != payload:
                raise ConflictError("同一请求编号不能用于不同练习分组")
            await self.db.commit()
            return await self.knowledge.task_view(user, previous.public_id)
        task = self.knowledge.new_task(user.id, doc.knowledge_base_id, doc.id, bank.version_id,
            request.request_id, "original_practice", payload)
        await self.db.commit()
        return await self.knowledge.task_view(user, task.public_id)

    async def publish_practice(self, user, payload):
        bank, doc = await self.owned_bank(user, payload["bank_id"])
        version = await self.db.get(KnowledgeDocumentVersion, bank.version_id)
        chapters, selected = await self.selected_chapters(user.id, version, payload["chapter_ids"])
        allowed = None
        if selected is not None:
            ranges = merged_ranges([chapter_view(c) for c in chapters], selected)
            allowed = {c.public_id for c in chapters if any(a <= c.start_offset < c.end_offset <= b for a, b in ranges)}
        query = select(QuestionBankItem).where(QuestionBankItem.bank_id == bank.id, QuestionBankItem.user_id == user.id)
        if allowed is not None:
            query = query.where(QuestionBankItem.chapter_id.in_(allowed))
        originals = (await self.db.scalars(query.order_by(QuestionBankItem.sequence_no)
                     .offset(payload["group_index"]*5).limit(5))).all()
        if not originals:
            raise ResourceNotFoundError("没有找到该章节练习分组")
        digest = sha256(json.dumps(selected, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        group = await self.db.scalar(select(QuestionPracticeGroup).where(QuestionPracticeGroup.user_id == user.id,
            QuestionPracticeGroup.bank_id == bank.id, QuestionPracticeGroup.scope_hash == digest,
            QuestionPracticeGroup.group_index == payload["group_index"]).with_for_update())
        if group:
            quiz = await self.db.get(Quiz, group.quiz_id)
        else:
            quiz = Quiz(public_id=public_id("quiz"), user_id=user.id, source_type="original",
                user_input=bank.title, title=bank.title, summary=f"原题练习 · 第 {payload['group_index']+1} 组 · 共 {len(originals)} 题",
                question_count=len(originals), difficulty="mixed", knowledge_metadata_json={"kind": "original",
                    "bank_id": bank.public_id, "version_id": version.public_id, "chapter_ids": selected,
                    "group_index": payload["group_index"]})
            self.db.add(quiz)
            await self.db.flush()
            chapter_titles = {c.public_id: c.title for c in chapters}
            for number, item in enumerate(originals, 1):
                chapter_title = chapter_titles.get(item.chapter_id, "未分章内容")
                snapshot = {"kind": "original", "document_title": doc.title, "document_id": doc.public_id,
                    "version_id": version.public_id, "chapter_id": item.chapter_id, "chapter_title": chapter_title,
                    "original_item_id": item.public_id, "manually_edited": item.source_json.get("manually_edited", False),
                    "missing_explanation": item.explanation is None,
                    "citations": [{"source_id": item.public_id, "quote": item.source_json.get("quote", "用户补充原题"),
                        "start_offset": item.source_json.get("start_offset"), "end_offset": item.source_json.get("end_offset")} ]}
                self.db.add(Question(public_id=public_id("q"), quiz_id=quiz.id, sequence_no=number,
                    question_type=item.question_type, stem=item.stem, options_json=item.options_json, answer_json=item.answer_json,
                    explanation=item.explanation or "", knowledge_point=chapter_title[:80], difficulty="medium",
                    original_item_id=item.id, source_metadata_json=snapshot))
            self.db.add(QuestionPracticeGroup(public_id=public_id("group"), user_id=user.id, bank_id=bank.id,
                scope_hash=digest, chapter_ids_json=selected or [], group_index=payload["group_index"], quiz_id=quiz.id))
            await self.db.flush()
        attempt = await LearningService(self.db).create_attempt(user, quiz.public_id, commit=False)
        return {"quiz_id": quiz.public_id, "attempt_id": attempt["attempt_id"], "title": quiz.title,
            "summary": quiz.summary, "user_input": quiz.user_input, "questions": attempt["questions"],
            "source_type": "original", "web_search": None}
