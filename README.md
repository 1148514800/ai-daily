# ai-daily

每天一份 5～10 分钟可读完的中文 AI 日报。后续系统会自动抓取 AI 新闻、GitHub Trending 和开源项目，经过筛选、去重和 AI 摘要后，通过后端提供给 Android App 阅读。

## 当前开发阶段

Phase 6 - GitHub Trending

今日 AI 新闻来自 OpenAI、Google DeepMind 和 Hugging Face 的 RSS；GitHub 页来自官方 Trending。LLM 中文增强可选。数据目前保存在内存中，尚未做数据库或定时任务。

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
GET /api/v1/daily/{date}
GET /api/v1/news/{news_id}
GET /api/v1/github
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

会打印每个来源的抓取数量，以及：

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
```

应用启动时会 refresh 一次。`GET /api/v1/daily` 读取内存中的日报，不会每次请求都重新访问 RSS。

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
- 数据存储：当前内存
- 自动定时：尚未实现

GitHub 热门项目来自官方 Trending 页面，`stars_delta` 表示页面上的 stars today，不是历史快照差值。

可选配置 GitHub Token，提高 REST metadata 的 rate limit：

```bash
GITHUB_TOKEN=ghp_xxx
```

没有 Token 时仍会请求公开仓库。Token 只用于后端，不会下发到 Mobile，也不要提交到 Git。
