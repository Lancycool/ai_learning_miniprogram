import httpx

from app.core.config import Settings
from app.core.exceptions import WechatServiceError


class WechatClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def code_to_session(self, code: str) -> dict[str, str]:
        if not self.settings.wechat_app_id or self.settings.wechat_app_id.startswith("replace-"):
            raise WechatServiceError("请先在 backend/.env 中填写微信测试号 AppID 和 AppSecret")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.settings.wechat_api_base_url}/sns/jscode2session",
                    params={"appid": self.settings.wechat_app_id, "secret": self.settings.wechat_app_secret, "js_code": code, "grant_type": "authorization_code"},
                )
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise WechatServiceError() from exc
        if response.status_code != 200 or data.get("errcode") or not data.get("openid"):
            raise WechatServiceError("微信登录凭证无效，请重新进入小程序")
        return {"openid": data["openid"], "unionid": data.get("unionid", "")}
