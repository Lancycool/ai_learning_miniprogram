from sqlalchemy import select
from pydantic import SecretStr

from app.core.config import Settings
from app.db.knowledge_models import KnowledgeBadCase, KnowledgeRetrievalTrace
from app.services.knowledge_trace_service import bad_case_types, maintenance_key_valid, persist_trace
from tests.test_knowledge_processing import processing_env


def test_bad_case_detection_and_maintenance_key():
    settings = Settings(_env_file=None, KNOWLEDGE_TRACE_ADMIN_KEY="maintenance-secret")
    settings.knowledge_trace_admin_key = SecretStr("maintenance-secret")
    assert maintenance_key_valid(settings, "maintenance-secret")
    assert not maintenance_key_valid(settings, "wrong")
    cases = bad_case_types({"retrievals": [], "validation": {}, "error_code": "insufficient_material"})
    assert {case[0] for case in cases} == {"no_retrieval", "insufficient_material"}


async def test_trace_persistence_creates_bad_case(processing_env):
    engine, sessions, settings, user, _, _ = processing_env
    trace = {"query": "退款审批", "knowledge_base_id": "kb-one", "document_public_id": "doc-one",
             "version_public_id": "ver-one", "retrievals": [{"source_id": "s1", "accepted": False,
             "filter_reason": "distance_threshold", "distance": 0.9}], "agent_events": [],
             "selected_source_ids": [], "validation": {}, "timings": {}}
    async with sessions() as db, db.begin():
        item = await persist_trace(db, trace, task_public_id="qtask-trace-0001", user_id=user.id, status="failed",
                                   error_code="insufficient_material", error_message="资料不足")
        assert item.public_id.startswith("ktrace_")
    async with sessions() as db:
        saved = await db.scalar(select(KnowledgeRetrievalTrace).where(KnowledgeRetrievalTrace.task_public_id == "qtask-trace-0001"))
        cases = (await db.scalars(select(KnowledgeBadCase).where(KnowledgeBadCase.trace_id == saved.id))).all()
        assert saved.status == "failed" and saved.retrieval_json[0]["filter_reason"] == "distance_threshold"
        assert {case.case_type for case in cases} == {"no_accepted_hit", "insufficient_material"}
