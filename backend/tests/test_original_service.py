import pytest
from sqlalchemy import func, select

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.db.models import KnowledgeProcessingTask, QuestionBank, QuestionBankItem
from app.models.knowledge import (ImportTaskInput, ImportDraftPatch, ImportConfirmInput, KnowledgeBaseInput,
                                  TextDocumentInput)
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from tests.knowledge_helpers import make_knowledge_env


@pytest.fixture
async def original_env(tmp_path):
    env = await make_knowledge_env(tmp_path)
    text = "第一章\n1. [单选题] 客服第一步？\nA. 核对订单\nB. 跳过检查\nC. 删除记录\nD. 直接退款\nE. 向主管确认\n答案：E\n2. [判断题] 退款需要主管确认。\n"
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        base = await service.create_base(env[3], KnowledgeBaseInput(name="原题培训"))
        task = await service.save_text(env[3], base["knowledge_base_id"], TextDocumentInput(
            title="原题", text=text, request_id="original-upload-0001"))
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    yield (*env, task)
    await env[0].dispose()


async def imported(env):
    from app.services.original_question_service import OriginalQuestionService
    async with env[1]() as db:
        doc_id = env[5]["document"]["document_id"]
        version = env[5]["document"]["version_id"]
        request = ImportTaskInput(request_id="original-import-0001", version_id=version)
        first = await OriginalQuestionService(db, env[2]).create_import(env[3], doc_id, request)
        repeated = await OriginalQuestionService(db, env[2]).create_import(env[3], doc_id, request)
        assert first["task_id"] == repeated["task_id"] and first["status"] == "queued"
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        view = await KnowledgeService(db, env[2]).task_view(env[3], first["task_id"])
        assert view["status"] == "succeeded"
        return view["result"]["draft_id"]


async def test_import_needs_no_embedding_and_preview_is_owned_paginated(original_env):
    from app.services.original_question_service import OriginalQuestionService
    env = original_env
    draft_id = await imported(env)
    async with env[1]() as db:
        service = OriginalQuestionService(db, env[2])
        page = await service.draft_view(env[3], draft_id, page=1, page_size=1)
        assert page["total"] == 2 and len(page["items"]) == 1 and len(page["items"][0]["options"]) == 5
        assert page["items"][0]["answer"] == ["E"] and page["can_confirm"] is False
        with pytest.raises(ResourceNotFoundError):
            await service.draft_view(env[4], draft_id)


async def test_edit_answer_revision_conflict_atomic_confirmation_and_idempotency(original_env):
    from app.services.original_question_service import OriginalQuestionService
    env = original_env
    draft_id = await imported(env)
    async with env[1]() as db:
        service = OriginalQuestionService(db, env[2])
        draft = await service.draft_view(env[3], draft_id)
        confirm = ImportConfirmInput(revision=draft["revision"], request_id="original-confirm-0001")
        with pytest.raises(ConflictError):
            await service.confirm(env[3], draft_id, confirm)
        assert await db.scalar(select(func.count()).select_from(QuestionBank)) == 0
        changed = {**draft["items"][1], "answer": ["A"]}
        updated = await service.patch_draft(env[3], draft_id, ImportDraftPatch(revision=draft["revision"], items=[changed]))
        assert updated["revision"] == draft["revision"]+1 and updated["can_confirm"]
        assert updated["items"][1]["manually_edited"] is True
        assert len(updated["items"]) == 2
        with pytest.raises(ConflictError):
            await service.patch_draft(env[3], draft_id, ImportDraftPatch(revision=draft["revision"], items=[changed]))
        confirm = confirm.model_copy(update={"revision": updated["revision"]})
        bank = await service.confirm(env[3], draft_id, confirm)
        same = await service.confirm(env[3], draft_id, confirm)
        other_id = await service.confirm(env[3], draft_id, confirm.model_copy(update={"request_id": "original-confirm-0002"}))
        assert bank["bank_id"] == same["bank_id"] == other_id["bank_id"]
        assert bank["question_count"] == 2
        discovered = await service.list_banks(env[3], env[5]['document']['document_id'])
        assert discovered['total'] == 1 and discovered['items'][0]['bank_id'] == bank['bank_id']
        with pytest.raises(ResourceNotFoundError):
            await service.list_banks(env[4], env[5]['document']['document_id'])
        stored = (await db.scalars(select(QuestionBankItem).order_by(QuestionBankItem.sequence_no))).all()
        assert stored[0].answer_json == ["E"] and len(stored[0].options_json) == 5
        assert stored[0].explanation is None and stored[1].source_json["manually_edited"] is True
        revised = await service.patch_draft(env[3], draft_id, ImportDraftPatch(revision=updated["revision"],
            items=[{**updated["items"][0], "stem": "用户修订的客服流程原题？"}]))
        with pytest.raises(ConflictError):
            await service.confirm(env[3], draft_id, ImportConfirmInput(revision=revised["revision"],
                request_id="original-confirm-0002"))


async def test_manual_addition_exclusion_and_user_metadata_cannot_fake_source(original_env):
    from app.services.original_question_service import OriginalQuestionService
    env = original_env
    draft_id = await imported(env)
    async with env[1]() as db:
        service = OriginalQuestionService(db, env[2])
        draft = await service.draft_view(env[3], draft_id)
        excluded = {**draft["items"][1], "excluded": True}
        manual = {"id": "manual-user-question", "type": "single", "stem": "用户补充的题目？", "answer": ["A"],
            "options": [{"key": "A", "text": "用户选项一"}, {"key": "B", "text": "用户选项二"}],
            "source": {"quote": "伪造来源", "start_offset": 999}, "chapter_id": draft["items"][0]["chapter_id"]}
        updated = await service.patch_draft(env[3], draft_id, ImportDraftPatch(revision=draft["revision"], items=[excluded, manual]))
        assert updated["total"] == 3 and updated["can_confirm"]
        added = updated["items"][-1]
        assert added["manually_edited"] is True and "伪造来源" not in str(added["source"])
        bank = await service.confirm(env[3], draft_id, ImportConfirmInput(revision=updated["revision"], request_id="manual-confirm-0001"))
        assert bank["question_count"] == 2


async def test_import_rejects_foreign_chapters_and_deleted_documents(original_env):
    from app.services.original_question_service import OriginalQuestionService
    env = original_env
    async with env[1]() as db:
        service = OriginalQuestionService(db, env[2])
        request = ImportTaskInput(request_id="original-invalid-0001", version_id=env[5]["document"]["version_id"], chapter_ids=["foreign-chapter"])
        with pytest.raises(ConflictError):
            await service.create_import(env[3], env[5]["document"]["document_id"], request)
    draft_id = await imported(env)
    async with env[1]() as db:
        await KnowledgeService(db, env[2]).delete_document(env[3], env[5]["document"]["document_id"])
        with pytest.raises(ResourceNotFoundError):
            await OriginalQuestionService(db, env[2]).draft_view(env[3], draft_id)
