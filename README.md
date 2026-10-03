# 竹知岛 AI 闯关学习小程序

这个仓库包含 MVP 的 Taro 小程序前端和 FastAPI 后端。用户可以输入学习主题。系统会生成五道题，并提供即时反馈、经验值、学习报告和分享海报。

## 目录

- `frontend/`：Taro 4 + React + TypeScript 小程序。
- `backend/`：FastAPI + LangChain + DeepSeek 服务。
- `docs/`：需求和方案文档。
- `prototypes/`：UI 原型和设计规则。

## 环境要求

- Node.js 18 或更高版本。
- pnpm 11。
- Python 3.11 到 3.13。
- uv。
- 微信开发者工具。

## 启动后端

后端从 `backend/.env` 读取模型配置。配置格式如下。请不要把真实密钥提交到 Git。

```dotenv
API_KEY=你的密钥
BASE_URL=https://api.deepseek.com
MODEL=deepseek-flash
```

请运行下面的命令。

```powershell
cd backend
uv sync --dev
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

服务启动后，接口文档位于 `http://127.0.0.1:8000/docs`。健康检查位于 `http://127.0.0.1:8000/api/v1/health`。

MySQL 8 重启后会重新验证数据库密码。后端依赖中的 `cryptography` 支持这一步。
开发者更新依赖后需要重启后端进程，因为旧进程不会自动加载新安装的依赖。
开发者可以在 `backend` 目录运行以下命令，检查数据库连接、登录表和微信配置是否齐全。
脚本只读取数据库，不输出密码、Token 和用户身份信息。

```powershell
uv run python -m scripts.check_auth
```

后端提供两个核心接口。

- `POST /api/v1/quiz/generate`：生成三道单选题、一道多选题和一道判断题。
- `POST /api/v1/report/generate`：重新核对答案，并生成学习报告。

## 启动小程序

请先启动后端。然后运行下面的命令。

```powershell
cd frontend
pnpm install
pnpm dev:weapp
```

请使用微信开发者工具导入 `frontend` 目录。`project.config.json` 已把 `dist/` 设置为小程序目录。正式发布前，请把 `touristappid` 换成真实 AppID。开发环境默认访问 `http://127.0.0.1:8000`。

生产环境需要复制 `frontend/.env.production.example` 为 `frontend/.env.production`。你还需要填写已备案的 HTTPS API 地址。微信公众平台也需要配置相同的请求域名。

## 验证命令

后端测试使用 TDD 编写。测试会核对题目模型、内容过滤、评分、报告、接口错误和模型重试。覆盖率门槛是 90%。

```powershell
cd backend
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=90
uv run python -m scripts.smoke_live
```

第二条命令会调用两次真实模型接口。脚本只输出题型数量和报告结果。脚本不会输出 API 密钥。

前端可以运行下面的检查。

```powershell
cd frontend
pnpm typecheck
pnpm build:weapp
pnpm build:h5
```

## 当前 MVP 边界

当前版本不包含账号系统、数据库、联网搜索和历史学习中心。海报中的二维码是视觉占位符。后续版本需要接入真实小程序码生成接口。

## 官方资料

- [Taro 4 文档](https://docs.taro.zone/docs/)
- [LangChain DeepSeek 集成](https://docs.langchain.com/oss/python/integrations/chat/deepseek)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [FastAPI 测试文档](https://fastapi.tiangolo.com/tutorial/testing/)
