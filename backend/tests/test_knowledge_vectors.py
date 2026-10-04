import pytest
from langchain_core.embeddings import Embeddings

from app.core.config import Settings


class SyntheticEmbedding(Embeddings):
    fingerprint = "synthetic-vector-v1"
    calls = 0
    def embed_query(self, text):
        vector = [0.0] * 1024
        vector[0 if "客服" in text else 1] = 1.0
        return vector
    def embed_documents(self, texts):
        return [self.embed_query(t) for t in texts]
    async def aembed_documents(self, texts):
        self.calls += 1
        return self.embed_documents(texts)


def settings(tmp_path):
    return Settings(_env_file=None, CHROMA_PERSIST_DIRECTORY=str(tmp_path / "vectors"))


def scope(user=1, document="doc-one", version="version-one", generation="gen-one", chapters=None):
    return {"user_id": user, "knowledge_base_id": "kb-one", "document_id": document,
            "version_id": version, "generation": generation, "chapter_ids": chapters,
            "title": "合成培训资料"}


async def test_real_chroma_persists_and_isolates_users_chapters_and_generations(tmp_path):
    from app.services.knowledge_vector_store import KnowledgeVectorStore
    text = "客服先核对订单。\n退款由主管确认。"
    boundary = text.index("退款")
    chapters = [{"chapter_id": "chapter-one", "title": "客服", "level": 1, "start_offset": 0, "end_offset": boundary},
                {"chapter_id": "chapter-two", "title": "退款", "level": 1, "start_offset": boundary, "end_offset": len(text)}]
    store = KnowledgeVectorStore(settings(tmp_path), SyntheticEmbedding())
    assert await store.write(scope(), text, chapters) == 2
    await store.write(scope(user=2), "客服属于用户二的秘密", [{**chapters[0], "end_offset": len("客服属于用户二的秘密")}])
    reopened = KnowledgeVectorStore(settings(tmp_path), SyntheticEmbedding())
    results = await reopened.retrieve("客服", 1, "kb-one", [scope(chapters=["chapter-one"])])
    assert len(results) == 1 and "核对订单" in results[0]["text"]
    assert "用户二" not in str(results) and "退款" not in str(results)
    assert results[0]["distance"] == pytest.approx(0, abs=0.001)
    assert await reopened.retrieve("客服", 1, "kb-one", [scope(generation="obsolete")]) == []
    assert await reopened.retrieve("客服", 1, "kb-one", [scope(chapters=["chapter-two"])]) == []
    await reopened.remove_generation(scope())
    assert await reopened.retrieve("客服", 1, "kb-one", [scope()]) == []
    assert await reopened.retrieve("客服", 2, "kb-one", [scope(user=2)])


async def test_nested_chapters_do_not_duplicate_or_overlap_unselected_content(tmp_path):
    from app.services.knowledge_vector_store import KnowledgeVectorStore
    text = "客服主章介绍。" + "客服子章正文。" * 300 + "退款末章。"
    chapters = [{"chapter_id": "parent", "title": "主章", "level": 1, "start_offset": 0, "end_offset": len(text)-5},
        {"chapter_id": "child", "title": "子章", "level": 2, "start_offset": 7, "end_offset": len(text)-5},
        {"chapter_id": "tail", "title": "末章", "level": 1, "start_offset": len(text)-5, "end_offset": len(text)}]
    store = KnowledgeVectorStore(settings(tmp_path), SyntheticEmbedding())
    await store.write(scope(), text, chapters)
    results = await store.retrieve("客服", 1, "kb-one", [scope(chapters=["child"])], limit=8)
    assert results and all(r["chapter_id"] == "child" for r in results)
    assert all("退款" not in r["text"] and "主章介绍" not in r["text"] for r in results)
    assert len({r["source_id"] for r in results}) == len(results)


async def test_partial_failure_removes_unpublished_generation(tmp_path):
    from app.services.knowledge_vector_store import KnowledgeVectorStore
    class Broken(SyntheticEmbedding):
        async def aembed_documents(self, texts):
            if self.calls:
                raise RuntimeError("synthetic provider failed")
            return await super().aembed_documents(texts)
    store = KnowledgeVectorStore(settings(tmp_path), Broken())
    text = "客服" * 15000
    with pytest.raises(RuntimeError):
        await store.write(scope(), text, [{"chapter_id": "whole", "title": "全文", "level": 1, "start_offset": 0, "end_offset": len(text)}])
    assert await store.retrieve("客服", 1, "kb-one", [scope()]) == []


async def test_metadata_scope_is_rechecked_and_fingerprint_isolated(tmp_path):
    from app.services.knowledge_vector_store import KnowledgeVectorStore
    from app.core.knowledge_errors import KnowledgeError
    store = KnowledgeVectorStore(settings(tmp_path), SyntheticEmbedding())
    with pytest.raises(KnowledgeError):
        await store.retrieve("客服", 1, "kb-one", [scope(user=2)])
    with pytest.raises(KnowledgeError):
        await store.retrieve("客服", 1, "kb-other", [scope()])
    embedding = SyntheticEmbedding()
    embedding.fingerprint = "synthetic-vector-v2"
    second = KnowledgeVectorStore(settings(tmp_path), embedding)
    assert store.collection_name(1, "kb-one") != second.collection_name(1, "kb-one")


async def test_chroma_survives_process_restart_and_cleanup_all_fingerprints(tmp_path):
    import asyncio, json, sys
    from app.services.knowledge_vector_store import KnowledgeVectorStore
    from pathlib import Path
    # First process writes and exits, so no shared in-memory Chroma client can
    # make this test pass without a persisted index.
    script = '''import asyncio,sys
from pathlib import Path
from tests.test_knowledge_vectors import SyntheticEmbedding,settings,scope
from app.services.knowledge_vector_store import KnowledgeVectorStore
async def run():
    store=KnowledgeVectorStore(settings(Path(sys.argv[1])),SyntheticEmbedding())
    text="客服跨进程核对订单。"
    await store.write(scope(),text,[{"chapter_id":"whole","title":"全文","level":1,"start_offset":0,"end_offset":len(text)}])
asyncio.run(run())
'''
    process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8', '-c', script, str(tmp_path),
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, stderr = await asyncio.wait_for(process.communicate(), 45)
    assert process.returncode == 0, stderr.decode('utf-8', errors='replace')
    store = KnowledgeVectorStore(settings(tmp_path), SyntheticEmbedding())
    found = await store.retrieve('客服', 1, 'kb-one', [scope()])
    assert found and '跨进程' in found[0]['text']
    changed = SyntheticEmbedding(); changed.fingerprint = 'changed-embedding'
    second = KnowledgeVectorStore(settings(tmp_path), changed)
    second_text = '客服第二配置的资料。'
    await second.write(scope(), second_text, [{'chapter_id':'whole','title':'全文','level':1,'start_offset':0,'end_offset':len(second_text)}])
    await store.remove_document(1, 'kb-one', 'doc-one')
    assert await store.retrieve('客服', 1, 'kb-one', [scope()]) == []
    assert await second.retrieve('客服', 1, 'kb-one', [scope()]) == []
