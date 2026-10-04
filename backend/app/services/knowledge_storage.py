"""Private local files. Client filenames never determine filesystem paths."""

import asyncio
from hashlib import sha256
import json
from pathlib import Path
import zipfile

from app.core.knowledge_errors import KnowledgeError
from app.core.knowledge_runtime import SUPPORTED_EXTENSIONS
from app.services.auth_service import public_id


class KnowledgeStorage:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.private_directory(settings.knowledge_storage_directory)

    def path(self, key: str) -> Path:
        if not key or Path(key).is_absolute() or "\\" in key or ".." in key.split("/"):
            raise KnowledgeError("invalid_storage_key", "资料存储标识不正确")
        result = (self.root / key).resolve()
        if not result.is_relative_to(self.root) or result == self.root:
            raise KnowledgeError("invalid_storage_key", "资料存储标识不正确")
        return result

    async def write(self, key: str, content: bytes):
        path = self.path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, content)

    async def remove(self, key: str):
        await asyncio.to_thread(self.path(key).unlink, missing_ok=True)

    async def read_parsed(self, key: str) -> dict:
        text = await asyncio.to_thread(self.path(key).read_text, encoding="utf-8")
        return json.loads(text)

    async def write_parsed(self, key: str, value: dict):
        await self.write(key, json.dumps(value, ensure_ascii=False).encode("utf-8"))

    async def receive(self, upload, owner_id: str) -> tuple[str, str, str, int, str]:
        filename = upload.filename or ""
        if "/" in filename or "\\" in filename or len(filename) > 120:
            raise KnowledgeError("invalid_filename", "请使用不超过 120 字的文件名")
        extension = Path(filename).suffix.lower().lstrip(".")
        if extension not in SUPPORTED_EXTENSIONS:
            raise KnowledgeError("unsupported_format", "系统只支持 PDF、DOCX、Markdown 和 TXT")
        key = f"{owner_id}/uploads/{public_id('upload')}.tmp"
        path = self.path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        digest, size = sha256(), 0
        handle = await asyncio.to_thread(path.open, "wb")
        try:
            while chunk := await upload.read(65536):
                size += len(chunk)
                if size > self.settings.knowledge_max_file_bytes:
                    raise KnowledgeError("file_too_large", "文件超过系统允许的大小，请拆分后上传", 413)
                digest.update(chunk)
                await asyncio.to_thread(handle.write, chunk)
            await asyncio.to_thread(handle.close)
            if size == 0:
                raise KnowledgeError("empty_file", "文件没有内容，请重新选择")
            await asyncio.to_thread(self.validate_file, path, extension)
            return key, filename, extension, size, digest.hexdigest()
        except BaseException:
            await asyncio.to_thread(handle.close)
            await self.remove(key)
            raise

    def validate_file(self, path: Path, extension: str):
        with path.open("rb") as source:
            header = source.read(4096)
        if extension == "pdf":
            if not header.startswith(b"%PDF-"):
                raise KnowledgeError("invalid_file", "文件内容不是有效 PDF")
        elif extension == "docx":
            try:
                with zipfile.ZipFile(path) as archive:
                    members = archive.infolist()
                    names = {item.filename for item in members}
                    if not {"[Content_Types].xml", "word/document.xml"}.issubset(names):
                        raise KnowledgeError("invalid_file", "文件内容不是有效 DOCX")
                    if len(members) > 2000 or sum(item.file_size for item in members) > 100 * 1024 * 1024:
                        raise KnowledgeError("archive_too_large", "文档解压后的内容超过处理限制")
                    if any(item.flag_bits & 1 or item.filename.startswith(("/", "\\"))
                           or ".." in item.filename.replace("\\", "/").split("/") for item in members):
                        raise KnowledgeError("invalid_archive", "文档包含加密或不正确的文件路径")
                    if any(name.lower().endswith("vbaproject.bin") for name in names):
                        raise KnowledgeError("unsupported_format", "系统暂不支持含宏的文档")
            except (zipfile.BadZipFile, OSError):
                raise KnowledgeError("invalid_file", "文件内容不是有效 DOCX") from None
        elif header.startswith((b"%PDF-", b"PK\x03\x04", b"\x89PNG", b"\xff\xd8", b"\xd0\xcf")) or b"\x00" in header:
            raise KnowledgeError("invalid_file", "文件内容不是可读取的文字资料")
