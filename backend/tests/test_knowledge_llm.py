import json
from types import SimpleNamespace
import pytest
from app.core.config import Settings
from app.models.knowledge_quiz import EvidenceSupport, GroundedQuizDraft


async def test_private_generators_use_schema_and_literal_sources(monkeypatch):
    import app.llm.knowledge_generators as module
    calls = []
    class Model:
        def with_structured_output(self, schema, method):
            self.schema = schema
            assert method == 'json_mode'
            return self
        async def ainvoke(self, messages):
            calls.append((self.schema, messages))
            return EvidenceSupport(supported=[True]*5, private_rules_consistent=True) if self.schema is EvidenceSupport else 'draft'
    constructed = []
    def construct(**kwargs): constructed.append(kwargs); return Model()
    monkeypatch.setattr(module, 'ChatDeepSeek', construct)
    settings = Settings(_env_file=None, API_KEY='synthetic-private-key')
    evidence = [{'source_id':'real-source','text':'退款需要主管审批。'}]
    assert await module.GroundedDraftGenerator(settings).generate('学习退款', evidence) == 'draft'
    class Draft:
        def model_dump(self, **kwargs): return {'questions': []}
    assert await module.GroundedAnswerChecker(settings).check(Draft(), evidence)
    assert constructed[0]['max_retries'] == 0 and constructed[0]['temperature'] == 0
    assert json.loads(calls[0][1][1][1])['evidence'] == evidence
    assert 'source_id' in calls[0][1][0][1] and '私有制度优先' in calls[0][1][0][1]


async def test_locator_returns_only_valid_original_line_ranges(monkeypatch):
    import app.llm.original_locator as module
    class Model:
        def with_structured_output(self, schema, method): return self
        async def ainvoke(self, messages):
            lines = json.loads(messages[1][1]); assert lines[0]['text'] == '原文标题'
            return module.LocatedRanges(questions=[{'start_line': 1, 'end_line': 3}, {'start_line': 8, 'end_line': 9}])
    monkeypatch.setattr(module, 'private_model', lambda *args: Model())
    text = '原文标题\n[单选题] 原文题目？\nA. 原文选项\n'
    result = await module.OriginalStructureLocator(Settings(_env_file=None))(text)
    assert result == [{'start_offset': len('原文标题\n'), 'end_offset': len(text)}]
    assert set(result[0]) == {'start_offset', 'end_offset'}
