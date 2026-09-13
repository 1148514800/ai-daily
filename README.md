# ai-daily

每天一份 5～10 分钟可读完的中文 AI 日报。后续系统会自动抓取 AI 新闻、GitHub Trending 和开源项目，经过筛选、去重和 AI 摘要后，通过后端提供给 Android App 阅读。

## 当前开发阶段

Phase 10 - Local Deployment

今日 AI 新闻来自中外官方模型厂商与 AI 媒体的公开 RSS / 官方页面；GitHub 页来自官方 Trending。LLM 中文增强可选。日报、新闻、GitHub 项目和收藏持久化在 SQLite 中，重启后仍然存在。后端每天固定时间自动刷新。

当前阶段的目标是让整套系统在本地 Windows 电脑上长期运行，并生成可以直接安装到真机的 Android APK。App 打开时主动拉取最新日报，**不使用系统 Push 通知**（见 "Push 状态"）。

## 目录结构

```text
ai-daily/
├── mobile/          # Expo + React Native + TypeScript 客户端
├── backend/         # FastAPI 后端
├── scripts/         # 本地部署脚本（启动 / 自启动 / 备份）
├── backups/         # SQLite 备份输出（已 gitignore）
├── logs/            # 后端运行日志（已 gitignore）
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

然后按终端提示使用 Expo Go 或 Android 模拟器打开。真机安装与发布见 [Local Deployment](#11-生成可安装的-apk)。

其他常用命令：

```bash
cd mobile
npm run android
```

类型检查与单元测试：

```bash
cd mobile
npm run typecheck
npm test
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

长期运行（不使用 `--reload`，单 worker）见 [Local Deployment](#2-启动-backend)。

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
GET /api/v1/system/status
```

运行后端测试：

```bash
cd backend
uv run pytest
```

运行 Mobile 类型检查与单元测试：

```bash
cd mobile
npx tsc --noEmit
npm test
```

开发环境开启了宽松 CORS，仅用于本地联调，生产环境不要使用 `allow_origins=["*"]`。


## 当前真实来源

官方一手来源（`source_type=official`，去重时优先）：

- OpenAI News RSS：`https://openai.com/news/rss.xml`
- Anthropic News：`https://www.anthropic.com/news`（官方页面 HTML）
- Google DeepMind Blog RSS：`https://deepmind.google/blog/rss.xml`
- Meta AI（Meta Engineering AI Research RSS）：`https://engineering.fb.com/category/ai-research/feed/`
- NVIDIA Blog RSS：`https://blogs.nvidia.com/feed/`
- DeepSeek News：`https://api-docs.deepseek.com/news/`（官方文档站 HTML）
- Qwen Blog RSS（Atom/`index.xml`）：`https://qwenlm.github.io/blog/index.xml`
- Kimi Research Blog：`https://www.kimi.com/en/blog/`（官方页面 HTML）

社区博客：

- Hugging Face Blog RSS：`https://huggingface.co/blog/feed.xml`

媒体来源（`source_type=media`，同一事件去重时让位于官方源）：

- TechCrunch AI RSS：`https://techcrunch.com/category/artificial-intelligence/feed/`
- 量子位 RSS：`https://www.qbitai.com/feed`

- 优先使用官方 RSS / Atom，其次官方公开页面，最后稳定媒体 RSS
- 只接入已确认可稳定公开采集的来源；没有稳定 Feed、且页面结构不适合轻量解析的来源不接入
- HTML 来源都在 `app/collectors/html.py` 中各自独立解析，任一来源失败只影响自身
- 机器之心未接入：服务端对所有请求（含 `robots.txt` 中声明的 sitemap 与实际文章页）统一返回同一个 3251 字节的机器人拦截页，没有可用的 RSS 或文章列表
- 日报不再按自然日归档，而按 **issue window** 归档：`window_start < published_at <= window_end`（左开右闭，UTC）
- 窗口从「上一次成功日报的 cutoff」延续到「本次 refresh 时间」，所以 09-12 20:00 与 09-13 08:00 的新闻都进入 09-13 日报，09-13 08:00:01 的新闻不进入
- 未来时间的文章一律不能进入当前日报（`window_end` 不会晚于 refresh 时间）
- 第一份日报默认覆盖过去 24h：`window_start = refresh 时间 - 24h`
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
- 日报日期（`date` 主键）仍由 `APP_TIMEZONE` 计算，默认 `Asia/Shanghai`；采集时间（`published_at`）与窗口（`window_start` / `window_end`）统一以 UTC 保存
- 一条新闻只属于一个窗口：`window_start < published_at <= window_end`，同一份日报的链接不会跨窗口重复
- 本阶段不做数据库迁移系统，表结构由 `Base.metadata.create_all()` 初始化；Phase 10.2 新增的 `window_start` / `window_end` 由轻量 `ALTER TABLE ADD COLUMN` 补列

存储内容：

```text
news_articles        新闻正文与元数据（稳定 ID upsert）
github_projects      GitHub 项目（repo 稳定 ID upsert）
daily_digests        每天的日报（date 主键，一天一条，含 UTC window_start / window_end）
daily_digest_news    日报与新闻的排序关系
daily_digest_github  日报与 GitHub 项目的排序关系
favorites            收藏（item_type + item_id，单用户）
refresh_runs         每次刷新执行记录（trigger / status / 计数 / 简短错误）
push_devices         已注册的 Expo Push Token（单用户，token 唯一）
```

同一天多次 refresh 只会更新当天日报，不会新增多条；已链接的新闻会保留并按 news_id 去重（08:00 得到 A B，18:00 得到 C D，最终是 A B C D），`window_start` 不变、`window_end` 前移。第二天 refresh 会创建新的日报，新日报的 `window_start` 等于上一份成功日报的 `window_end`，因此漏跑一天时窗口会自动跨过漏掉的那天，而不是固定只抓最近 24h。如果某次采集没有拿到任何新闻，会保留数据库中已有的当天日报，避免临时网络失败把日报清空。

未来可迁移到 PostgreSQL 与多用户模型，但本阶段不实现。

### 修复历史日报归属

如果历史数据里存在窗口污染（例如未来时间的新闻进了某天日报），可以只根据数据库里已保存的 `news_articles` 重建日报关系：

```bash
cd backend
uv run python -m app.jobs.rebuild_digests --dates 2026-09-12,2026-09-13
```

- 只读 `news_articles` 里的 `published_at`（UTC），按 issue window 重新判断归属，再重建 `daily_digest_news` 关联
- 窗口优先取该日报已保存的 `window_start` / `window_end`；没有保存时按 `DAILY_REFRESH_HOUR` + `APP_TIMEZONE` 推导为 `(cutoff(D-1), cutoff(D)]`，例如 08:00 Asia/Shanghai 下 2026-09-12 的窗口是 `2026-09-11T00:00Z .. 2026-09-12T00:00Z`
- 命令会把推导出的窗口写回该日报，方便下次继续沿用
- 不重新调用 RSS 或 LLM，也不删除任何 `news_articles` 原始记录
- 只重建传入日期的日报关系，其他日期不受影响；GitHub 关联保持不变
- 命令幂等，可重复执行

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

## Push 状态（本阶段不使用系统通知）

产品决策：**当前不使用系统 Push 通知**。

```text
App 打开 → 主动请求 /api/v1/daily → 显示最新日报
```

因此本阶段：

- 不需要 Firebase
- 不需要 FCM
- 不需要 Expo Push Token
- 不需要 `google-services.json`

APK 构建不再依赖任何推送凭据，`mobile/app.json` 中已删除 `googleServicesFile` 与 `expo-notifications` 插件，客户端依赖中也已移除 `expo-notifications` / `expo-device`。

Backend 的 Push 代码仍然保留，但处于 dormant 状态：

```bash
PUSH_ENABLED=false
```

`PUSH_ENABLED=false` 时不会请求 Firebase、不会请求 Expo Push、不会注册 Token，也不影响 App 启动、Scheduler 和日报生成（有测试覆盖）。

客户端侧已完全移除推送代码与依赖：App 不再申请通知权限、不再获取 Push Token、不再在启动时注册。未来若需要恢复通知，可参考 Phase 9 的提交重新接入 `expo-notifications` 并配置 Firebase / FCM。

推送相关接口（保留但默认关闭）：

```text
GET  /api/v1/push/status
POST /api/v1/push/register
POST /api/v1/push/test     # 仅 PUSH_ENABLED=true 时可用
```

## Mobile 连接 Backend

App 请求的地址按以下优先级解析：

```text
1. 用户在「设置 → Backend 地址」中保存的地址（AsyncStorage）
2. EXPO_PUBLIC_API_BASE_URL（构建时写入）
3. http://127.0.0.1:8000（兜底）
```

推荐做法：**在 App 内填写 Backend 地址**，而不是把局域网 IP 编译进 APK。

原因：

- 电脑 IP 改变后不需要重新编译 APK
- 换 Wi-Fi、换电脑、以后搬到云服务器都只需要改设置
- 代码里不出现任何具体局域网 IP

### 设置页行为

```text
设置 → Backend 地址
→ 输入 http://192.168.1.100:8000
→ 测试连接（调用 GET /health）
→ 连接成功 / 无法连接服务器
→ 保存
```

- 只接受 `http://` 或 `https://` 开头的合法 URL，明显无效的地址不会保存
- 「恢复默认地址」会清除本地保存的值，回到构建时的默认值
- 保存后立即生效，不需要重启 App

### 构建时默认值（可选）

复制 `mobile/.env.example` 为 `mobile/.env` 并按环境修改：

```bash
# 本机 / Expo web
EXPO_PUBLIC_API_BASE_URL=http://127.0.0.1:8000

# Android 模拟器
EXPO_PUBLIC_API_BASE_URL=http://10.0.2.2:8000

# 真机：电脑的局域网 IP，不要把该 IP 提交进仓库
EXPO_PUBLIC_API_BASE_URL=http://192.168.x.x:8000
```

修改 `.env` 后需要重启 Expo。

### 离线行为

Backend 不可达时 App 不会崩溃，会显示：

```text
无法连接 AI Daily 服务，请检查后端地址与网络
```

以及「重新加载」按钮。SQLite 在 Backend 侧，本阶段不实现手机端离线数据库。

### Android Cleartext

本地部署使用 HTTP。Release APK 默认禁止明文流量，因此 `mobile/app.json` 通过 `expo-build-properties` 显式开启：

```json
{ "android": { "usesCleartextTraffic": true } }
```

这是针对当前 App 的最小配置。未来迁移到云服务器时应改用 HTTPS 并移除该项。

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

## Local Deployment

本阶段部署在**用户自己的 Windows 电脑**上，目标是可以长期运行、重启后仍能使用。

架构：

```text
Windows 电脑
├── FastAPI Backend
├── SQLite（backend/data/ai_daily.db）
├── APScheduler（每天 08:00 自动刷新）
└── HTTP :8000
        ↓  局域网
   Android APK（用户主动打开 → 拉取最新日报）
```

本阶段不使用 Docker、PostgreSQL、Nginx、Redis 或云服务器。

### 1. Backend `.env`

```bash
cd backend
copy .env.example .env
```

本地长期运行建议值：

```bash
APP_TIMEZONE=Asia/Shanghai
SCHEDULER_ENABLED=true
DAILY_REFRESH_HOUR=8
DAILY_REFRESH_MINUTE=0
DATABASE_URL=sqlite:///./data/ai_daily.db
PUSH_ENABLED=false
```

LLM 与 GitHub Token 都可以留空：

- `LLM_ENABLED=false` 时日报回退为英文原文，功能正常
- 未配置 `GITHUB_TOKEN` 时使用 strict fallback，功能正常，但受 60 requests/hour 匿名限制

`backend/.env` 不提交 Git。

### 2. 启动 Backend

**生产式启动**（不使用 `--reload`）：

```bash
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

或者使用脚本（会同时打印手机可用的局域网 URL 并写日志）：

```powershell
.\scripts\start_backend.ps1
```

> 只使用 **1 个 worker**。APScheduler 是进程内调度器，`--workers 4` 会导致多个进程各自启动 Scheduler 并重复执行日报任务。

验证：

```text
电脑浏览器：http://127.0.0.1:8000/health      → {"status":"ok"}
```

部署自检（不含任何 Secret）：

```text
GET /api/v1/system/status
→ {"status":"ok","database":"ok","scheduler_enabled":true,...}
```

### 3. Windows 开机自启动

创建计划任务（**不需要管理员权限**，登录后自动运行，可重复执行）：

```powershell
.\scripts\install_startup_task.ps1
```

删除计划任务：

```powershell
.\scripts\uninstall_startup_task.ps1
```

任务名为 `AI Daily Backend`。可用以下命令确认：

```powershell
Get-ScheduledTask -TaskName 'AI Daily Backend' | Select-Object TaskName, State
```

### 4. 获取电脑局域网 IP

```powershell
Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
  Select-Object IPAddress, InterfaceAlias
```

例如得到 `192.168.0.107`，那么手机应访问：

```text
http://192.168.0.107:8000
```

建议在路由器里为这台电脑设置 **DHCP Static Lease**（固定 IP），这样地址不会变化。

### 5. Windows Defender Firewall

手机打不开 `http://电脑IP:8000/health` 时，通常是防火墙拦截。

只放行 **TCP 8000**，并且只对 **专用网络（Private）** 生效：

```powershell
New-NetFirewallRule -DisplayName 'AI Daily Backend (TCP 8000)' `
  -Direction Inbound -Protocol TCP -LocalPort 8000 `
  -Profile Private -Action Allow
```

删除该规则：

```powershell
Remove-NetFirewallRule -DisplayName 'AI Daily Backend (TCP 8000)'
```

> 不要直接关闭整个 Windows Defender Firewall。

### 6. App 配置 Backend URL

安装 APK 后，打开 App 的「设置」页填写 Backend 地址（见上一节）。不需要重新编译 APK。

### 7. Scheduler

```text
每天 08:00（APP_TIMEZONE）自动 refresh
```

检查状态：

```text
GET /api/v1/refresh/status
→ scheduler_enabled=true, next_run_at=次日 08:00
```

不用等到第二天验证：可以先在 App 里触发一次手动刷新，或者：

```bash
cd backend
uv run python -m app.collectors.refresh
```

### 8. SQLite 位置

```text
backend/data/ai_daily.db
```

数据库中包含日报、新闻、GitHub 项目和收藏。`backend/data/` 已加入 `.gitignore`。

### 9. 数据备份

```powershell
.\scripts\backup_db.ps1
```

行为：

```text
backend/data/ai_daily.db
↓
backups/ai_daily_YYYYMMDD_HHMMSS.db
```

默认保留最近 14 份（`-Keep 0` 表示全部保留）。当数据库写入很少时直接复制文件即可；`backups/` 已加入 `.gitignore`。

### 10. HTTP 与 HTTPS

```text
本地部署阶段使用 HTTP。
未来云服务器阶段改为 HTTPS。
```

Release APK 默认禁止明文流量，因此 `mobile/app.json` 里通过 `expo-build-properties` 打开了 `android.usesCleartextTraffic`。这是当前 App 的最小必要配置；迁移到 HTTPS 后应当移除。

### 11. 生成可安装的 APK

`mobile/eas.json` 的 `preview` profile 输出 `APK`（不是 AAB），用于直接安装到自己的手机：

```bash
cd mobile
npx eas login
npx eas init                      # 写入 extra.eas.projectId（仅用于 EAS Build，与 Push 无关）
npx eas build --profile preview --platform android
```

- 不需要 `google-services.json`
- 不需要 Firebase / FCM / Expo Push Credentials
- 签名可使用 EAS Managed Credentials
- 本阶段不发布 Google Play

构建前可用以下命令确认 resolved config 中没有 Firebase 配置：

```bash
cd mobile
npx expo config --type public
```

应满足：

```text
android.package = com.aidaily.app
android.googleServicesFile 不存在
```

也可以用本地 Android SDK 直接构建：`npx expo prebuild --platform android` 后执行
`android/gradlew.bat :app:assembleRelease`，产物在 `android/app/build/outputs/apk/release/app-release.apk`。
`mobile/android/` 与 `mobile/ios/` 都是生成目录，不提交 Git。

### 12. 真机验收清单

1. 浏览器访问 `http://电脑IP:8000/health`，应返回 `{"status":"ok"}`
2. 安装 APK 并启动 AI Daily
3. 设置页填写 Backend 地址 → 测试连接 → 保存
4. 依次确认：今日 / GitHub / 历史 / 收藏
5. 收藏一条新闻，关闭 App 再打开，确认收藏仍在

手动刷新后检查：

```text
GET /api/v1/refresh/status
→ scheduler_enabled=true, next_run_at=次日 08:00
```

不需要等到 08:00：Scheduler 已由 Phase 8 单测覆盖。

## 数据来源现状

- RSS：真实
- GitHub Trending：真实
- LLM：可选
- 数据存储：SQLite（`backend/data/ai_daily.db`）
- 自动定时：APScheduler 每日刷新 + 启动补偿（单进程内）
- Push：不使用（产品决策，Backend 代码保留为 dormant，默认 PUSH_ENABLED=false）

GitHub 热门项目来自官方 Trending 页面，`stars_delta` 表示页面上的 stars today，不是历史快照差值。

可选配置 GitHub Token，提高 REST metadata 的 rate limit：

```bash
GITHUB_TOKEN=ghp_xxx
```

没有 Token 时仍会请求公开仓库。Token 只用于后端，不会下发到 Mobile，也不要提交到 Git。
