import re

from app.core.exceptions import ContentRejectedError


class ContentFilter:
    def __init__(self, blocked_terms: list[str]) -> None:
        self.blocked_terms = [term.casefold() for term in blocked_terms if term.strip()]

    def clean(self, value: str) -> str:
        without_controls = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
        normalized = re.sub(r"\s+", " ", without_controls).strip()
        folded = normalized.casefold()
        if any(term in folded for term in self.blocked_terms):
            raise ContentRejectedError()
        return normalized

