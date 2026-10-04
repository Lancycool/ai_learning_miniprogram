"""Run the document libraries outside the API process, with a killable deadline."""

import asyncio
import json
from pathlib import Path
import sys

from app.core.knowledge_errors import KnowledgeError


class KnowledgeParser:
    def __init__(self, settings):
        self.settings = settings
        self.active_processes = set()

    async def parse(self, path: Path, extension: str):
        limits = json.dumps({"pages": self.settings.knowledge_max_pages,
                             "characters": self.settings.knowledge_max_characters})
        process = await asyncio.create_subprocess_exec(sys.executable, "-X", "utf8", "-m",
            "app.services.knowledge_parser_child", str(path.resolve()), extension, limits,
            cwd=str(Path(__file__).resolve().parents[2]), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        self.active_processes.add(process)
        try:
            try:
                async with asyncio.timeout(self.settings.knowledge_parse_timeout_seconds):
                    output, _ = await process.communicate()
            except TimeoutError:
                raise KnowledgeError("parse_timeout", "资料解析超时，请拆分文档后重试") from None
            if process.returncode or len(output) > self.settings.knowledge_max_characters * 12 + 100000:
                raise KnowledgeError("parse_failed", "资料解析失败，请检查文件后重试")
            try:
                value = json.loads(output)
            except (ValueError, UnicodeDecodeError):
                raise KnowledgeError("parse_failed", "资料解析失败，请检查文件后重试") from None
            if "error" in value:
                raise KnowledgeError(value["error"]["code"], value["error"]["message"])
            return value
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
            self.active_processes.discard(process)
