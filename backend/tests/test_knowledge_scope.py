import pytest
from pydantic import ValidationError

from app.core.exceptions import ConflictError, ResourceNotFoundError
from app.models.knowledge import KnowledgeScope
from app.models.quiz_task import QuizTaskCreateRequest
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from tests.test_knowledge_processing import processing_env


def selected(doc, chapters=None):
    return {"knowledge_base_id": "kb-example", "documents": [{"document_id": doc["document_id"],
        "version_id": doc["version_id"], "chapter_ids": chapters}]}


def test_private_request_defaults_to_no_web_and_requires_explicit_public_topic():
    scope = selected({"document_id": "doc", "version_id": "version"})
    private = QuizTaskCreateRequest(request_id="private-generation-0001", user_input="客服流程", knowledge_scope=scope)
    assert private.enable_web_search is False
    assert QuizTaskCreateRequest(request_id="ordinary-generation-001", user_input="普通主题").enable_web_search is None
    with pytest.raises(ValidationError):
        QuizTaskCreateRequest(request_id="private-generation-0001", user_input="客服流程", knowledge_scope=scope, enable_web_search=True)
    allowed = QuizTaskCreateRequest(request_id="private-generation-0001", user_input="客服流程", knowledge_scope=scope,
        enable_web_search=True, public_search_topic="公开客服服务知识", public_search_confirmed=True)
    assert allowed.enable_web_search is True
    with pytest.raises(ValidationError):
        QuizTaskCreateRequest(request_id="private-generation-0001", user_input="客服流程", knowledge_scope=scope, question_count=3)


async def test_server_scope_expands_only_owned_selected_chapters_and_current_version(processing_env):
    env = processing_env
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        doc = env[5]["document"]
        preview = await service.preview(env[3], doc["document_id"])
        document = await service.document(env[3].id, doc["document_id"])
        from app.db.models import KnowledgeBase
        base = await db.get(KnowledgeBase, document.knowledge_base_id)
        scope = KnowledgeScope.model_validate({**selected(doc, [preview["chapters"][1]["chapter_id"]]), "knowledge_base_id": base.public_id})
        resolved = await service.resolve_scope(env[3], scope, require_index=False)
        assert len(resolved) == 1 and resolved[0]["chapter_ids"] == [preview["chapters"][1]["chapter_id"]]
        assert resolved[0]["user_id"] == env[3].id
        with pytest.raises(ResourceNotFoundError):
            await service.resolve_scope(env[4], scope, require_index=False)
        bad = scope.model_copy(deep=True)
        bad.documents[0].chapter_ids = ["foreign-chapter"]
        with pytest.raises(ConflictError):
            await service.resolve_scope(env[3], bad, require_index=False)
        bad.documents[0].chapter_ids, bad.documents[0].version_id = None, "obsolete-version"
        with pytest.raises(ConflictError):
            await service.resolve_scope(env[3], bad, require_index=False)
        await service.delete_document(env[3], doc["document_id"])
        with pytest.raises(ResourceNotFoundError):
            await service.resolve_scope(env[3], scope, require_index=False)
