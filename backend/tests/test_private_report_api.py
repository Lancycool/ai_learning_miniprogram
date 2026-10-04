import pytest
from httpx import ASGITransport, AsyncClient
from app.api.dependencies import get_current_user, get_report_generator
from app.core.database import get_db
from app.db.models import Quiz, Question
from app.main import app
from app.models.report import ReportNarrative
from app.services.learning_service import LearningService
from tests.knowledge_helpers import make_knowledge_env


@pytest.mark.parametrize('count', [1, 2, 3, 4, 5])
async def test_private_report_keeps_long_originals_and_generic_public_share(tmp_path, count):
    env = await make_knowledge_env(tmp_path)
    class Generator:
        async def generate(self, request, score):
            assert len(request.questions) == count and len(request.questions[0].stem) == 5000
            assert request.questions[0].explanation is None
            assert request.answer_records[0].selected_answers == list('ABCDE')
            return ReportNarrative(three_line_summary=['学习原文流程。']*3, advice=['继续复习。'],
                share_quote='内部制度名称不能公开')
    async def database():
        async with env[1]() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: env[3]
    app.dependency_overrides[get_report_generator] = lambda: Generator()
    try:
        async with env[1]() as db:
            quiz = Quiz(public_id='private-report-quiz', user_id=env[3].id, title='内部原题',
                summary='原题', user_input='原题', source_type='original', generation_status='ready', question_count=count,
                prompt_version='original-v1')
            db.add(quiz); await db.flush()
            db.add_all([Question(public_id=f'private-report-q-{i}', quiz_id=quiz.id, sequence_no=i+1,
                question_type='multiple', stem='原文长题干'*1000,
                options_json=[{'key': chr(65+j), 'text': f'原文选项{j}'} for j in range(6)],
                answer_json=list('ABCDE'), explanation='', knowledge_point='原文流程', difficulty='medium',
                source_metadata_json={'kind': 'original', 'citations': [{'quote': '完整原文'}]}) for i in range(count)])
            await db.commit()
            practice = await LearningService(db).create_attempt(env[3], quiz.public_id)
            for i, q in enumerate(practice['questions']):
                await LearningService(db).submit_answer(env[3], practice['attempt_id'], q['question_id'], list('ABCDE'), 1000, f'report-answer-{i}')
            await LearningService(db).complete(env[3], practice['attempt_id'])
        async with AsyncClient(transport=ASGITransport(app), base_url='http://test') as api:
            response = await api.post(f"/api/v1/attempts/{practice['attempt_id']}/report")
            assert response.status_code == 200, response.text
            data = response.json()['data']
            assert data['total_count'] == count and data['accuracy'] == 100 and data['is_private']
            assert '内部制度' not in data['share_quote']
            saved = await api.post(f"/api/v1/attempts/{practice['attempt_id']}/report")
            assert saved.json()['data'] == data
    finally:
        app.dependency_overrides.clear()
        await env[0].dispose()
