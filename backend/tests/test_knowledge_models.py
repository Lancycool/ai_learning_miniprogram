import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError

from app.db.models import (KnowledgeBase, KnowledgeDocument, KnowledgeDocumentVersion,
                           KnowledgeChapter, KnowledgeProcessingTask, QuestionImportDraft,
                           QuestionBank, QuestionBankItem, QuestionPracticeGroup, Quiz, Question)
from tests.knowledge_helpers import make_knowledge_env


@pytest.fixture
async def env(tmp_path):
    env = await make_knowledge_env(tmp_path)
    yield env
    await env[0].dispose()


async def base_document(db, user):
    kb = KnowledgeBase(public_id="kb-test", user_id=user.id, name="客服资料")
    db.add(kb)
    await db.flush()
    doc = KnowledgeDocument(public_id="doc-test", user_id=user.id, knowledge_base_id=kb.id,
                            title="原题文档", file_type="txt", file_size=100, file_hash="a" * 64)
    db.add(doc)
    await db.flush()
    version = KnowledgeDocumentVersion(public_id="ver-test", user_id=user.id, document_id=doc.id,
                                       version_no=1, source_key="owner/file.txt")
    db.add(version)
    await db.flush()
    doc.current_version_id = version.id
    return kb, doc, version


async def test_private_document_version_chapter_and_task_persist_in_mysql(env):
    engine, sessions, _, user, _ = env
    async with sessions() as db:
        kb, doc, version = await base_document(db, user)
        chapter = KnowledgeChapter(public_id="chapter-test", user_id=user.id, version_id=version.id,
                                   title="第一章", sequence_no=1, level=1, start_offset=0, end_offset=100)
        task = KnowledgeProcessingTask(public_id="ktask-test", user_id=user.id, knowledge_base_id=kb.id,
                                       document_id=doc.id, version_id=version.id,
                                       request_id="model-task-0001", task_type="parse_index", request_json={})
        db.add_all([chapter, task])
        await db.commit()
    async with sessions() as db:
        loaded = await db.scalar(select(KnowledgeProcessingTask))
        assert loaded.status == "queued" and loaded.stage == "queued"
        assert loaded.user_id == user.id and loaded.claim_token is None
        loaded.status, loaded.stage = "running", "parsing"
        await db.commit()
        assert (await db.scalar(select(KnowledgeDocument))).cleanup_status == "none"
        db.add(KnowledgeProcessingTask(public_id="ktask-dup", user_id=user.id, knowledge_base_id=kb.id,
                                      document_id=doc.id, version_id=version.id,
                                      request_id="model-task-0001", task_type="parse_index", request_json={}))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
    async with engine.connect() as conn:
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("knowledge_processing_tasks"))
        assert any(i["column_names"][:2] == ["status", "created_at"] for i in indexes)


async def test_chapter_offsets_and_document_version_uniqueness_are_enforced(env):
    async with env[1]() as db:
        _, doc, version = await base_document(db, env[3])
        await db.commit()
        document_id = doc.id
        db.add(KnowledgeChapter(public_id="chapter-bad", user_id=env[3].id, version_id=version.id,
                                title="章节", sequence_no=1, level=1, start_offset=10, end_offset=5))
        with pytest.raises(DBAPIError) as error:
            await db.commit()
        assert error.value.orig.args[0] == 3819
        await db.rollback()
        db.add(KnowledgeDocumentVersion(public_id="ver-duplicate", user_id=env[3].id, document_id=document_id,
                                        version_no=1, source_key="owner/file.txt"))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_original_draft_bank_and_stable_practice_group_constraints(env):
    async with env[1]() as db:
        kb, doc, version = await base_document(db, env[3])
        draft = QuestionImportDraft(public_id="draft-test", user_id=env[3].id,
                                    document_id=doc.id, version_id=version.id, title="原题", items_json=[], coverage_json=[])
        db.add(draft)
        await db.flush()
        assert draft.revision == 1
        bank = QuestionBank(public_id="bank-test", user_id=env[3].id, document_id=doc.id,
                            version_id=version.id, draft_id=draft.id, draft_revision=1,
                            confirm_request_id="confirm-test-0001", title="原题", question_count=1)
        db.add(bank)
        await db.flush()
        item = QuestionBankItem(public_id="item-test", user_id=env[3].id, bank_id=bank.id,
                                sequence_no=1, chapter_id="chapter-test", question_type="multiple",
                                stem="原题" * 500, options_json=[{"key": k, "text": k} for k in "ABCDE"],
                                answer_json=["A", "E"], explanation=None, source_json={"number": "1"})
        quiz = Quiz(public_id="quiz-bank", user_id=env[3].id, user_input="原题", title="原题",
                    summary="原题", question_count=1, source_type="original")
        db.add_all([item, quiz])
        await db.flush()
        group = QuestionPracticeGroup(public_id="group-test", user_id=env[3].id,
                                      bank_id=bank.id, scope_hash="c" * 64, chapter_ids_json=["chapter-test"],
                                      group_index=0, quiz_id=quiz.id)
        db.add(group)
        await db.commit()
        assert (await db.scalar(select(QuestionBankItem))).stem == "原题" * 500
        db.add(QuestionPracticeGroup(public_id="group-duplicate", user_id=env[3].id,
                                    bank_id=bank.id, scope_hash="c" * 64, chapter_ids_json=["chapter-test"],
                                    group_index=0, quiz_id=quiz.id))
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_long_original_snapshot_and_nullable_legacy_metadata(env):
    async with env[1]() as db:
        quiz = Quiz(public_id="quiz-long", user_id=env[3].id, user_input="培训", title="培训",
                    summary="培训", question_count=1)
        db.add(quiz)
        await db.flush()
        question = Question(public_id="que-long", quiz_id=quiz.id, sequence_no=1,
                            question_type="multiple", stem="题干" * 16000,
                            options_json=[{"key": k, "text": "选项" * 2000} for k in "ABCDE"],
                            answer_json=["A", "E"], explanation="讲解" * 16000,
                            knowledge_point="培训", difficulty="easy",
                            source_metadata_json={"type": "original", "version_id": "ver-snapshot"})
        db.add(question)
        await db.commit()
        assert quiz.knowledge_metadata_json is None
        assert question.original_item_id is None
        assert len((await db.scalar(select(Question))).stem) == 32000


async def test_draft_optimistic_version_rejects_concurrent_overwrite(env):
    async with env[1]() as db:
        _, doc, version = await base_document(db, env[3])
        draft = QuestionImportDraft(public_id="draft-race", user_id=env[3].id, document_id=doc.id,
                                    version_id=version.id, title="原题", items_json=[], coverage_json=[])
        db.add(draft)
        await db.commit()
    async with env[1]() as first, env[1]() as second:
        a = await first.scalar(select(QuestionImportDraft))
        b = await second.scalar(select(QuestionImportDraft))
        a.items_json = [{"stem": "用户第一次修订"}]
        await first.commit()
        assert a.revision == 2
        b.items_json = [{"stem": "过期页面修订"}]
        with pytest.raises(StaleDataError):
            await second.commit()


async def test_same_draft_revision_cannot_publish_two_banks(env):
    async with env[1]() as db:
        _, doc, version = await base_document(db, env[3])
        draft = QuestionImportDraft(public_id="draft-bank-unique", user_id=env[3].id, document_id=doc.id,
                                    version_id=version.id, title="原题", items_json=[], coverage_json=[])
        db.add(draft)
        await db.flush()
        values = dict(user_id=env[3].id, document_id=doc.id, version_id=version.id, draft_id=draft.id,
                      draft_revision=1, title="原题", question_count=1)
        db.add(QuestionBank(public_id="bank-unique-a", confirm_request_id="confirm-unique-a", **values))
        await db.commit()
        db.add(QuestionBank(public_id="bank-unique-b", confirm_request_id="confirm-unique-b", **values))
        with pytest.raises(IntegrityError):
            await db.commit()
