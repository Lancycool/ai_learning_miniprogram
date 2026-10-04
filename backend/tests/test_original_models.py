import pytest
from pydantic import ValidationError

from app.models.knowledge import OriginalQuestion, OriginalDraftItem, DocumentSelection
from app.models.quiz import Question


def original(**extra):
    return {"id": "original-test", "type": "multiple", "stem": "完整原题" * 150,
            "options": [{"key": k, "text": "原选项" * 100, "source_label": k} for k in "ABCDE"],
            "answer": ["A", "E"], "explanation": None, "chapter_id": "chapter-test", **extra}


def test_original_long_content_and_all_options_survive_validation():
    value = original()
    item = OriginalQuestion.model_validate(value)
    assert item.stem == value["stem"] and len(item.options) == 5
    assert item.options[-1].source_label == "E" and item.explanation is None
    with pytest.raises(ValidationError):
        Question.model_validate({**value, "knowledge_point": "培训", "difficulty": "easy"})


def test_original_draft_keeps_missing_answers_but_cannot_publish():
    draft = OriginalDraftItem.model_validate(original(answer=[]))
    assert draft.answer == []
    with pytest.raises(ValidationError):
        OriginalQuestion.model_validate(draft.model_dump())


@pytest.mark.parametrize("extra", [
    {"answer": ["Z"]}, {"answer": ["A", "A"]},
    {"type": "single", "answer": ["A", "B"]},
    {"type": "judge", "answer": ["A"]},
    {"stem": "x" * 32001}, {"options": [{"key": "A", "text": "x" * 8001}, {"key": "B", "text": "B"}]},
])
def test_original_invalid_content_is_rejected_instead_of_truncated(extra):
    with pytest.raises(ValidationError):
        OriginalQuestion.model_validate(original(**extra))


def test_original_answer_single_value_and_exact_text_are_preserved():
    value = original(answer=["E"], stem="  原题正文\n下一行  ")
    assert OriginalQuestion.model_validate(value).stem == value["stem"]


def test_empty_chapter_selection_is_not_implicitly_full_document():
    assert DocumentSelection(document_id="doc-test", version_id="ver-test").chapter_ids is None
    with pytest.raises(ValidationError):
        DocumentSelection(document_id="doc-test", version_id="ver-test", chapter_ids=[])
