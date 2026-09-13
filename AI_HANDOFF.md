# AI_HANDOFF.md

Current Phase: Phase 10.2（Issue Window 日报模型）

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
- 本地长期部署、可配置 Backend URL 与可安装 APK（Phase 10）
- 日报日期归属修复：future timestamp bug + natural-day invariant + 历史日报重建（Phase 10.1）
- 日报改为 Issue Window（Since Last Successful Digest）：daily_digests 新增 window_start / window_end（UTC），窗口为 (window_start, window_end]（Phase 10.2）

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- RSS -> Collector -> issue window filter（window_start < published_at <= window_end，未来时间自然被剔除）-> rule dedup -> LLM enrich -> SQLite
- GitHub Trending HTML -> AI filter (strong/weak + strict fallback) -> GitHub REST metadata -> optional LLM enrich -> SQLite
- Database -> API -> Mobile：数据库是唯一 source of truth，API 读取全部来自 SQLite
- SQLAlchemy 2.x + SQLite（backend/data/ai_daily.db），表结构由 metadata.create_all() 初始化，暂不引入 Alembic
- 日报 date 仍按 APP_TIMEZONE（默认 Asia/Shanghai）计算；published_at 与 window_start / window_end 统一保存 UTC
- 归属是 invariant：一条新闻只属于一个窗口，窗口为左开右闭 (window_start, window_end]，所以相邻日报的 news_id 交集必然为空
- 窗口推导（app/services/digest_window.py）：已存在日报沿用其 window_start 并把 window_end 前移到当前 refresh；新日报 window_start = 上一份成功日报的 window_end；第一份日报 window_start = 当前时间 - 24h
- 漏跑一天不丢内容：窗口从「上一次成功 cutoff」延续，而不是固定最近 24h
- 同日二次 refresh 是合并而非覆盖：旧链接保留在前，新链接按 news_id 去重追加，window_start 不变、window_end 前移
- 写入前有最终防线：DigestStore.persist() 在写 daily_digest_news 之前对最终 id 列表再校验一次窗口，窗口外文章仍保存在 news_articles，但不建立关联
- 一次性修复命令：uv run python -m app.jobs.rebuild_digests --dates 2026-09-12,2026-09-13，只读 news_articles 重建 daily_digest_news，不调用 RSS / LLM，不删除原始记录；窗口优先用日报已存的 window，否则按 DAILY_REFRESH_HOUR + APP_TIMEZONE 推导为 (cutoff(D-1), cutoff(D)]
- Scheduler：进程内 APScheduler（AsyncIOScheduler）+ FastAPI lifespan，默认每天 08:00（APP_TIMEZONE）执行 refresh_all()
- RefreshRun：refresh_runs 表记录 manual / scheduled / startup_catchup 的执行状态，只存简短错误
- Startup catch-up：启动时若已过计划时间且今天没有成功刷新，则后台补跑一次，不阻塞启动
- Refresh status：GET /api/v1/refresh/status 返回 scheduler 状态、最近一次执行与下次执行时间
- System status：GET /api/v1/system/status 返回 status / database / scheduler_enabled / 最近刷新结果，不包含任何 Secret
- 本地部署：uvicorn --host 0.0.0.0 --port 8000，单 worker（进程内 Scheduler 不允许 --workers > 1）
- 启动脚本：scripts/start_backend.ps1（打印局域网 URL，日志写 logs/backend-YYYYMMDD.log）
- 开机自启动：scripts/install_startup_task.ps1 注册登录触发的计划任务 "AI Daily Backend"（无需管理员权限，可重复执行）；scripts/uninstall_startup_task.ps1 删除
- 备份：scripts/backup_db.ps1 复制到 backups/ai_daily_YYYYMMDD_HHMMSS.db，默认保留 14 份
- Mobile Backend URL：AsyncStorage 保存值 > EXPO_PUBLIC_API_BASE_URL > http://127.0.0.1:8000；设置页可测试连接（GET /health）
- 网络失败可见：请求 12s 超时，UI 显示「无法连接 AI Daily 服务」+ 重新加载，不会卡在加载中
- Android：release APK 通过 expo-build-properties 开启 android.usesCleartextTraffic，用于局域网 HTTP
- LLM 使用环境变量配置，失败回退原文，结果缓存到 backend/.cache
- uv + CPython 3.11

Push（产品决策，不是缺陷）:
- User opted out of system push notifications.
- Push code remains disabled and is not part of the current product path.
- 当前流程是：用户主动打开 App -> 拉取最新日报，不依赖任何系统通知。
- PUSH_ENABLED=false 时不会请求 Firebase / Expo Push，不会注册 Token，不影响 App 启动、Scheduler 与日报生成。
- Backend Push 代码（push_devices 表、/api/v1/push/*）保留但 dormant，便于将来恢复。
- Mobile 推送客户端已完全移除（含启动时的 registerForDailyDigest 调用）；App 不再申请通知权限、不再获取 Push Token。
- 已移除的构建依赖：expo-notifications、expo-device、googleServicesFile、expo-notifications 插件配置。
- 验收不再要求 Firebase / FCM / ExpoPushToken / google-services.json。

Next:
Phase 11 - 待定（云端部署 / HTTPS、内容质量迭代）

Not in scope（产品设计问题，与本阶段 bug 修复无关，明确未实现）:
- 48h multi-date archive / previous-day automatic backfill / 跨多日报自动 merge
- 未修改 scheduler 时间语义，未修改 Today 页语义

Not in scope（Phase 10.2）:
- 未引入 first_seen_at
- 未改 Scheduler 每天 08:00 的语义，未改 Mobile，未启用 Push，未做云部署

Known Issues:
- 无语义级事件聚类
- 历史 future-timestamp bug 造成的污染需要手动跑一次 rebuild_digests 修复（不会自动 backfill）
- Phase 10.2 之前写入的日报没有 window_start / window_end，首次 rebuild 会按配置 cutoff 推导；若这些日报当时并非在 cutoff 时刻生成，推导窗口只是近似
- GitHub 强关键词列表仍需按实际误报迭代
- 未配置 GITHUB_TOKEN 时 REST metadata 易被匿名 rate limit 限制，此时自动使用 strict fallback
- Scheduler 为进程内实现，仅支持单 worker；多 worker / 云部署需要外部 Scheduler
- 计划失败后仅自动重试一次（15 分钟后），仍失败则等下一次正常调度
- 本地部署阶段使用 HTTP，尚未启用 HTTPS
- 手机端没有离线数据库，Backend 不可达时只能显示错误与重试
- 数据库 schema 变更依赖 create_all() + 轻量 ADD COLUMN 补列，仍无迁移框架
- 收藏为单用户模型，没有登录与多设备同步
- 开发环境 CORS 允许所有来源，仅限 development
