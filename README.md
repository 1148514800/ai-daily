# ai-daily

每天一份 5～10 分钟可读完的中文 AI 日报。后续系统会自动抓取 AI 新闻、GitHub Trending 和开源项目，经过筛选、去重和 AI 摘要后，通过后端提供给 Android App 阅读。

## 当前开发阶段

Phase 3 - OpenAI News RSS

今日日报来自 OpenAI 官方 RSS。GitHub 页面仍为 mock。尚未实现中文 AI 摘要、数据库或定时任务。

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
- 只解析 RSS，不爬 OpenAI HTML 页面
- 最近 24 小时内的文章进入今日日报
- 当前直接使用 RSS 原标题和原摘要，没有中文翻译或 AI 摘要
- GitHub 页面仍返回 Phase 2 mock 数据

手动测试 collector：

```bash
cd backend
uv run python -m app.collectors.openai
```

会打印：

```text
Fetched: X
Valid: X
Skipped: X
Last 24h: X
published_at | title
```

应用启动时会 refresh 一次。`GET /api/v1/daily` 读取内存中的日报，不会每次请求都访问 OpenAI。

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
