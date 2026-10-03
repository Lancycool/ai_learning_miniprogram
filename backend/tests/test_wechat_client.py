import pytest

from app.core.config import get_settings
from app.core.exceptions import WechatServiceError
from app.integrations.wechat_client import WechatClient


async def test_wechat_client_requires_configuration() -> None:
    settings = get_settings().model_copy(update={"wechat_app_id": "replace-with-id"})
    with pytest.raises(WechatServiceError):
        await WechatClient(settings).code_to_session("code")


async def test_wechat_client_reads_success_response(monkeypatch) -> None:
    class Response:
        status_code = 200
        def json(self): return {"openid": "openid-1", "unionid": "union-1"}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr("app.integrations.wechat_client.httpx.AsyncClient", Client)
    settings = get_settings().model_copy(update={"wechat_app_id": "appid", "wechat_app_secret": "secret"})
    assert (await WechatClient(settings).code_to_session("code"))["openid"] == "openid-1"


async def test_wechat_client_rejects_wechat_error(monkeypatch) -> None:
    class Response:
        status_code = 200
        def json(self): return {"errcode": 40029}
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr("app.integrations.wechat_client.httpx.AsyncClient", Client)
    settings = get_settings().model_copy(update={"wechat_app_id": "appid", "wechat_app_secret": "secret"})
    with pytest.raises(WechatServiceError):
        await WechatClient(settings).code_to_session("bad-code")
