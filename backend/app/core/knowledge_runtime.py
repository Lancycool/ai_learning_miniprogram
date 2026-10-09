"""Optional services must not prevent the existing application from starting."""

from importlib.util import find_spec
import logging
import re
from urllib.parse import urlsplit

from app.core.config import Settings

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = ["pdf", "docx", "md", "markdown", "txt"]


def valid_bailian_configuration(settings: Settings) -> bool:
    try:
        url = urlsplit(settings.bailian_api_base_url)
        return bool(
            settings.bailian_api_key.get_secret_value().strip()
            and settings.bailian_api_model == "text-embedding-v4"
            and url.scheme == "https"
            and (url.hostname == "dashscope.aliyuncs.com" or bool(re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,62}\.cn-beijing\.maas\.aliyuncs\.com", url.hostname or "")))
            and url.port in (None, 443)
            and url.path.rstrip("/") == "/api/v1"
            and not (url.username or url.password or url.query or url.fragment)
        )
    except ValueError:
        return False


def dependencies_available() -> bool:
    return all(find_spec(name) is not None for name in (
        "langchain_community", "langchain_chroma", "langchain_text_splitters",
        "pypdf", "docx2txt", "unstructured", "docx",
    ))


def knowledge_capabilities(settings: Settings, *, dependency_check=None) -> dict:
    enabled = settings.enable_knowledge_base
    try:
        dependencies = enabled and (dependency_check or dependencies_available)()
    except (ImportError, ValueError):
        dependencies = False
    return {
        "enabled": enabled,
        "management_available": enabled,
        "parsing_available": bool(dependencies),
        "index_available": bool(dependencies and valid_bailian_configuration(settings)),
        "original_practice_available": enabled,
        "supported_extensions": SUPPORTED_EXTENSIONS,
        "max_file_bytes": settings.knowledge_max_file_bytes,
        "max_bases": settings.knowledge_max_bases,
        "max_documents": settings.knowledge_max_documents,
        "max_storage_bytes": settings.knowledge_max_storage_bytes,
        "max_characters": settings.knowledge_max_characters,
        "max_import_questions": settings.knowledge_max_import_questions,
        "max_original_options": 26,
        "max_original_stem_characters": 32000,
        "max_original_explanation_characters": 32000,
        "max_original_option_characters": 8000,
        "poll_after_ms": 5000,
        "trace_enabled": bool(settings.knowledge_trace_admin_key.get_secret_value().strip()),
    }


def start_knowledge_worker(sessions, settings: Settings, *, worker_factory=None):
    if not settings.enable_knowledge_base:
        return None
    try:
        if worker_factory is None:
            from app.services.knowledge_task_service import KnowledgeTaskWorker
            worker_factory = KnowledgeTaskWorker
        worker = worker_factory(sessions, settings)
        worker.start()
        return worker
    except Exception as exc:
        # Provider messages and file content are deliberately excluded.
        logger.warning("knowledge_worker_unavailable error_type=%s", type(exc).__name__)
        return None
