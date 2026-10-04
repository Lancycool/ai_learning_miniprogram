"""Bailian Beijing native embedding API, behind the LangChain Embeddings contract."""

import asyncio
from contextlib import nullcontext
from hashlib import sha256
import math
from time import monotonic, sleep

import httpx
from langchain_core.embeddings import Embeddings

from app.core.knowledge_errors import KnowledgeError
from app.core.knowledge_runtime import valid_bailian_configuration


def embedding_failure():
    return KnowledgeError("embedding_unavailable", "向量服务暂时不可用，请稍后重试", 503)


class BailianEmbeddings(Embeddings):
    dimension = 1024

    def __init__(self, settings, *, async_client=None, sync_client=None):
        if not valid_bailian_configuration(settings):
            raise embedding_failure()
        self.settings, self.async_client, self.sync_client = settings, async_client, sync_client
        self.endpoint = settings.bailian_api_base_url.rstrip("/")+"/services/embeddings/text-embedding/text-embedding"
        self.fingerprint = sha256(f"{self.endpoint}|{settings.bailian_api_model}|1024|chapter-1000-150-v1".encode()).hexdigest()

    def payload(self, texts, text_type):
        if not all(isinstance(t, str) and t.strip() for t in texts):
            raise KnowledgeError("empty_embedding_text", "向量处理需要有效文字")
        return {"model": self.settings.bailian_api_model, "input": {"texts": texts},
                "parameters": {"dimension": self.dimension, "output_type": "dense", "text_type": text_type}}

    def headers(self):
        return {"Authorization": "Bearer "+self.settings.bailian_api_key.get_secret_value(), "Content-Type": "application/json"}

    @staticmethod
    def validate(value, count):
        try:
            entries = value["output"]["embeddings"]
            if len(entries) != count:
                raise ValueError()
            ordered = [None] * count
            for entry in entries:
                index, vector = entry["text_index"], entry["embedding"]
                if type(index) is not int or not 0 <= index < count or ordered[index] is not None:
                    raise ValueError()
                if len(vector) != 1024 or not all(type(v) in (float, int) and math.isfinite(v) for v in vector):
                    raise ValueError()
                ordered[index] = vector
            return ordered
        except (KeyError, TypeError, ValueError, OverflowError):
            raise embedding_failure() from None

    async def _async_batch(self, client, texts, text_type):
        timeout = self.settings.knowledge_query_timeout_seconds if text_type == "query" else self.settings.knowledge_embedding_timeout_seconds
        deadline = monotonic()+timeout
        for attempt in range(2):
            remaining = deadline-monotonic()
            if remaining <= 0:
                raise embedding_failure()
            try:
                async with asyncio.timeout(remaining):
                    response = await client.post(self.endpoint, json=self.payload(texts, text_type), headers=self.headers(), timeout=remaining)
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(min(0.1, max(0, deadline-monotonic())))
                    continue
                if response.status_code != 200:
                    raise embedding_failure()
                return self.validate(response.json(), len(texts))
            except (httpx.TimeoutException, httpx.TransportError, TimeoutError):
                if attempt == 0 and monotonic() < deadline:
                    continue
                raise embedding_failure() from None
            except (ValueError, TypeError):
                raise embedding_failure() from None
        raise embedding_failure()

    def _sync_batch(self, client, texts, text_type):
        timeout = self.settings.knowledge_query_timeout_seconds if text_type == "query" else self.settings.knowledge_embedding_timeout_seconds
        deadline = monotonic()+timeout
        for attempt in range(2):
            remaining = deadline-monotonic()
            if remaining <= 0:
                raise embedding_failure()
            try:
                response = client.post(self.endpoint, json=self.payload(texts, text_type), headers=self.headers(), timeout=remaining)
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    sleep(min(0.1, max(0, deadline-monotonic())))
                    continue
                if response.status_code != 200:
                    raise embedding_failure()
                return self.validate(response.json(), len(texts))
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 0 and monotonic() < deadline:
                    continue
                raise embedding_failure() from None
            except (ValueError, TypeError):
                raise embedding_failure() from None
        raise embedding_failure()

    async def aembed_documents(self, texts):
        async def run(client):
            vectors = []
            for start in range(0, len(texts), 10):
                vectors.extend(await self._async_batch(client, texts[start:start+10], "document"))
            return vectors
        if self.async_client is not None:
            return await run(self.async_client)
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            return await run(client)

    async def aembed_query(self, text):
        if self.async_client is not None:
            return (await self._async_batch(self.async_client, [text], "query"))[0]
        async with httpx.AsyncClient(follow_redirects=False, trust_env=False) as client:
            return (await self._async_batch(client, [text], "query"))[0]

    def embed_documents(self, texts):
        with nullcontext(self.sync_client) if self.sync_client else httpx.Client(follow_redirects=False, trust_env=False) as client:
            vectors = []
            for start in range(0, len(texts), 10):
                vectors.extend(self._sync_batch(client, texts[start:start+10], "document"))
            return vectors

    def embed_query(self, text):
        with nullcontext(self.sync_client) if self.sync_client else httpx.Client(follow_redirects=False, trust_env=False) as client:
            return self._sync_batch(client, [text], "query")[0]
