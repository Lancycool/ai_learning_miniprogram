"""Opt-in synthetic acceptance. Never prints credentials or provider bodies."""
import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_settings
from app.core.knowledge_errors import KnowledgeError
from app.models.quiz_task import QuizTaskCreateRequest
from app.services.bailian_embeddings import BailianEmbeddings
from app.services.knowledge_vector_store import KnowledgeVectorStore
from app.services.knowledge_quiz_service import KnowledgeQuizService
from app.services.web_search_service import WebSearchService

TEXT = '''第一章 合成客服练习制度
这是一份公开的虚构测试资料，不代表真实公司制度。
客服接待的第一步是核对测试订单编号。客服不能跳过身份核验。
普通退款需要先确认订单状态，再交给测试主管审批。客服不能自行批准退款。
退款审批通过后，客服需要保留审批记录。客服不能删除处理记录。
测试主管只审批退款。测试客服负责核对订单、记录问题和跟进处理结果。
客服遇到资料未说明的情况时，需要请测试主管确认，不能自行编造流程。
接口返回 HTTP 429 时，系统需要等待后再重试。系统最多重试一次。
接口返回 HTTP 401 时，系统需要提示认证失败，不能无限重试。
第二章 合成学习规则
每组练习最多包含五道题。最后一组可以只有一道题或两道题。
学习者需要选择全部正确的多选选项。少选或多选都不能得分。
学习者完成整组练习后，系统才展示资料来源摘录。
这份资料中的题目和答案必须与这里写明的制度一致。'''

class SearchAudit:
    def __init__(self, settings): self.actual, self.queries = WebSearchService(settings), []
    async def enrich(self, topic, *args):
        self.queries.append(topic)
        return await self.actual.enrich(topic, *args)

async def main():
    logging.getLogger('httpx').setLevel(logging.WARNING)
    settings = get_settings().model_copy(update={'enable_knowledge_base': True})
    results = {}
    with tempfile.TemporaryDirectory(prefix='kb-live-', dir=Path(__file__).resolve().parents[1]/'data') as root:
        settings.chroma_persist_directory = str(Path(root)/'chroma')
        embeddings = BailianEmbeddings(settings)
        vectors = await embeddings.aembed_documents(['合成客服先核对订单。','合成退款需要主管审批。'])
        results['native_embedding_dimension'] = len(vectors[0])
        store = KnowledgeVectorStore(settings, embeddings)
        scope = {'user_id': 1, 'knowledge_base_id': 'synthetic-live-base', 'document_id': 'synthetic-live-doc',
            'version_id': 'synthetic-live-version', 'generation': 'synthetic-live-generation', 'chapter_ids': None,
            'title': '公开合成验收资料', 'ranges': [[0, len(TEXT)]], 'embedding_fingerprint': embeddings.fingerprint}
        chapters = [{'chapter_id': 'synthetic-live-chapter', 'title': '合成客服与学习规则', 'level': 1,
            'start_offset': 0, 'end_offset': len(TEXT)}]
        await store.write(scope, TEXT, chapters)
        related = await store.retrieve('客服核对订单和退款审批流程', 1, scope['knowledge_base_id'], [scope])
        unrelated = await store.retrieve('星系演化中的暗物质引力透镜', 1, scope['knowledge_base_id'], [scope])
        results.update(related_hit_count=len(related), unrelated_hit_count=len(unrelated),
            related_distances=[round(r['distance'], 4) for r in related])
        audit = SearchAudit(settings)
        request = QuizTaskCreateRequest(request_id='synthetic-live-private-0001', user_input='学习合成客服的订单核对、退款审批和资料规则',
            knowledge_scope={'knowledge_base_id': scope['knowledge_base_id'], 'documents': [
                {'document_id': scope['document_id'], 'version_id': scope['version_id']}]})
        generated = await KnowledgeQuizService(settings, vector_store=store, search=audit).generate(request, [scope], 'synthetic-live-private')
        results.update(private_question_count=len(generated.quiz.questions), private_default_search_calls=len(audit.queries),
            private_citation_count=sum(len(s['citations']) for s in generated.snapshots))
        empty_scope = {**scope, 'generation': 'nonexistent-generation'}
        try: await KnowledgeQuizService(settings, vector_store=store, search=audit).generate(request, [empty_scope], 'synthetic-live-empty')
        except KnowledgeError as exc: results['insufficient_material_code'] = exc.reason
        if settings.enable_web_search:
            public_topic = 'HTTP 429 Too Many Requests 官方规范'
            public_request = request.model_copy(update={'request_id': 'synthetic-live-public-0001',
                'user_input': '学习资料中的合成客服与 HTTP 429 重试规则。请先检索私有知识库，并调用公开搜索工具核对已确认的公开 HTTP 429 规范，然后出题。',
                'enable_web_search': True, 'public_search_topic': public_topic, 'public_search_confirmed': True})
            public_generated = await KnowledgeQuizService(settings, vector_store=store, search=audit).generate(public_request, [scope], 'synthetic-live-public-agent')
            results.update(public_agent_question_count=len(public_generated.quiz.questions),
                public_agent_search_calls=len(audit.queries),
                tavily_queries_only_public=bool(audit.queries) and all(q == public_topic for q in audit.queries))
            assert results['public_agent_search_calls'] > 0 and results['tavily_queries_only_public']
        assert results['native_embedding_dimension'] == 1024 and results['private_question_count'] == 5
        assert results['private_default_search_calls'] == 0 and results['insufficient_material_code'] == 'insufficient_material'
        print(json.dumps(results, ensure_ascii=False))
        for index in store.stores.values():
            index._client._system.stop()
    return results

if __name__ == '__main__':
    try: asyncio.run(main())
    except Exception as exc:
        print(json.dumps({'failed': type(exc).__name__, 'code': exc.reason if isinstance(exc, KnowledgeError) else 'provider_or_acceptance_error'}))
        sys.exit(1)
