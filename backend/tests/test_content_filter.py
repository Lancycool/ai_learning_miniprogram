import pytest

from app.core.exceptions import ContentRejectedError
from app.utils.content_filter import ContentFilter


def test_content_filter_normalizes_whitespace_and_control_characters() -> None:
    service = ContentFilter(blocked_terms=[])
    assert service.clean("  RAG\x00  与\n\n搜索  ") == "RAG 与 搜索"


def test_content_filter_rejects_configured_term() -> None:
    service = ContentFilter(blocked_terms=["禁止内容"])
    with pytest.raises(ContentRejectedError):
        service.clean("这里包含禁止内容")

