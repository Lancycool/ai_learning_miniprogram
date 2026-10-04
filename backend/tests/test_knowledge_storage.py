import io
import zipfile

import pytest
from starlette.datastructures import UploadFile

from app.core.config import Settings
from app.core.knowledge_errors import KnowledgeError
from app.services.knowledge_storage import KnowledgeStorage


async def test_actual_thirty_mib_boundary_and_partial_cleanup(tmp_path):
    storage = KnowledgeStorage(Settings(_env_file=None, KNOWLEDGE_STORAGE_DIRECTORY=str(tmp_path)))
    size = 30 * 1024 * 1024
    accepted = UploadFile(io.BytesIO(b"a" * size), filename="boundary.txt")
    key, _, _, received, _ = await storage.receive(accepted, "synthetic-user")
    assert received == size and storage.path(key).stat().st_size == size
    await storage.remove(key)
    rejected = UploadFile(io.BytesIO(b"a" * (size+1)), filename="oversized.txt")
    with pytest.raises(KnowledgeError) as caught:
        await storage.receive(rejected, "synthetic-user")
    assert caught.value.status_code == 413
    assert not list(tmp_path.rglob("*.tmp"))


async def test_zip_expansion_path_and_macro_limits(tmp_path):
    storage = KnowledgeStorage(Settings(_env_file=None, KNOWLEDGE_STORAGE_DIRECTORY=str(tmp_path)))
    for name, text in (("word/large.xml", b"a" * (100*1024*1024)), ("../outside.xml", b"bad"), ("word/vbaProject.bin", b"bad")):
        source = io.BytesIO()
        with zipfile.ZipFile(source, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "types")
            archive.writestr("word/document.xml", "word")
            archive.writestr(name, text)
        source.seek(0)
        with pytest.raises(KnowledgeError):
            await storage.receive(UploadFile(source, filename="restricted.docx"), "synthetic-user")
    for key in ("../outside.txt", "C:/outside.txt", "folder/../../outside.txt", "folder\\bad.txt"):
        with pytest.raises(KnowledgeError):
            storage.path(key)


async def test_stream_failure_removes_partial_private_file(tmp_path):
    storage = KnowledgeStorage(Settings(_env_file=None, KNOWLEDGE_STORAGE_DIRECTORY=str(tmp_path)))
    class Broken:
        filename = "notes.txt"
        calls = 0
        async def read(self, size):
            self.calls += 1
            if self.calls == 1:
                return b"partial private text"
            raise OSError("synthetic read failure")
    with pytest.raises(OSError):
        await storage.receive(Broken(), "synthetic-user")
    assert not list(tmp_path.rglob("*.tmp"))
