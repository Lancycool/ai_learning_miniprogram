from app.core.exceptions import AppError


class KnowledgeError(AppError):
    code = 4200

    def __init__(self, reason: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


def feature_unavailable():
    return KnowledgeError("feature_unavailable", "知识库功能暂未启用", 503)
