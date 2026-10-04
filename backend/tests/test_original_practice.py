import pytest
import asyncio
from sqlalchemy import func, select

from app.db.models import KnowledgeDocumentVersion, Question, Quiz, QuestionPracticeGroup
from app.models.knowledge import (ImportConfirmInput, ImportTaskInput, KnowledgeBaseInput, OriginalPracticeInput, TextDocumentInput)
from app.services.knowledge_service import KnowledgeService
from app.services.knowledge_task_service import KnowledgeTaskWorker
from app.services.learning_service import LearningService
from tests.knowledge_helpers import make_knowledge_env


@pytest.fixture
async def practice_env(tmp_path):
    from app.services.original_question_service import OriginalQuestionService
    env = await make_knowledge_env(tmp_path)
    text = "第一章\n"+"\n".join(f"{i}. [单选题] 客服第{i}题应如何处理？\nA. 跳过检查\nB. 删除记录\nC. 直接退款\nD. 关闭会话\nE. 核对订单\n答案：E" for i in range(1, 13))
    async with env[1]() as db:
        service = KnowledgeService(db, env[2])
        base = await service.create_base(env[3], KnowledgeBaseInput(name="原题练习"))
        uploaded = await service.save_text(env[3], base["knowledge_base_id"], TextDocumentInput(
            title="十二原题", text=text, request_id="practice-upload-0001"))
    runner = KnowledgeTaskWorker(env[1], env[2])
    await runner.run_once()
    async with env[1]() as db:
        imported = await OriginalQuestionService(db, env[2]).create_import(env[3], uploaded["document"]["document_id"],
            ImportTaskInput(request_id="practice-import-0001", version_id=uploaded["document"]["version_id"]))
    await runner.run_once()
    async with env[1]() as db:
        view = await KnowledgeService(db, env[2]).task_view(env[3], imported["task_id"])
        bank = await OriginalQuestionService(db, env[2]).confirm(env[3], view["result"]["draft_id"],
            ImportConfirmInput(revision=1, request_id="practice-confirm-0001"))
    yield (*env, uploaded, bank)
    await env[0].dispose()


async def start_practice(env, group, request_id):
    from app.services.original_question_service import OriginalQuestionService
    async with env[1]() as db:
        task = await OriginalQuestionService(db, env[2]).create_practice(env[3], env[6]["bank_id"],
            OriginalPracticeInput(request_id=request_id, group_index=group))
        repeat = await OriginalQuestionService(db, env[2]).create_practice(env[3], env[6]["bank_id"],
            OriginalPracticeInput(request_id=request_id, group_index=group))
        assert repeat["task_id"] == task["task_id"]
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        view = await KnowledgeService(db, env[2]).task_view(env[3], task["task_id"])
        assert view["status"] == "succeeded"
        return view["result"]


async def test_twelve_originals_form_stable_five_five_two_without_cloud(practice_env):
    env = practice_env
    assert [g["question_count"] for g in env[6]["groups"]] == [5, 5, 2]
    results = [await start_practice(env, i, f"practice-start-group-{i}") for i in range(3)]
    assert [len(r["questions"]) for r in results] == [5, 5, 2]
    assert all("answer" not in q and "sources" not in q for r in results for q in r["questions"])
    repeated = await start_practice(env, 2, "practice-repeat-group-2")
    assert repeated["quiz_id"] == results[2]["quiz_id"] and repeated["attempt_id"] != results[2]["attempt_id"]
    assert [q["question_id"] for q in repeated["questions"]] == [q["question_id"] for q in results[2]["questions"]]
    async with env[1]() as db:
        assert await db.scalar(select(func.count()).select_from(Quiz)) == 3
        assert await db.scalar(select(func.count()).select_from(QuestionPracticeGroup)) == 3
        repeat = await LearningService(db).get_attempt(env[3], repeated["attempt_id"])
        assert repeat["attempt_type"] == "replay"


async def test_tail_group_grading_sources_delete_and_replay(practice_env):
    env = practice_env
    result = await start_practice(env, 2, "practice-tail-start-0001")
    async with env[1]() as db:
        learning = LearningService(db)
        for i, question in enumerate(result["questions"]):
            await learning.submit_answer(env[3], result["attempt_id"], question["question_id"], ["E"], 1000, f"answer-original-{i}")
        completion = await learning.complete(env[3], result["attempt_id"])
        assert completion["total_count"] == 2 and completion["accuracy"] == 100
        completed = await learning.get_attempt(env[3], result["attempt_id"])
        assert completed['is_private'] is True and completed['source_type'] == 'original'
        assert all(q["sources"]["kind"] == "original" for q in completed["questions"])
        assert all(q["answer"] == ["E"] for q in completed["questions"])
        replay = await learning.create_attempt(env[3], result["quiz_id"], "replay")
        assert all("answer" not in q and "sources" not in q for q in replay["questions"])
        await KnowledgeService(db, env[2]).delete_document(env[3], env[5]["document"]["document_id"])
    await KnowledgeTaskWorker(env[1], env[2]).run_once()
    async with env[1]() as db:
        saved = await LearningService(db).get_attempt(env[3], result["attempt_id"])
        assert saved["accuracy"] == 100 and saved["questions"][0]["sources"]
        assert await db.scalar(select(func.count()).select_from(Question)) == 2


async def test_concurrent_original_attempts_have_only_one_first_normal(practice_env):
    from app.db.models import User, LearningAttempt
    env = practice_env
    result = await start_practice(env, 2, 'concurrent-original-start-0001')
    # Remove the setup attempt. The two callers below must both begin a MySQL
    # consistent-read snapshot before either inserts the first normal attempt.
    from sqlalchemy import delete
    async with env[1]() as db:
        await db.execute(delete(LearningAttempt)); await db.commit()
    arrived, release = 0, asyncio.Event()
    async def start():
        nonlocal arrived
        async with env[1]() as db:
            user = await db.get(User, env[3].id)
            await db.scalar(select(LearningAttempt.id).limit(1))
            arrived += 1
            if arrived == 2: release.set()
            await release.wait()
            return await LearningService(db).create_attempt(user, result['quiz_id'])
    attempts = await asyncio.wait_for(asyncio.gather(start(), start()), 15)
    assert sorted(a['attempt_type'] for a in attempts) == ['normal', 'replay']


async def test_mixed_mistake_review_hides_private_sources_until_complete(practice_env):
    from app.db.models import MistakeRecord
    from app.db.base import utc_now
    from datetime import timedelta
    from sqlalchemy import update
    env = practice_env
    result = await start_practice(env, 2, 'mixed-review-start-0001')
    async with env[1]() as db:
        service = LearningService(db)
        for i, q in enumerate(result['questions']):
            await service.submit_answer(env[3], result['attempt_id'], q['question_id'], ['A'], 1000, f'mixed-original-{i}')
        await service.complete(env[3], result['attempt_id'])
        ordinary = Quiz(public_id='mixed-ordinary', user_id=env[3].id, title='普通主题', summary='普通', user_input='普通主题', question_count=1)
        db.add(ordinary); await db.flush()
        question = Question(public_id='mixed-ordinary-q', quiz_id=ordinary.id, sequence_no=1, question_type='single',
            stem='普通题目？', options_json=[{'key':'A','text':'一'},{'key':'B','text':'二'}], answer_json=['A'],
            explanation='普通题目讲解。', knowledge_point='普通知识', difficulty='easy')
        db.add(question); await db.flush()
        db.add(MistakeRecord(user_id=env[3].id, question_id=question.id, next_review_at=utc_now()-timedelta(days=2)))
        await db.flush()
        await db.execute(update(MistakeRecord).where(MistakeRecord.user_id == env[3].id).values(next_review_at=utc_now()-timedelta(days=2)))
        await db.commit()
        review = await service.create_review(env[3])
        assert review['is_private'] and len(review['questions']) == 3
        assert all('answer' not in q and 'sources' not in q for q in review['questions'])
        for i, q in enumerate(review['questions']):
            await service.submit_answer(env[3], review['attempt_id'], q['question_id'], ['A'], 1000, f'mixed-review-{i}')
            midway = await service.get_attempt(env[3], review['attempt_id'])
            assert all('sources' not in x for x in midway['questions'])
        await service.complete(env[3], review['attempt_id'])
        done = await service.get_attempt(env[3], review['attempt_id'])
        assert sum(bool(q.get('sources')) for q in done['questions']) == 2
