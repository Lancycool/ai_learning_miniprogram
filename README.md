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
ENABLE_WEB_SEARCH=True
TAVILYSEARCH_API_KEY=你的Tavily密钥
```

请运行下面的命令。

```powershell
cd backend
uv sync --dev
uv run alembic upgrade head
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
pnpm test:web-search
pnpm build:weapp
pnpm build:h5
```

## 当前 MVP 边界

当前版本包含账号系统、MySQL、历史学习中心和可选 Tavily 联网增强。海报中的二维码是视觉占位符。后续版本需要接入真实小程序码生成接口。

## 可选联网出题

系统优先读取 `backend/.env` 中的 `TAVILYSEARCH_API_KEY`，并兼容 `TAVILY_API_KEY`。后端 `ENABLE_WEB_SEARCH` 默认开启。请求同名字段 `enable_web_search=false` 可以关闭本次搜索；后端关闭时，请求不能强行打开。缺少或无效密钥不会阻止应用启动，系统会回退原 Prompt。

系统根据主题选择 general/news/finance、basic/advanced、最多 5 或 8 个结果。用户明确时间窗口时，系统设置 week/month/year；用户只说最新时，系统不会增加硬时间过滤。系统只发送精简主题，查询不超过 300 字。检测到明显敏感输入时，系统跳过搜索。系统不抓取网页正文。

系统把有效结果加入独立参考区域。系统在搜索失败时记录不含密钥和查询的 WARNING 日志，并用原 Prompt 出题。模型失败和结构不合格仍返回原错误。响应的 `web_search.status` 为 success、fallback 或 disabled。登录用户在当前学习记录完成前只能看到状态，完成后可以查看有限参考内容与来源链接。旧题库显示搜索状态缺失。

| 配置 | 默认值 |
| --- | --- |
| 首次搜索 / 重试时限 | 10 秒 / 5 秒 |
| 搜索阶段上限 / 重试次数 | 20 秒 / 最多 1 次 |
| 后端总预算 / 前端请求时限 | 55 秒 / 60 秒 |
| 原模型调用保留时间 | REQUEST_TIMEOUT_SECONDS，默认 45 秒 |
| 每进程搜索并发 / 排队 | 4 个 / 1 秒 |
| 搜索熔断 | 60 秒内连续 5 次可恢复故障后暂停 30 秒 |
| 参考上下文 | 最多 8 条，每条 1500 字，总计 6000 字 |

系统按最小可用预算执行。默认 55 秒总预算给搜索留下至多约 10 秒；一次超时后可能没有重试时间，系统会直接用原 Prompt。重试不能侵占原模型链时间。多进程各自限流，Tavily 调用会增加上游费用，取消不能保证撤销已发生的费用。各配置名见 `backend/.env.example`。

当前项目使用本地 FastAPI 直连，仓库没有生产网关配置。团队上线时需要核对网关与真机时限。团队回滚搜索时设置 `ENABLE_WEB_SEARCH=False` 并重启后端，系统恢复原 Prompt，已有题库仍可读取。数据库迁移只增加可空字段，团队不需要删除历史数据。

开发者可以运行固定故障测试，或在已有真实配置时运行三个主题的联网对比。脚本会为每个主题分别生成联网和关闭搜索的题库。重试可能增加搜索或模型的实际调用次数。脚本把有限来源与题库保存到被 Git 忽略的 `backend/data/web-search-acceptance.json`。

```powershell
cd backend
uv run pytest tests/test_web_search.py tests/test_web_search_migration.py tests/test_user_system_api.py
uv run python -m scripts.smoke_web_search
```

开发验收记录见 [联网搜索开发验收](docs/联网搜索开发验收.md)。搜索结果和模型已有知识都可能出错，系统不把搜索成功称为事实已核实。

## 官方资料

- [Taro 4 文档](https://docs.taro.zone/docs/)
- [LangChain DeepSeek 集成](https://docs.langchain.com/oss/python/integrations/chat/deepseek)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)
- [FastAPI 测试文档](https://fastapi.tiangolo.com/tutorial/testing/)
