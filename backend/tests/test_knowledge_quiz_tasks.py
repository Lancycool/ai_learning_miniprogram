import asyncio

import pytest
from sqlalchemy import select

from app.db.models import KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion, QuizGenerationTask, Question, Quiz
from app.models.knowledge_quiz import KnowledgeGeneratedQuiz
from app.models.quiz import Quiz as GeneratedQuiz
from app.models.quiz_task import QuizTaskCreateRequest
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from app.services.quiz_task_service import QuizTaskService, QuizTaskWorker
from app.services.web_search_service import WebSearchService
from tests.test_knowledge_processing import processing_env
from tests.test_services import build_questions


class PrivateGenerator:
    def __init__(self):
        self.entered, self.release = asyncio.Event(), asyncio.Event()
        self.release.set()
    async def generate(self, request, scopes, task_id):
        self.entered.set()
        await self.release.wait()
        assert scopes[0]["user_id"] == 1
        quiz = GeneratedQuiz(quiz_id="private-generated-quiz", user_input=request.user_input, title="客服培训",
            summary="根据所选资料学习客服流程", questions=build_questions())
        return KnowledgeGeneratedQuiz(quiz, [{"kind": "knowledge", "citations": [{"source_id": "source-one",
            "quote": "客服先核对订单。"}]} for _ in quiz.questions])


async def private_request(env):
    from pydantic import SecretStr
    from app.services.bailian_embeddings import BailianEmbeddings
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    env[2].bailian_api_key = SecretStr("synthetic")
    async with env[1]() as db:
        doc = await db.scalar(select(KnowledgeDocument))
        version = await db.get(KnowledgeDocumentVersion, doc.current_version_id)
        base = await db.get(KnowledgeBase, doc.knowledge_base_id)
        doc.index_status = "ready"
        version.index_generation, version.embedding_fingerprint = "index-synthetic", BailianEmbeddings(env[2]).fingerprint
        await db.commit()
        return QuizTaskCreateRequest(request_id="private-quiz-task-0001", user_input="客服流程",
            knowledge_scope={"knowledge_base_id": base.public_id, "documents": [{"document_id": doc.public_id,
                "version_id": version.public_id}]})


def runner(env, generator):
    def forbidden():
        pytest.fail("Private request reached ordinary memory generator")
    return QuizTaskWorker(env[1], env[2], forbidden, lambda: WebSearchService(env[2]), knowledge_generator=lambda: generator)


async def test_private_task_dispatch_and_atomic_snapshot_publish(processing_env):
    env = processing_env
    request = await private_request(env)
    async with env[1]() as db:
        task = await QuizTaskService(db, env[2]).create(env[3], request)
        assert task["status"] == "queued" and task["result"] is None
    generator = PrivateGenerator()
    await runner(env, generator).run_once()
    async with env[1]() as db:
        view = await QuizTaskService(db, env[2]).view(env[3], task["task_id"])
        assert view["status"] == "succeeded" and "sources" not in str(view["result"]["questions"])
        quiz = await db.scalar(select(Quiz))
        assert quiz.source_type == "knowledge" and quiz.knowledge_metadata_json
        questions = (await db.scalars(select(Question))).all()
        assert all(q.source_metadata_json["kind"] == "knowledge" for q in questions)


async def test_private_task_rechecks_deletion_before_late_publish(processing_env):
    env = processing_env
    request = await private_request(env)
    async with env[1]() as db:
        task = await QuizTaskService(db, env[2]).create(env[3], request)
    generator = PrivateGenerator()
    generator.release.clear()
    running = asyncio.create_task(runner(env, generator).run_once())
    await asyncio.wait_for(generator.entered.wait(), 10)
    async with env[1]() as db:
        await KnowledgeService(db, env[2]).delete_document(env[3], env[5]["document"]["document_id"])
    generator.release.set()
    await running
    async with env[1]() as db:
        view = await QuizTaskService(db, env[2]).view(env[3], task["task_id"])
        assert view["status"] == "failed" and view["result"] is None
        assert (await db.scalars(select(Quiz))).all() == []


async def test_scope_is_validated_before_queue_and_private_flag_off_rejects(processing_env):
    env = processing_env
    request = await private_request(env)
    async with env[1]() as db:
        with pytest.raises(Exception) as caught:
            await QuizTaskService(db, env[2]).create(env[4], request)
        assert caught.value.status_code == 404
        env[2].enable_knowledge_base = False
        with pytest.raises(Exception) as caught:
            await QuizTaskService(db, env[2]).create(env[3], request)
        assert caught.value.status_code == 503
