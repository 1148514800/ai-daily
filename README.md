# ai-daily

每天一份 5～10 分钟可读完的中文 AI 日报。后续系统会自动抓取 AI 新闻、GitHub Trending 和开源项目，经过筛选、去重和 AI 摘要后，通过后端提供给 Android App 阅读。

## 当前开发阶段

Phase 8 - Scheduled Daily Refresh

今日 AI 新闻来自 OpenAI、Google DeepMind 和 Hugging Face 的 RSS；GitHub 页来自官方 Trending。LLM 中文增强可选。日报、新闻、GitHub 项目和收藏持久化在 SQLite 中，重启后仍然存在。后端现在会在每天固定时间自动刷新，并记录每次执行结果。

## 目录结构

```text
ai-daily/
├── mobile/          # Expo + React Native + TypeScript 客户端
├── backend/         # FastAPI 后端
├── tests/           # 仓库级测试预留目录
├── docs/            # 项目文档预留目录
├── AGENTS.md        # 长期开发规则
├── AI_HANDOFF.md    # 当前项目状态
├── PRD.md           # 产品需求
└── README.md
```

## Mobile 启动方式

前置要求：已安装 Node.js。

```bash
cd mobile
npm start
```

然后按终端提示使用 Expo Go 或 Android 模拟器打开。

其他常用命令：

```bash
cd mobile
npm run android
```

## Backend 启动方式

前置要求：已安装 [uv](https://docs.astral.sh/uv/)，Python 3.11+ 由 uv 管理。

本机调试：

```bash
cd backend
uv sync --all-groups
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

给真机或模拟器访问时，需要监听所有网卡：

```bash
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

预期返回：

```json
{"status": "ok"}
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

主要接口：

```text
GET /health
GET /api/v1/daily
GET /api/v1/digests
GET /api/v1/daily/{date}
GET /api/v1/news/{news_id}
GET /api/v1/github
GET /api/v1/github?date={date}
GET /api/v1/favorites
POST /api/v1/favorites
DELETE /api/v1/favorites/{favorite_id}
GET /api/v1/refresh/status
```

运行后端测试：

```bash
cd backend
uv run pytest
```

开发环境开启了宽松 CORS，仅用于本地联调，生产环境不要使用 `allow_origins=["*"]`。


## 当前真实来源

- OpenAI News RSS：`https://openai.com/news/rss.xml`
- Google DeepMind Blog RSS：`https://deepmind.google/blog/rss.xml`
- Hugging Face Blog RSS：`https://huggingface.co/blog/feed.xml`
- 只解析标准 RSS/Atom，不爬 HTML 页面
- 最近 24 小时内的文章进入今日日报
- 来源失败互相隔离：单个源超时或解析失败时，其余源仍会生成日报
- 当前只做保守规则去重（canonical URL、48 小时内完全相同标题），没有语义级事件聚类
- RSS 是事实来源；LLM 只负责中文标题、摘要、Why it matters 和重要度评分
- LLM 失败或关闭时回退到 RSS 原文，服务仍可启动
- 成功结果写入本地磁盘 Cache（backend/.cache/），避免重复消耗 Token
- GitHub Trending：真实，来自 https://github.com/trending?since=daily
- GitHub AI 筛选使用确定性规则，不调用 LLM 分类
- 关键词分两层：Core/Strong（如 `llm`、`rag`、`diffusion`、`machine-learning`、`stable-diffusion`、`langchain`，以及工具类的 `mcp`）与 Weak（如 `agent`、`model`、`vision`、`chat`、`copilot`）
- 评分：topics 强关键词 +4、description 强关键词 +3、repo/name 强关键词 +2、弱关键词每个 +1（上限 3）
- 入选必须存在 Core 证据：description/name 里的 Core 关键词直接入选；只有 topics 命中 Core 时需要达到分数阈值
- 工具关键词（如 `mcp`）不能单独入选，必须另有 Core 证据佐证，因为普通开发工具也常自称 MCP tools / AI agents
- Weak 关键词不能单独入选，需要 2 个来自不同字段的 Weak 关键词，且必须另有 Core 证据
- 只有 topics 命中、description 与 name 都没有 Core 关键词时不会入选，避免自填 topics 造成误报
- 保守 negative hints（`crm`、`todo`、`game`、`adhd` 等）会否决上述所有情况，但 description/name 中的 Core 证据仍然生效
- GitHub REST metadata 可用时按常规规则判断；metadata 不可用（例如匿名 rate limit）时自动切换 strict fallback，只接受 description/name 中的 Core 证据

手动测试单个 OpenAI collector：

```bash
cd backend
uv run python -m app.collectors.openai
```

手动测试全部来源：

```bash
cd backend
uv run python -m app.collectors.refresh
```

会打印每个来源的抓取数量、GitHub 筛选结果，以及数据库写入情况：

```text
Total:
Fetched: X
Valid: X
Last 24h: X
After dedup: X

Candidates: X
LLM:
Success: X
Cache hit: X
Fallback: X
Failed: X
[92] OpenAI | title_cn

Digest saved: 2026-09-12
News: 3
GitHub: 1

Database
Daily digests: 1
News total: 3
GitHub repos total: 1
```

GitHub 部分会打印筛选结果，默认只显示入选项目和拒绝数量：

```text
GitHub Trending
Fetched: 16
Parsed: 16
AI candidates: 1
Metadata success: 0
Selected: 1

AI filtering:

ACCEPT
#8 nashsu/llm_wiki
score=6
strong=[llm, rag]
weak=[]
source=description/name

(15 rejected; set AI_DAILY_DEBUG_GITHUB=1 for per-repo reasons)

Accepted: 1/16
```

设置 `AI_DAILY_DEBUG_GITHUB=1` 可以看到每个仓库的 `mode`、`route`、`metadata`、`negative` 与 `reason`：

```bash
cd backend
AI_DAILY_DEBUG_GITHUB=1 uv run python -m app.collectors.refresh
```

应用启动时会按需触发后台 refresh，并写入数据库。`GET /api/v1/daily` 读取数据库中最新的日报，不会每次请求都重新访问 RSS。

## 数据持久化

- 当前使用 SQLite + SQLAlchemy 2.x，适合个人单用户场景
- 数据库文件：`backend/data/ai_daily.db`（`backend/data/` 已加入 `.gitignore`，不会提交）
- 连接串由环境变量 `DATABASE_URL` 控制，默认 `sqlite:///./data/ai_daily.db`
- 相对路径始终相对 `backend/` 解析，与启动时的工作目录无关；目录不存在时会自动创建
- 日报日期由 `APP_TIMEZONE` 计算，默认 `Asia/Shanghai`；采集时间仍以 UTC 保存
- 本阶段不做数据库迁移系统，表结构由 `Base.metadata.create_all()` 初始化

存储内容：

```text
news_articles        新闻正文与元数据（稳定 ID upsert）
github_projects      GitHub 项目（repo 稳定 ID upsert）
daily_digests        每天的日报（date 主键，一天一条）
daily_digest_news    日报与新闻的排序关系
daily_digest_github  日报与 GitHub 项目的排序关系
favorites            收藏（item_type + item_id，单用户）
refresh_runs         每次刷新执行记录（trigger / status / 计数 / 简短错误）
```

同一天多次 refresh 只会更新当天日报，不会新增多条；第二天 refresh 会创建新的日报，历史保持不变。如果某次采集没有拿到任何新闻，会保留数据库中已有的当天日报，避免临时网络失败把日报清空。

未来可迁移到 PostgreSQL 与多用户模型，但本阶段不实现。

## 每日自动刷新

后端使用进程内 APScheduler（`AsyncIOScheduler`），随 FastAPI 生命周期启动和关闭。

默认行为：

```text
每天北京时间 08:00 自动执行一次 refresh
```

相关环境变量（`backend/.env.example` 有完整说明）：

```bash
SCHEDULER_ENABLED=true
DAILY_REFRESH_HOUR=8
DAILY_REFRESH_MINUTE=0
APP_TIMEZONE=Asia/Shanghai
```

- `SCHEDULER_ENABLED=false` 时不注册定时任务，FastAPI API 照常工作
- 时间与 `APP_TIMEZONE` 一起生效，不在代码里写死时区
- 调度器只负责“到点调用”，采集逻辑仍然是 `refresh_all()` 一套
- `coalesce=True` + `max_instances=1`，重复错过只补跑一次
- `misfire_grace_time` 为 1 小时，短暂休眠不会直接漏掉当天任务

启动补偿（catch-up）：

```text
启动时如果今天已过计划时间、且数据库里今天还没有成功刷新
→ 后台补跑一次（trigger=startup_catchup）
```

补跑以后台任务方式触发，不会阻塞 FastAPI 启动，API 会先用数据库里已有的日报提供服务。

避免重复执行：

- 进程内使用互斥锁，已有 refresh 运行时第二次调用会跳过并记录日志
- 同一天多次 refresh 只会更新当天日报，不会产生多条 `daily_digests`

执行记录与状态接口：

```text
GET /api/v1/refresh/status
```

会返回 `scheduler_enabled`、`timezone`、`scheduled_time`、`last_run` 和 `next_run_at`，不包含任何 Secret。

> 当前 Scheduler 只适用于本地开发与单进程部署。如果使用 `uvicorn --workers > 1`，每个 worker 都会有自己的 Scheduler，因此当前必须保持单 worker。云端生产部署会在后续阶段改用外部 Scheduler / Cron 调用统一的 refresh job，本阶段不实现分布式锁。

`refresh_runs` 表记录每次执行（`manual` / `scheduled` / `startup_catchup`），只保存简短错误原因，完整 traceback 只写日志：

```text
status: running / success / failed
```

成功判定依据是日报真的写入数据库且有内容；单个 RSS 源失败不影响整体结果，全部采集失败或数据库写入失败会记录为 `failed`，且不会覆盖当天已存在的有效日报。

## Mobile 连接 Backend

默认 API 地址：

```text
http://127.0.0.1:8000
```

Expo 通过环境变量读取：

```text
EXPO_PUBLIC_API_BASE_URL
```

复制 `mobile/.env.example` 为 `mobile/.env` 后按环境修改：

```bash
# 本机 / Expo web
EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8000

# Android 模拟器
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000

# 真机：改成电脑的局域网 IP，不要把该 IP 提交进仓库
EXPO_PUBLIC_API_BASE_URL=http://192.168.x.x:8000
```

修改 `.env` 后需要重启 Expo。

## LLM 配置

复制 `backend/.env.example` 为 `backend/.env`：

```bash
LLM_ENABLED=true
LLM_API_KEY=your-key
LLM_MODEL=your-model
LLM_BASE_URL=https://api.example.com/v1
```

说明：

- 不要把 API Key 写进代码或提交 `.env`
- `LLM_ENABLED=false` 或没有 API Key 时，后端仍返回最近 24 小时去重后的 RSS 原文
- LLM 只处理 24h + 去重后的候选，不会把历史 RSS 全部送去生成
- 使用 OpenAI 兼容的 `/chat/completions` 接口
- 本地 Cache 目录是 `backend/.cache/`，已加入 `.gitignore`

启动后端时会自动读取 `backend/.env`。也可以显式传入：

```bash
cd backend
uv run --env-file .env uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## 数据来源现状

- RSS：真实
- GitHub Trending：真实
- LLM：可选
- 数据存储：SQLite（`backend/data/ai_daily.db`）
- 自动定时：APScheduler 每日刷新 + 启动补偿（单进程内）

GitHub 热门项目来自官方 Trending 页面，`stars_delta` 表示页面上的 stars today，不是历史快照差值。

可选配置 GitHub Token，提高 REST metadata 的 rate limit：

```bash
GITHUB_TOKEN=ghp_xxx
```

没有 Token 时仍会请求公开仓库。Token 只用于后端，不会下发到 Mobile，也不要提交到 Git。
