import importlib

import pytest

from app.core.config import Settings
from app.core.knowledge_runtime import knowledge_capabilities, start_knowledge_worker


def settings(**values):
    return Settings(_env_file=None, **values)


def test_private_feature_is_independent_and_disabled_by_default():
    config = settings(ENABLE_WEB_SEARCH=True)
    assert config.enable_knowledge_base is False
    result = knowledge_capabilities(config, dependency_check=lambda: True)
    assert result["enabled"] is False
    assert result["management_available"] is False
    assert result["max_file_bytes"] == 30 * 1024 * 1024
    assert result["poll_after_ms"] == 5000
    assert result["supported_extensions"] == ["pdf", "docx", "md", "markdown", "txt"]


def test_existing_bailian_names_are_read_and_secret_is_redacted():
    config = settings(ENABLE_KNOWLEDGE_BASE=True, BAILIAN_API_KEY="private-test-key",
                      BAILIAN_API_MODEL="text-embedding-v4",
                      BAILIAN_API_BASE_URL="https://dashscope.aliyuncs.com/api/v1/")
    result = knowledge_capabilities(config, dependency_check=lambda: True)
    assert config.bailian_api_key.get_secret_value() == "private-test-key"
    assert "private-test-key" not in repr(config.bailian_api_key)
    assert result["index_available"] is True
    assert "private-test-key" not in str(result)
    assert "dashscope" not in str(result)


def test_beijing_workspace_native_endpoint_is_supported_without_region_rewrite():
    config = settings(ENABLE_KNOWLEDGE_BASE=True, BAILIAN_API_KEY="synthetic",
        BAILIAN_API_BASE_URL="https://workspace-demo.cn-beijing.maas.aliyuncs.com/api/v1")
    assert knowledge_capabilities(config, dependency_check=lambda: True)["index_available"] is True


@pytest.mark.parametrize("base", ["http://dashscope.aliyuncs.com/api/v1", "https://example.com/api/v1",
                                   "https://dashscope.aliyuncs.com/compatible-mode/v1",
                                   "https://dashscope.aliyuncs.com/api/v1?secret=x",
                                   "https://evil@dashscope.aliyuncs.com/api/v1"])
def test_bad_embedding_configuration_disables_index_without_breaking_management(base):
    config = settings(ENABLE_KNOWLEDGE_BASE=True, BAILIAN_API_KEY="test", BAILIAN_API_BASE_URL=base)
    result = knowledge_capabilities(config, dependency_check=lambda: True)
    assert result["management_available"] is True
    assert result["original_practice_available"] is True
    assert result["index_available"] is False


def test_missing_key_and_missing_dependencies_do_not_claim_success():
    config = settings(ENABLE_KNOWLEDGE_BASE=True)
    result = knowledge_capabilities(config, dependency_check=lambda: True)
    assert result["parsing_available"] is True
    assert result["index_available"] is False
    result = knowledge_capabilities(config, dependency_check=lambda: False)
    assert result["management_available"] is True
    assert result["parsing_available"] is False
    assert result["original_practice_available"] is True


async def test_disabled_feature_never_constructs_or_imports_new_worker():
    def forbidden(*args):
        pytest.fail("Disabled knowledge feature constructed its worker")
    assert start_knowledge_worker(None, settings(), worker_factory=forbidden) is None


async def test_new_dependency_failure_does_not_stop_core_lifespan(monkeypatch, caplog):
    main = importlib.import_module("app.main")
    calls = []
    class CoreWorker:
        def __init__(self, *args):
            pass
        def start(self):
            calls.append("start")
        async def close(self):
            calls.append("close")
    def broken(*args):
        raise ImportError("private-test-key and private document content")
    config = settings(ENABLE_KNOWLEDGE_BASE=True)
    assert start_knowledge_worker(None, config, worker_factory=broken) is None
    assert "private-test-key" not in caplog.text
    monkeypatch.setattr(main, "QuizTaskWorker", CoreWorker)
    monkeypatch.setattr(main, "get_settings", lambda: config)
    monkeypatch.setattr(main, "start_knowledge_worker", lambda *args: None)
    async with main.lifespan(main.app):
        assert calls == ["start"]
    assert calls == ["start", "close"]


async def test_available_worker_starts_and_closes_with_core_lifespan(monkeypatch):
    main = importlib.import_module("app.main")
    calls = []
    class Worker:
        def __init__(self, *args):
            pass
        def start(self):
            calls.append("start")
        async def close(self):
            calls.append("close")
    config = settings(ENABLE_KNOWLEDGE_BASE=True)
    instance = start_knowledge_worker(None, config, worker_factory=Worker)
    assert instance is not None and calls == ["start"]
    monkeypatch.setattr(main, "QuizTaskWorker", Worker)
    monkeypatch.setattr(main, "start_knowledge_worker", lambda *args: instance)
    async with main.lifespan(main.app):
        assert calls == ["start", "start"]
    assert calls == ["start", "start", "close", "close"]


async def test_private_worker_close_failure_still_closes_core(monkeypatch, caplog):
    main = importlib.import_module('app.main')
    closed = []
    class Core:
        def __init__(self, *args): pass
        def start(self): pass
        async def close(self): closed.append(True)
    class Broken:
        async def close(self): raise RuntimeError('SECRET document body')
    monkeypatch.setattr(main, 'QuizTaskWorker', Core)
    monkeypatch.setattr(main, 'start_knowledge_worker', lambda *args: Broken())
    async with main.lifespan(main.app): pass
    assert closed == [True] and 'SECRET' not in caplog.text
