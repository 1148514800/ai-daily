# AI_HANDOFF.md

Current Phase: Phase 9

Completed:
- 项目初始化
- Mobile 工程骨架
- Backend 工程骨架
- Android 静态 UI
- FastAPI mock API 与 Mobile 联调
- OpenAI / DeepMind / Hugging Face RSS
- 统一 RSS Collector、URL 标准化和规则去重
- LLM 中文标题 / 摘要 / Why it matters / importance_score
- GitHub Trending 真实采集、AI 筛选、REST metadata、可选 LLM 增强
- GitHub AI 筛选改为 strong/weak keyword evidence + strict fallback（Phase 6.1）
- SQLite 持久化、历史日报与真实收藏（Phase 7）
- 每日自动刷新、刷新记录与启动补偿（Phase 8）
- Android 日报 Push 通知（Phase 9）

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- RSS -> Collector -> 24h filter -> rule dedup -> LLM enrich -> SQLite
- GitHub Trending HTML -> AI filter (strong/weak + strict fallback) -> GitHub REST metadata -> optional LLM enrich -> SQLite
- Database -> API -> Mobile：数据库是唯一 source of truth，API 读取全部来自 SQLite
- SQLAlchemy 2.x + SQLite（backend/data/ai_daily.db），表结构由 metadata.create_all() 初始化，暂不引入 Alembic
- 日报日期按 APP_TIMEZONE（默认 Asia/Shanghai）计算，采集时间仍保存 UTC
- Scheduler：进程内 APScheduler（AsyncIOScheduler）+ FastAPI lifespan，默认每天 08:00（APP_TIMEZONE）执行 refresh_all()
- RefreshRun：refresh_runs 表记录 manual / scheduled / startup_catchup 的执行状态，只存简短错误
- Startup catch-up：启动时若已过计划时间且今天没有成功刷新，则后台补跑一次，不阻塞启动
- Refresh status：GET /api/v1/refresh/status 返回 scheduler 状态、最近一次执行与下次执行时间
- Push：Expo Notifications + Expo Push Service，客户端使用 Development Build（含 FCM 配置）
- PushDevice：push_devices 表按 Expo Push Token 唯一 upsert，单用户，无 User 表
- 通知时机：仅 scheduled / startup_catchup 成功后推送；manual 不推送
- 防重复：daily_digests.notified_at，至少一台设备成功后写入，同一天只通知一次
- LLM 使用环境变量配置，失败回退原文，结果缓存到 backend/.cache
- uv + CPython 3.11

Next:
Phase 10 - deployment and installable Android build

Known Issues:
- 无语义级事件聚类
- GitHub 强关键词列表仍需按实际误报迭代
- 未配置 GITHUB_TOKEN 时 REST metadata 易被匿名 rate limit 限制，此时自动使用 strict fallback
- Scheduler 为进程内实现，仅支持单 worker；多 worker / 云部署需要外部 Scheduler
- 计划失败后仅自动重试一次（15 分钟后），仍失败则等下一次正常调度
- Push 未配置（PUSH_ENABLED=false）时不会发送通知；Android remote push 需要真机 + Development Build
- 只处理 Expo Push send 的即时响应，尚无 Receipt polling
- 数据库 schema 变更依赖 create_all() + 轻量 ADD COLUMN 补列，仍无迁移框架
- 收藏为单用户模型，没有登录与多设备同步
- 开发环境 CORS 允许所有来源，仅限 development
