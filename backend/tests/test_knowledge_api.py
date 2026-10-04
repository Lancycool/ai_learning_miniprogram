import asyncio
import io
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.core.database import get_db
from app.db.models import KnowledgeDocument, KnowledgeProcessingTask
from app.main import app
from tests.knowledge_helpers import make_knowledge_env


@pytest.fixture
async def knowledge_env(tmp_path):
    env = await make_knowledge_env(tmp_path)
    async def database():
        async with env[1]() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: env[3]
    app.dependency_overrides[get_settings] = lambda: env[2]
    yield env
    await env[0].dispose()


def client():
    return AsyncClient(transport=ASGITransport(app), base_url="http://test")


async def create_base(api):
    response = await api.post("/api/v1/knowledge-bases", json={"name": "企业培训", "description": "员工学习"})
    assert response.status_code == 201
    return response.json()["data"]["knowledge_base_id"]


async def upload(api, base_id, content=b"# Chapter One\nThis is a private learning document.", filename="notes.md", request_id="knowledge-upload-0001"):
    return await api.post(f"/api/v1/knowledge-bases/{base_id}/documents",
                          data={"request_id": request_id}, files={"file": (filename, content, "application/octet-stream")})


async def test_owned_crud_and_capabilities_do_not_expose_configuration(knowledge_env):
    async with client() as api:
        capabilities = (await api.get("/api/v1/knowledge-bases/capabilities")).json()["data"]
        assert capabilities["management_available"] is True and capabilities["index_available"] is False
        assert "api_key" not in str(capabilities) and "directory" not in str(capabilities)
        base_id = await create_base(api)
        listing = (await api.get("/api/v1/knowledge-bases")).json()["data"]
        assert listing["total"] == 1 and listing["items"][0]["knowledge_base_id"] == base_id
        updated = await api.patch(f"/api/v1/knowledge-bases/{base_id}", json={"name": "修订培训"})
        assert updated.json()["data"]["name"] == "修订培训"
        app.dependency_overrides[get_current_user] = lambda: knowledge_env[4]
        assert (await api.get("/api/v1/knowledge-bases")).json()["data"]["total"] == 0
        for method in ("get", "patch", "delete"):
            response = await getattr(api, method)(f"/api/v1/knowledge-bases/{base_id}", **({"json": {"name": "恶意修改"}} if method == "patch" else {}))
            assert response.status_code == 404


async def test_upload_is_private_immediate_and_idempotent(knowledge_env):
    async with client() as api:
        base_id = await create_base(api)
        response = await upload(api, base_id)
        assert response.status_code == 202
        result = response.json()["data"]
        task_id, doc_id = result["task_id"], result["document"]["document_id"]
        assert result["status"] == "queued" and result["poll_after_ms"] == 5000
        assert result["result"] is None
        assert "source_key" not in str(result) and "private learning" not in str(result)
        repeat = (await upload(api, base_id)).json()["data"]
        assert repeat["task_id"] == task_id and repeat["document"]["document_id"] == doc_id
        assert (await upload(api, base_id, content=b"different content")).status_code == 409
        assert (await api.get(f"/api/v1/knowledge-processing-tasks/{task_id}")).json()["data"]["status"] == "queued"
        recovered = await api.get("/api/v1/knowledge-processing-tasks/by-request/knowledge-upload-0001")
        assert recovered.status_code == 200 and recovered.json()["data"]["task_id"] == task_id
        assert (await api.get(f"/api/v1/knowledge-documents/{doc_id}/preview")).status_code == 409
        assert (await api.get(f"/api/v1/knowledge-bases/{base_id}/documents")).json()["data"]["total"] == 1
        app.dependency_overrides[get_current_user] = lambda: knowledge_env[4]
        assert (await api.get(f"/api/v1/knowledge-documents/{doc_id}")).status_code == 404
        assert (await api.get(f"/api/v1/knowledge-processing-tasks/{task_id}")).status_code == 404
        assert (await api.get(f"/api/v1/knowledge-documents/{doc_id}/preview")).status_code == 404
        assert (await api.delete(f"/api/v1/knowledge-documents/{doc_id}")).status_code == 404
        assert (await upload(api, base_id, request_id="knowledge-other-0001")).status_code == 404
    async with knowledge_env[1]() as db:
        assert await db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1
        assert await db.scalar(select(func.count()).select_from(KnowledgeProcessingTask)) == 1
    files = list(knowledge_env[2].private_directory(knowledge_env[2].knowledge_storage_directory).rglob("*.md"))
    assert len(files) == 1 and files[0].read_bytes().startswith(b"# Chapter One")


@pytest.mark.parametrize("filename,content", [
    ("slides.pptx", b"unsupported"), ("empty.txt", b""), ("fake.pdf", b"not a pdf"),
    ("fake.docx", b"not a zip"), ("image.txt", b"\x89PNG\r\n\x1a\n"),
    ("../../escape.txt", b"text"), ("fake.md", b"%PDF-1.7\n"),
])
async def test_bad_upload_rejects_without_document_or_task(knowledge_env, filename, content):
    async with client() as api:
        base_id = await create_base(api)
        response = await upload(api, base_id, filename=filename, content=content)
        assert response.status_code == 400
        assert "Traceback" not in response.text
    async with knowledge_env[1]() as db:
        assert await db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 0
        assert await db.scalar(select(func.count()).select_from(KnowledgeProcessingTask)) == 0


async def test_file_size_boundary_is_enforced_from_actual_bytes(knowledge_env):
    knowledge_env[2].knowledge_max_file_bytes = 100
    async with client() as api:
        base_id = await create_base(api)
        assert (await upload(api, base_id, content=b"a" * 100, filename="boundary.txt")).status_code == 202
        assert (await upload(api, base_id, content=b"a" * 101, filename="large.txt", request_id="knowledge-large-0001")).status_code == 413
    async with knowledge_env[1]() as db:
        assert await db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1


async def test_docx_archive_requires_real_word_content(knowledge_env):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("random.txt", "fake document")
    async with client() as api:
        base_id = await create_base(api)
        assert (await upload(api, base_id, filename="fake.docx", content=archive.getvalue())).status_code == 400


async def test_text_document_saves_without_vector_service_and_respects_quota(knowledge_env):
    knowledge_env[2].knowledge_max_documents = 1
    async with client() as api:
        base_id = await create_base(api)
        payload = {"title": "客服流程", "text": "第一章\n客服先核对客户订单。", "request_id": "knowledge-text-0001"}
        first = await api.post(f"/api/v1/knowledge-bases/{base_id}/text-documents", json=payload)
        assert first.status_code == 202
        assert (await api.post(f"/api/v1/knowledge-bases/{base_id}/text-documents", json=payload)).json()["data"]["task_id"] == first.json()["data"]["task_id"]
        second = await api.post(f"/api/v1/knowledge-bases/{base_id}/text-documents", json={**payload, "request_id": "knowledge-text-0002"})
        assert second.status_code == 400


async def test_disabled_feature_and_unauthenticated_access(knowledge_env):
    knowledge_env[2].enable_knowledge_base = False
    async with client() as api:
        assert (await api.get("/api/v1/knowledge-bases/capabilities")).json()["data"]["enabled"] is False
        assert (await api.post("/api/v1/knowledge-bases", json={"name": "资料"})).status_code == 503
        app.dependency_overrides.pop(get_current_user)
        assert (await api.get("/api/v1/knowledge-bases/capabilities")).status_code == 401


async def test_delete_immediately_blocks_sources_and_keeps_cleanup_task(knowledge_env):
    async with client() as api:
        base_id = await create_base(api)
        result = (await upload(api, base_id)).json()["data"]
        doc_id = result["document"]["document_id"]
        deleted = await api.delete(f"/api/v1/knowledge-documents/{doc_id}")
        assert deleted.status_code == 200
        assert deleted.json()["data"]["cleanup_status"] == "pending"
        assert deleted.json()["data"]["learning_snapshots_retained"] is True
        cleanup_id = deleted.json()["data"]["cleanup_task_id"]
        cleanup = (await api.get('/api/v1/knowledge-processing-tasks/cleanup')).json()['data']
        assert [item['task_id'] for item in cleanup['items']] == [cleanup_id]
        assert cleanup['items'][0]['document']['deleted'] is True
        app.dependency_overrides[get_current_user] = lambda: knowledge_env[4]
        assert (await api.get('/api/v1/knowledge-processing-tasks/cleanup')).json()['data']['total'] == 0
        app.dependency_overrides[get_current_user] = lambda: knowledge_env[3]
        assert (await api.get(f"/api/v1/knowledge-documents/{doc_id}/preview")).status_code == 404
        assert (await api.get(f"/api/v1/knowledge-bases/{base_id}/documents")).json()["data"]["total"] == 0
        assert (await api.get(f"/api/v1/knowledge-processing-tasks/{result['task_id']}")).json()["data"]["status"] == "failed"


async def test_pagination_and_same_topic_are_owner_scoped(knowledge_env):
    async with client() as api:
        own = await create_base(api)
        await create_base(api)
        page = (await api.get("/api/v1/knowledge-bases?page=2&page_size=1")).json()["data"]
        assert page["total"] == 2 and len(page["items"]) == 1
        assert (await api.get("/api/v1/knowledge-bases?page=0")).status_code == 422
        app.dependency_overrides[get_current_user] = lambda: knowledge_env[4]
        other = await create_base(api)
        assert other != own
        listing = (await api.get("/api/v1/knowledge-bases")).json()["data"]
        assert listing["total"] == 1 and listing["items"][0]["knowledge_base_id"] == other


async def test_concurrent_identical_uploads_have_one_persisted_result(knowledge_env):
    async with client() as api:
        base = await create_base(api)
        first, second = await asyncio.gather(upload(api, base), upload(api, base))
        assert first.status_code == second.status_code == 202
        assert first.json()["data"]["task_id"] == second.json()["data"]["task_id"]
    async with knowledge_env[1]() as db:
        assert await db.scalar(select(func.count()).select_from(KnowledgeDocument)) == 1


async def test_archive_limits_and_private_paths_are_not_public(knowledge_env):
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as writer:
        writer.writestr("[Content_Types].xml", "types")
        writer.writestr("word/document.xml", "document")
        for number in range(2000):
            writer.writestr(f"word/{number}.xml", "data")
    async with client() as api:
        base = await create_base(api)
        assert (await upload(api, base, filename="archive.docx", content=archive.getvalue())).status_code == 400
        result = (await upload(api, base)).json()["data"]
        doc = result["document"]["document_id"]
        for path in (f"/data/knowledge/{doc}", f"/static/knowledge/{doc}", f"/api/v1/knowledge-documents/{doc}/download"):
            assert (await api.get(path)).status_code == 404
        knowledge_env[2].knowledge_max_storage_bytes = 50
        assert (await upload(api, base, content=b"a" * 50, request_id="knowledge-quota-0001")).status_code == 400


async def test_wechat_temporary_name_uses_validated_original_filename(knowledge_env):
    async with client() as api:
        base = await create_base(api)
        response = await api.post(f"/api/v1/knowledge-bases/{base}/documents",
            data={"request_id": "wechat-original-name-0001", "filename": "培训说明.txt"},
            files={"file": ("wx-tmp-file.tmp", "第一章\n员工培训".encode(), "application/octet-stream")})
        assert response.status_code == 202
        assert response.json()["data"]["document"]["title"] == "培训说明.txt"
