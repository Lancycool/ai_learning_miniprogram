import asyncio
import json
import math

import httpx
import pytest

from app.core.config import Settings
from app.core.knowledge_errors import KnowledgeError


def config():
    return Settings(_env_file=None, BAILIAN_API_KEY="synthetic-only",
                    BAILIAN_API_BASE_URL="https://dashscope.aliyuncs.com/api/v1")


def vector_response(request):
    payload = json.loads(request.content)
    assert request.url.path == "/api/v1/services/embeddings/text-embedding/text-embedding"
    assert payload["model"] == "text-embedding-v4"
    assert payload["parameters"]["dimension"] == 1024
    return httpx.Response(200, json={"output": {"embeddings": [
        {"text_index": i, "embedding": [float(i)] * 1024} for i in reversed(range(len(payload["input"]["texts"])))
    ]}})


async def test_document_batching_query_type_and_reordering():
    from app.services.bailian_embeddings import BailianEmbeddings
    requests = []
    def handle(request):
        requests.append(json.loads(request.content))
        return vector_response(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        embedding = BailianEmbeddings(config(), async_client=client)
        vectors = await embedding.aembed_documents([f"资料{i}" for i in range(23)])
        assert len(vectors) == 23 and vectors[1][0] == 1 and vectors[10][0] == 0
        assert [len(r["input"]["texts"]) for r in requests] == [10, 10, 3]
        assert all(r["parameters"]["text_type"] == "document" for r in requests)
        await embedding.aembed_query("查询")
        assert requests[-1]["parameters"]["text_type"] == "query"


def test_sync_langchain_interface():
    from app.services.bailian_embeddings import BailianEmbeddings
    from langchain_core.embeddings import Embeddings
    with httpx.Client(transport=httpx.MockTransport(vector_response)) as client:
        embedding = BailianEmbeddings(config(), sync_client=client)
        assert isinstance(embedding, Embeddings)
        assert len(embedding.embed_query("问题")) == 1024
        assert len(embedding.embed_documents(["文档", "文档二"])) == 2


@pytest.mark.parametrize("entries", [[], [{"text_index": 0, "embedding": [1] * 3}],
    [{"text_index": 1, "embedding": [0] * 1024}], [{"text_index": 0, "embedding": ["bad"] * 1024}],
    [{"text_index": 0, "embedding": [0] * 1024}] * 2])
async def test_invalid_provider_response_is_rejected(entries):
    from app.services.bailian_embeddings import BailianEmbeddings
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"output": {"embeddings": entries}}))) as client:
        with pytest.raises(KnowledgeError):
            await BailianEmbeddings(config(), async_client=client).aembed_query("私有资料")


@pytest.mark.parametrize("status,expected_calls", [(429, 2), (503, 2), (401, 1), (400, 1)])
async def test_retry_is_bounded_and_logs_no_upstream_body(status, expected_calls, caplog):
    from app.services.bailian_embeddings import BailianEmbeddings
    calls = 0
    def handle(request):
        nonlocal calls
        calls += 1
        return httpx.Response(status, text="PRIVATE_BODY SECRET_KEY")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(KnowledgeError) as caught:
            await BailianEmbeddings(config(), async_client=client).aembed_documents(["资料"])
    assert calls == expected_calls
    assert "PRIVATE_BODY" not in str(caught.value) + caplog.text
    assert "SECRET_KEY" not in str(caught.value) + caplog.text


async def test_network_timeout_and_cancellation():
    from app.services.bailian_embeddings import BailianEmbeddings
    async def handle(request):
        await asyncio.sleep(0.2)
        return vector_response(request)
    settings = config()
    settings.knowledge_query_timeout_seconds = 0.01
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        embedding = BailianEmbeddings(settings, async_client=client)
        with pytest.raises(KnowledgeError):
            await embedding.aembed_query("查询")
        settings.knowledge_query_timeout_seconds = 10
        running = asyncio.create_task(embedding.aembed_query("查询"))
        await asyncio.sleep(0.01)
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running


async def test_bad_configuration_never_calls_network():
    from app.services.bailian_embeddings import BailianEmbeddings
    settings = config()
    settings.bailian_api_base_url = "https://dashscope-intl.aliyuncs.com/api/v1"
    with pytest.raises(KnowledgeError):
        BailianEmbeddings(settings)


def test_non_finite_vectors_are_rejected_before_chroma():
    from app.services.bailian_embeddings import BailianEmbeddings
    for value in (math.inf, math.nan, True):
        with pytest.raises(KnowledgeError):
            BailianEmbeddings.validate({"output": {"embeddings": [{"text_index": 0, "embedding": [value] * 1024}]}}, 1)


@pytest.mark.parametrize('kind', ['retry_success', 'unauthorized', 'transport', 'invalid_json', 'empty_text'])
def test_sync_embeddings_share_bounded_failures_and_do_not_expose_payload(kind):
    from app.services.bailian_embeddings import BailianEmbeddings
    calls = []
    def handle(request):
        calls.append(request)
        if kind == 'transport': raise httpx.ConnectError('PRIVATE_BODY SECRET_KEY')
        if kind == 'invalid_json': return httpx.Response(200, text='PRIVATE_BODY SECRET_KEY')
        if kind == 'unauthorized': return httpx.Response(401, text='PRIVATE_BODY SECRET_KEY')
        if len(calls) == 1: return httpx.Response(429, text='rate limit')
        return vector_response(request)
    with httpx.Client(transport=httpx.MockTransport(handle)) as upstream:
        embedding = BailianEmbeddings(config(), sync_client=upstream)
        if kind == 'retry_success':
            assert len(embedding.embed_query('合成查询')) == 1024 and len(calls) == 2
        else:
            with pytest.raises(KnowledgeError) as caught:
                embedding.embed_query(' ' if kind == 'empty_text' else '合成查询')
            assert 'PRIVATE_BODY' not in str(caught.value) and 'SECRET_KEY' not in str(caught.value)
            assert len(calls) == {'unauthorized': 1, 'transport': 2, 'invalid_json': 1, 'empty_text': 0}[kind]
