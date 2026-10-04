from pydantic import Field, model_validator

from app.models.quiz import QuizGenerateRequest
from app.models.knowledge import KnowledgeScope


class QuizTaskCreateRequest(QuizGenerateRequest):
    request_id: str = Field(min_length=16, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    knowledge_scope: KnowledgeScope | None = None
    public_search_topic: str | None = Field(default=None, min_length=2, max_length=300)
    public_search_confirmed: bool = False

    @model_validator(mode="after")
    def private_permissions(self):
        if self.knowledge_scope is not None:
            if self.enable_web_search is None:
                self.enable_web_search = False
            if self.question_count != 5:
                raise ValueError("知识库新题每次生成五题")
            if self.enable_web_search and not (self.public_search_topic and self.public_search_confirmed):
                raise ValueError("请单独填写并确认可公开的搜索主题")
            ids = [d.document_id for d in self.knowledge_scope.documents]
            if len(ids) != len(set(ids)):
                raise ValueError("同一资料不能重复选择")
        elif self.public_search_topic is not None or self.public_search_confirmed:
            raise ValueError("公开补充主题仅用于知识库出题")
        return self
