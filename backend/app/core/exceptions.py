class AppError(Exception):
    code = 5000
    status_code = 500
    public_message = "系统暂时无法完成请求"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.public_message)
        self.public_message = message or self.public_message


class ContentRejectedError(AppError):
    code = 4002
    status_code = 400
    public_message = "学习内容不符合生成要求，请修改后重试"


class InvalidSubmissionError(AppError):
    code = 4003
    status_code = 400
    public_message = "答题记录不完整，请完成全部题目后重试"


class GenerationError(AppError):
    code = 5001
    status_code = 503
    public_message = "题目生成失败，请稍后重试"


class ReportGenerationError(AppError):
    code = 5002
    status_code = 503
    public_message = "复盘报告生成失败，请稍后重试"


class AuthenticationError(AppError):
    code = 4010
    status_code = 401
    public_message = "登录状态已失效，请重新登录"


class RefreshTokenError(AuthenticationError):
    code = 4011
    public_message = "登录凭证已失效，请重新登录"


class ForbiddenError(AppError):
    code = 4030
    status_code = 403
    public_message = "当前操作不允许"


class ResourceNotFoundError(AppError):
    code = 4040
    status_code = 404
    public_message = "没有找到相关内容"


class ConflictError(AppError):
    code = 4090
    status_code = 409
    public_message = "操作已提交，请勿重复操作"


class WechatServiceError(AppError):
    code = 5003
    status_code = 503
    public_message = "微信登录服务暂时不可用，请稍后重试"
