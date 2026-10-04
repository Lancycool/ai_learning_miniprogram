import asyncio

import pytest

from app.core.config import Settings
from app.core.knowledge_errors import KnowledgeError
from app.models.quiz_task import QuizTaskCreateRequest
from app.models.web_search import SearchSource, WebSearchMetadata
from tests.test_services import build_questions


def request(web=False):
    return QuizTaskCreateRequest(request_id="rag-generation-0001", user_input="客服退款流程",
        knowledge_scope={"knowledge_base_id": "base-one", "documents": [{"document_id": "doc-one", "version_id": "version-one"}]},
        enable_web_search=web, **({"public_search_topic": "公开客服通用规范", "public_search_confirmed": True} if web else {}))


def scope():
    return [{"user_id": 1, "knowledge_base_id": "base-one", "document_id": "doc-one", "version_id": "version-one",
        "generation": "gen-one", "chapter_ids": ["chapter-one"], "ranges": [[0, 100]], "title": "内部培训"}]


class Vectors:
    calls = 0
    empty = False
    async def retrieve(self, query, user_id, base_id, scopes, **kwargs):
        self.calls += 1
        assert user_id == 1 and base_id == "base-one" and scopes == scope()
        return [] if self.empty else [{"source_id": "gen-one_1", "text": "私有制度：退款必须由主管确认。",
            "source_type": "private", "document_id": "doc-one", "version_id": "version-one",
            "chapter_id": "chapter-one", "chapter_title": "退款", "title": "内部培训", "start_offset": 0, "end_offset": 18}]


class Search:
    queries = []
    async def enrich(self, topic, enabled, deadline, task_id):
        self.queries.append(topic)
        return WebSearchMetadata(requested=True, enabled=True, status="success", context_used=True,
            sources=[SearchSource(source_id="web-source", title="公开规范", url="https://example.com/public", content="公开规范")])


class DraftGenerator:
    calls = 0
    fake_quote = False
    fake_id = False
    async def generate(self, user_input, evidence):
        from app.models.knowledge_quiz import GroundedQuizDraft
        self.calls += 1
        return GroundedQuizDraft(title="客服流程", summary="根据培训资料学习客服流程", questions=[
            {**q.model_dump(mode="json"), "citations": [{"source_id": "fake" if self.fake_id else "gen-one_1",
                "quote": "模型编造的句子" if self.fake_quote else "退款必须由主管确认。"}]} for q in build_questions()])


class Checker:
    supported = True
    async def check(self, draft, evidence):
        return self.supported


class Agent:
    def __init__(self, tools, *, broken=False, public=False):
        self.tools, self.broken, self.public = tools, broken, public
    async def ainvoke(self, inputs, config=None):
        if self.broken:
            raise RuntimeError("SECRET PRIVATE_BODY provider failure")
        await self.tools[0].ainvoke({"query": "退款流程"})
        if self.public and len(self.tools) == 2:
            await self.tools[1].ainvoke({"query": "私有制度 退款必须由主管确认"})
        return {"messages": ["Agent 自述内容不能成为资料证据"]}


def service(settings=None, *, agent_broken=False, public=False, vectors=None, draft=None, checker=None):
    from app.services.knowledge_quiz_service import KnowledgeQuizService
    captured = []
    def factory(**kwargs):
        captured.append(kwargs)
        return Agent(kwargs["tools"], broken=agent_broken, public=public)
    search = Search()
    search.queries = []
    return KnowledgeQuizService(settings or Settings(_env_file=None, ENABLE_WEB_SEARCH=True),
        vector_store=vectors or Vectors(), search=search, agent_factory=factory,
        draft_generator=draft or DraftGenerator(), checker=checker or Checker()), captured, search


async def test_private_tools_are_scope_bound_and_web_defaults_off():
    rag, calls, search = service()
    result = await rag.generate(request(), scope(), "task-one")
    assert [tool.name for tool in calls[0]["tools"]] == ["search_private_knowledge"]
    assert search.queries == [] and len(result.quiz.questions) == 5
    assert len(result.snapshots) == 5 and all(s["citations"][0]["quote"] == "退款必须由主管确认。" for s in result.snapshots)
    assert calls[0]["middleware"]


async def test_public_tool_uses_only_confirmed_topic_and_global_switch_wins():
    rag, calls, search = service(public=True)
    await rag.generate(request(True), scope(), "task-one")
    assert len(calls[0]["tools"]) == 2 and search.queries == ["公开客服通用规范"]
    rag, calls, search = service(Settings(_env_file=None, ENABLE_WEB_SEARCH=False), public=True)
    await rag.generate(request(True), scope(), "task-one")
    assert len(calls[0]["tools"]) == 1 and search.queries == []


async def test_agent_failure_has_one_private_fallback_without_logging_secrets(caplog):
    vectors = Vectors()
    rag, _, _ = service(agent_broken=True, vectors=vectors)
    await rag.generate(request(), scope(), "task-one")
    assert vectors.calls == 1
    assert "SECRET" not in caplog.text and "PRIVATE_BODY" not in caplog.text


async def test_agent_factory_failure_still_uses_bounded_owned_retrieval():
    rag, _, _ = service()
    def broken(**kwargs):
        raise RuntimeError('provider startup unavailable')
    rag.agent_factory = broken
    checked = []
    async def validate():
        checked.append(True)
    rag.scope_validator = validate
    result = await rag.generate(request(), scope(), 'factory-failure')
    assert len(result.quiz.questions) == 5 and checked == [True]


async def test_no_material_does_not_generate_from_model_memory():
    vectors, draft = Vectors(), DraftGenerator()
    vectors.empty = True
    rag, _, _ = service(vectors=vectors, draft=draft)
    with pytest.raises(KnowledgeError) as caught:
        await rag.generate(request(), scope(), "task-one")
    assert caught.value.reason == "insufficient_material" and draft.calls == 0


@pytest.mark.parametrize("failure", ["fake_id", "fake_quote", "unsupported_answer"])
async def test_fabricated_citations_and_unsupported_answers_are_rejected(failure):
    draft, checker = DraftGenerator(), Checker()
    if failure == "unsupported_answer":
        checker.supported = False
    else:
        setattr(draft, failure, True)
    rag, _, _ = service(draft=draft, checker=checker)
    with pytest.raises(KnowledgeError):
        await rag.generate(request(), scope(), "task-one")


async def test_total_budget_and_private_tool_budget_are_bounded():
    class Slow(DraftGenerator):
        async def generate(self, *args):
            await asyncio.Event().wait()
    settings = Settings(_env_file=None)
    settings.knowledge_quiz_timeout_seconds = 0.02
    rag, _, _ = service(settings, draft=Slow())
    with pytest.raises(KnowledgeError) as caught:
        await rag.generate(request(), scope(), "task-one")
    assert caught.value.reason == "knowledge_generation_timeout"


async def test_public_search_budget_reserves_generation_outside_planning():
    from time import monotonic
    rag, _, _ = service(public=True)
    budgets = []
    class BudgetSearch(Search):
        async def enrich(self, topic, enabled, deadline, task_id):
            # Existing search reserves 45s for the ordinary model. Passing only
            # the 45s planning deadline would always disable the public tool.
            budgets.append(deadline-monotonic())
            return await super().enrich(topic, enabled, deadline, task_id)
    rag.search = BudgetSearch()
    await rag.generate(request(True), scope(), 'public-budget')
    assert budgets and budgets[0] > rag.settings.request_timeout_seconds+5
