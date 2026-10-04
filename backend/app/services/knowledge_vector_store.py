"""Local Chroma indexes. Every query carries a server-validated private scope."""

import asyncio
from hashlib import sha256
import math

from app.core.knowledge_errors import KnowledgeError


async def local_operation(function, *args, **kwargs):
    # Let a local write finish before cleanup after cancellation. A thread cannot
    # be killed and must not write a chunk after its generation was discarded.
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


class KnowledgeVectorStore:
    max_distance = 0.65

    def __init__(self, settings, embedding):
        self.settings, self.embedding = settings, embedding
        self.root = settings.private_directory(settings.chroma_persist_directory)
        self.fingerprint = embedding.fingerprint
        self.stores = {}

    def collection_name(self, user_id, base_id):
        owner = sha256(f"{user_id}|{base_id}".encode()).hexdigest()[:24]
        model = sha256(self.fingerprint.encode()).hexdigest()[:24]
        return f"kb_{owner}_{model}"

    async def store(self, user_id, base_id):
        name = self.collection_name(user_id, base_id)
        if name not in self.stores:
            from langchain_chroma import Chroma
            from chromadb.config import Settings
            self.stores[name] = await local_operation(Chroma, collection_name=name,
                embedding_function=self.embedding, persist_directory=str(self.root),
                client_settings=Settings(anonymized_telemetry=False),
                collection_configuration={"hnsw": {"space": "cosine"}})
        return self.stores[name]

    def chunks(self, scope, text, chapters):
        from langchain_core.documents import Document
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        if not chapters or any(not 0 <= c["start_offset"] < c["end_offset"] <= len(text) for c in chapters):
            raise KnowledgeError("invalid_chapters", "章节范围不正确，请重新确认")
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150,
            add_start_index=True, strip_whitespace=False, separators=["\n\n", "\n", "。", "！", "？", "；", " ", ""])
        boundaries = sorted({0, len(text)} | {c[k] for c in chapters for k in ("start_offset", "end_offset")})
        documents = []
        for start, end in zip(boundaries, boundaries[1:]):
            covering = [c for c in chapters if c["start_offset"] <= start and c["end_offset"] >= end]
            if not covering:
                raise KnowledgeError("invalid_chapters", "章节没有覆盖完整正文，请补充未分章内容")
            chapter = max(covering, key=lambda c: (c["level"], c["start_offset"]))
            metadata = {"user_id": scope["user_id"], "knowledge_base_id": scope["knowledge_base_id"],
                "document_id": scope["document_id"], "version_id": scope["version_id"], "generation": scope["generation"],
                "chapter_id": chapter["chapter_id"], "chapter_title": chapter["title"], "title": scope["title"],
                "fingerprint": self.fingerprint}
            for part in splitter.split_documents([Document(page_content=text[start:end], metadata=metadata)]):
                if not part.page_content.strip():
                    continue
                part.metadata["start_offset"] = start+part.metadata.pop("start_index")
                part.metadata["end_offset"] = part.metadata["start_offset"]+len(part.page_content)
                part.metadata["source_id"] = f"{scope['generation']}_{len(documents)}"
                documents.append(part)
        if len(documents) > self.settings.knowledge_max_chunks:
            raise KnowledgeError("chunk_limit", "资料片段超过索引上限，请拆分文档")
        return documents

    async def write(self, scope, text, chapters, progress=None):
        chunks = self.chunks(scope, text, chapters)
        store = await self.store(scope["user_id"], scope["knowledge_base_id"])
        try:
            for start in range(0, len(chunks), 10):
                batch = chunks[start:start+10]
                if progress:
                    await progress("indexing", start, len(chunks))
                vectors = await self.embedding.aembed_documents([c.page_content for c in batch])
                await local_operation(store._collection.upsert, ids=[c.metadata["source_id"] for c in batch],
                    documents=[c.page_content for c in batch], metadatas=[c.metadata for c in batch], embeddings=vectors)
            if progress:
                await progress("indexing", len(chunks), len(chunks))
            return len(chunks)
        except BaseException:
            await self.remove_generation(scope)
            raise

    async def remove_generation(self, scope):
        store = await self.store(scope["user_id"], scope["knowledge_base_id"])
        await local_operation(store._collection.delete, where={"$and": [
            {"user_id": scope["user_id"]}, {"document_id": scope["document_id"]}, {"generation": scope["generation"]}]})

    async def remove_document(self, user_id, base_id, document_id):
        # Previous fingerprints live in collections with the same owner prefix.
        import chromadb
        from chromadb.config import Settings
        client = await local_operation(chromadb.PersistentClient, path=str(self.root), settings=Settings(anonymized_telemetry=False))
        owner_prefix = self.collection_name(user_id, base_id).rsplit("_", 1)[0]+"_"
        for info in await local_operation(client.list_collections):
            if info.name.startswith(owner_prefix):
                collection = await local_operation(client.get_collection, info.name)
                await local_operation(collection.delete, where={"$and": [{"user_id": user_id}, {"document_id": document_id}]})

    async def retrieve(self, query, user_id, base_id, scopes, *, limit=8):
        if any(s["user_id"] != user_id or s["knowledge_base_id"] != base_id for s in scopes):
            raise KnowledgeError("invalid_scope", "资料检索范围不正确", 404)
        store = await self.store(user_id, base_id)
        if not scopes or not await local_operation(store._collection.count):
            return []
        vector = await self.embedding.aembed_query(query)
        results, seen = [], set()
        for scope in scopes:
            clauses = [{"user_id": user_id}, {"knowledge_base_id": base_id}, {"document_id": scope["document_id"]},
                       {"version_id": scope["version_id"]}, {"generation": scope["generation"]}, {"fingerprint": self.fingerprint}]
            if scope.get("chapter_ids") is not None:
                if not scope["chapter_ids"]:
                    continue
                clauses.append({"chapter_id": {"$in": scope["chapter_ids"]}})
            matches = await local_operation(store.similarity_search_by_vector_with_relevance_scores,
                vector, k=limit, filter={"$and": clauses})
            for document, distance in matches:
                meta = document.metadata
                if (not math.isfinite(distance) or distance > self.max_distance
                    or any(meta.get(key) != scope[key] for key in ("user_id", "knowledge_base_id", "document_id", "version_id", "generation"))
                    or meta.get("fingerprint") != self.fingerprint
                    or (scope.get("chapter_ids") is not None and meta.get("chapter_id") not in scope["chapter_ids"])):
                    continue
                identity = (meta["document_id"], meta["version_id"], document.page_content)
                if identity in seen:
                    continue
                seen.add(identity)
                results.append({**meta, "text": document.page_content, "distance": float(distance), "source_type": "private"})
        return sorted(results, key=lambda r: r["distance"])[:limit]
