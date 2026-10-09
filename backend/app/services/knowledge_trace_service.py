"""Maintenance-only persistence for private retrieval diagnostics."""
from datetime import timedelta
import secrets

from sqlalchemy import desc, select, func

from app.db.base import utc_now
from app.db.knowledge_models import KnowledgeBadCase, KnowledgeRetrievalTrace
from app.services.auth_service import public_id


def maintenance_key_valid(settings, supplied: str | None) -> bool:
    expected = settings.knowledge_trace_admin_key.get_secret_value().strip()
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def bad_case_types(trace: dict) -> list[tuple[str, str, dict]]:
    cases: list[tuple[str, str, dict]] = []
    retrievals = trace.get("retrievals", [])
    if not retrievals:
        cases.append(("no_retrieval", "high", {"reason": "没有发生私有资料检索"}))
    elif not any(item.get("accepted") for item in retrievals):
        cases.append(("no_accepted_hit", "high", {"candidate_count": len(retrievals)}))
    validation = trace.get("validation", {})
    if validation.get("invalid_citation"):
        cases.append(("invalid_citation", "high", {"count": validation["invalid_citation"]}))
    if validation.get("unsupported_answer"):
        cases.append(("unsupported_answer", "high", {"count": validation["unsupported_answer"]}))
    if trace.get("error_code"):
        cases.append((trace["error_code"], "medium", {"message": trace.get("error_message", "")}))
    return cases


async def persist_trace(db, trace: dict | None, *, task_public_id: str, user_id: int, status: str,
                        error_code: str | None = None, error_message: str | None = None):
    if not trace:
        trace = {"retrievals": [], "agent_events": [], "selected_source_ids": [], "validation": {}, "timings": {}}
    trace["error_code"], trace["error_message"] = error_code, error_message
    item = KnowledgeRetrievalTrace(
        public_id=public_id("ktrace"), task_public_id=task_public_id, user_id=user_id,
        knowledge_base_id=trace.get("knowledge_base_id"), document_public_id=trace.get("document_public_id"),
        version_public_id=trace.get("version_public_id"), status=status,
        query_text=(trace.get("query") or "")[:1000], retrieval_json=trace.get("retrievals", []),
        agent_events_json=trace.get("agent_events", []), selected_source_ids_json=trace.get("selected_source_ids", []),
        validation_json=trace.get("validation", {}), timings_json=trace.get("timings", {}),
        error_code=error_code, error_message=(error_message or "")[:200] or None,
    )
    db.add(item)
    await db.flush()
    for case_type, severity, details in bad_case_types({**trace, "error_code": error_code, "error_message": error_message}):
        db.add(KnowledgeBadCase(public_id=public_id("kcase"), trace_id=item.id,
                                case_type=case_type, severity=severity, details_json=details))
    return item


def trace_view(item: KnowledgeRetrievalTrace, cases: list[KnowledgeBadCase]) -> dict:
    return {
        "trace_id": item.public_id, "task_id": item.task_public_id, "status": item.status,
        "knowledge_base_id": item.knowledge_base_id, "document_id": item.document_public_id,
        "version_id": item.version_public_id, "query": item.query_text,
        "retrievals": item.retrieval_json, "agent_events": item.agent_events_json,
        "selected_source_ids": item.selected_source_ids_json, "validation": item.validation_json,
        "timings": item.timings_json, "error_code": item.error_code, "error_message": item.error_message,
        "created_at": item.created_at,
        "bad_cases": [{"bad_case_id": c.public_id, "type": c.case_type, "severity": c.severity,
                        "status": c.status, "details": c.details_json, "created_at": c.created_at} for c in cases],
    }


async def list_traces(db, *, trace_id=None, task_id=None, document_id=None, status=None, case_type=None,
                      page=1, page_size=20, retention_days=30):
    query = select(KnowledgeRetrievalTrace).order_by(desc(KnowledgeRetrievalTrace.created_at))
    cutoff = utc_now() - timedelta(days=retention_days)
    query = query.where(KnowledgeRetrievalTrace.created_at >= cutoff)
    if trace_id: query = query.where(KnowledgeRetrievalTrace.public_id == trace_id)
    if task_id: query = query.where(KnowledgeRetrievalTrace.task_public_id == task_id)
    if document_id: query = query.where(KnowledgeRetrievalTrace.document_public_id == document_id)
    if status: query = query.where(KnowledgeRetrievalTrace.status == status)
    if case_type:
        query = query.join(KnowledgeBadCase, KnowledgeBadCase.trace_id == KnowledgeRetrievalTrace.id).where(KnowledgeBadCase.case_type == case_type).distinct()
    total = await db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    rows = (await db.scalars(query.offset((page - 1) * page_size).limit(page_size))).all()
    values = []
    for item in rows:
        cases = (await db.scalars(select(KnowledgeBadCase).where(KnowledgeBadCase.trace_id == item.id).order_by(KnowledgeBadCase.id))).all()
        values.append(trace_view(item, cases))
    return {"items": values, "total": total or 0, "page": page, "page_size": page_size}
