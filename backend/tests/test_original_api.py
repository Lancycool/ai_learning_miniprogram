import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.main import app
from app.services.knowledge_task_service import KnowledgeTaskWorker
from tests.test_original_service import original_env


async def test_original_routes_preview_edit_confirm_and_ownership(original_env, monkeypatch):
    env = original_env
    async def database():
        async with env[1]() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: env[3]
    app.dependency_overrides[get_settings] = lambda: env[2]
    doc = env[5]["document"]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as api:
        imported = await api.post(f"/api/v1/knowledge-documents/{doc['document_id']}/question-import-tasks",
            json={"version_id": doc["version_id"], "request_id": "api-original-import-0001"})
        assert imported.status_code == 202
        await KnowledgeTaskWorker(env[1], env[2]).run_once()
        view = (await api.get(f"/api/v1/knowledge-processing-tasks/{imported.json()['data']['task_id']}")).json()["data"]
        draft_id = view["result"]["draft_id"]
        draft = (await api.get(f"/api/v1/question-imports/{draft_id}")).json()["data"]
        assert draft["total"] == 2 and not draft["can_confirm"]
        assert (await api.post(f"/api/v1/question-imports/{draft_id}/confirm", json={"revision": 1,
            "request_id": "api-original-confirm-0001"})).status_code == 409
        patched = await api.patch(f"/api/v1/question-imports/{draft_id}", json={"revision": 1,
            "items": [{**draft["items"][1], "excluded": True}]})
        assert patched.status_code == 200
        confirmed = await api.post(f"/api/v1/question-imports/{draft_id}/confirm", json={
            "revision": patched.json()["data"]["revision"], "request_id": "api-original-confirm-0001"})
        assert confirmed.status_code == 201
        bank_id = confirmed.json()["data"]["bank_id"]
        assert (await api.get(f"/api/v1/question-banks/{bank_id}")).json()["data"]["question_count"] == 1
        banks = (await api.get(f"/api/v1/knowledge-documents/{doc['document_id']}/question-banks")).json()['data']
        assert banks['items'][0]['bank_id'] == bank_id
        practice = await api.post(f'/api/v1/question-banks/{bank_id}/practice-tasks', json={
            'group_index': 0, 'request_id': 'api-original-practice-0001'})
        assert practice.status_code == 202
        await KnowledgeTaskWorker(env[1], env[2]).run_once()
        task = (await api.get(f"/api/v1/knowledge-processing-tasks/{practice.json()['data']['task_id']}")).json()['data']
        attempt = task['result']; attempt_id = attempt['attempt_id']
        assert all('sources' not in q and 'answer' not in q for q in attempt['questions'])
        assert (await api.post(f'/api/v1/attempts/{attempt_id}/answers', json={
            'question_id': attempt['questions'][0]['question_id'], 'selected_answers': ['E'],
            'duration_ms': 1000, 'idempotency_key': 'api-original-answer-0001'})).json()['data']['is_correct']
        assert (await api.post(f'/api/v1/attempts/{attempt_id}/complete')).json()['data']['total_count'] == 1
        deleted = await api.delete(f"/api/v1/knowledge-documents/{doc['document_id']}")
        await KnowledgeTaskWorker(env[1], env[2]).run_once()
        assert (await api.get(f"/api/v1/knowledge-processing-tasks/{deleted.json()['data']['cleanup_task_id']}")).json()['data']['status'] == 'succeeded'
        env[2].enable_knowledge_base = False
        assert (await api.get('/api/v1/knowledge-bases/capabilities')).json()['data']['enabled'] is False
        assert (await api.post('/api/v1/knowledge-bases', json={'name':'关闭时不能创建'})).status_code == 503
        history = (await api.get(f'/api/v1/learning/history/{attempt_id}')).json()['data']
        assert history['accuracy'] == 100 and history['questions'][0]['sources']['kind'] == 'original'
        replay = (await api.post('/api/v1/attempts', json={'quiz_id': attempt['quiz_id'], 'attempt_type': 'replay'})).json()['data']
        assert all('sources' not in q and 'answer' not in q for q in replay['questions'])
        # Ordinary generation stays available when the private feature is off.
        from app.api.v1.routes import quizzes
        from app.api.dependencies import get_quiz_generator
        from tests.test_user_system_api import FakeQuizGenerator
        monkeypatch.setattr(quizzes, 'get_settings', lambda: env[2])
        app.dependency_overrides[get_quiz_generator] = lambda: FakeQuizGenerator()
        assert (await api.post('/api/v1/quizzes/generate', json={'user_input': '学习 RAG 的基本概念'})).status_code == 200
        env[2].enable_knowledge_base = True
        app.dependency_overrides[get_current_user] = lambda: env[4]
        for path in (f"/api/v1/question-imports/{draft_id}", f"/api/v1/question-banks/{bank_id}"):
            assert (await api.get(path)).status_code == 404
        assert (await api.patch(f"/api/v1/question-imports/{draft_id}", json={"revision": 2, "items": [draft["items"][0]]})).status_code == 404
        assert (await api.post(f"/api/v1/question-imports/{draft_id}/confirm", json={"revision": 2,
            "request_id": "api-foreign-confirm-0001"})).status_code == 404
