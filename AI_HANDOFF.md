# AI_HANDOFF.md

Current Phase: Phase 10.4 - Cross-source Event Dedup

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
- 扩展 AI 信息源：从 3 个 RSS 升级为 11 个来源（8 官方 + 1 社区博客 + 2 媒体），新增 HTML 采集器与统一 source 配置（Phase 10.3）
- 跨来源事件去重：规则去重之后新增事件级去重，同一事件的多个来源只保留一条主新闻（Phase 10.4）

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- 来源 -> Collector（RSS 或官方页面 HTML）-> issue window filter（window_start < published_at <= window_end，未来时间自然被剔除）-> rule dedup -> LLM enrich -> SQLite -> event dedup -> daily_digest_news
- GitHub Trending HTML -> AI filter (strong/weak + strict fallback) -> GitHub REST metadata -> optional LLM enrich -> SQLite
- Database -> API -> Mobile：数据库是唯一 source of truth，API 读取全部来自 SQLite
- SQLAlchemy 2.x + SQLite（backend/data/ai_daily.db），表结构由 metadata.create_all() 初始化，暂不引入 Alembic
- 日报 date 仍按 APP_TIMEZONE（默认 Asia/Shanghai）计算；published_at 与 window_start / window_end 统一保存 UTC
- 归属是 invariant：一条新闻只属于一个窗口，窗口为左开右闭 (window_start, window_end]，所以相邻日报的 news_id 交集必然为空
- 窗口推导（app/services/digest_window.py）：已存在日报沿用其 window_start 并把 window_end 前移到当前 refresh；新日报 window_start = 上一份成功日报的 window_end；第一份日报 window_start = 当前时间 - 24h
- 漏跑一天不丢内容：窗口从「上一次成功 cutoff」延续，而不是固定最近 24h
- 同日二次 refresh 是合并而非覆盖：旧链接保留在前，新链接按 news_id 去重追加，window_start 不变、window_end 前移
- 写入前有最终防线：DigestStore.persist() 在写 daily_digest_news 之前对最终 id 列表再校验一次窗口，窗口外文章仍保存在 news_articles，但不建立关联
- 跨来源事件去重（app/services/event_dedup.py）：规则去重之后的第二层，在同一 issue window 内把「同一事件的多来源报道」折叠为一条主新闻
- 事件判断不使用 embedding / 向量库 / RAG / 额外 LLM 调用，只用 title / title_cn / summary / why_it_matters / published_at 做确定性判断
- 判断顺序：先否决（两条都有时间且相差 <= 48h、版本标识不矛盾、立场词不相反），再用 Sørensen-Dice 文本相似度阈值判定
- 主新闻优先级：官方一手源 > 社区一手（Hugging Face）> 媒体；同类内依次比较 source priority、importance_score、内容完整度、更早发布时间，最后用 news_id 兜底
- 事件去重只影响 daily_digest_news；所有文章仍写入 news_articles，不物理删除重复新闻
- 事件去重运行在「该日报已链接的全部新闻」上，而不是本次采集结果，所以二次 refresh 不会重新引入已折叠的重复项
- 观察性：日志默认一行汇总（candidates / clusters / merged），AI_DAILY_DEBUG_EVENT_DEDUP=1 或 refresh CLI 的 --debug 才打印每个簇的 KEEP / MERGE 与 reason/score
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

Not in scope（Phase 10.3）:
- 未引入 embedding / LLM 事件聚类，跨来源去重仍是现有 URL / 标题规则
- 未改日报时间模型（仍为 Phase 10.2 的 issue window），未改 Mobile，未启用 Push，未做云部署
- 未接入机器之心：服务端对所有请求统一返回同一个机器人拦截页，没有可用 RSS 或文章列表

Not in scope（Phase 10.4）:
- 未引入 embedding / 向量数据库 / RAG / 额外 LLM 调用，事件去重是确定性规则
- 未改 Scheduler 每天 08:00 的语义，未改 issue window，未改 Mobile API contract，未改收藏 / GitHub Trending / Push / 本地部署
- 未引入 Alembic，未新增数据库表或列（事件去重只改 daily_digest_news 的内容）
- 未做跨日重新聚类：事件去重只在写入某份日报前运行，历史日报不自动重算

Known Issues:
- 事件去重是规则而非语义理解：换个说法的同一事件可能仍判为两条（宁可少合并，也不错误合并，错误合并会静默隐藏一条真新闻）
- 中文按字符二元组比较，对同义改写（如「发布」/「推出」）不敏感
- 同一事件跨越 48 小时的两篇报道不会合并
- 事件去重只作用于 daily_digest_news，news_articles 不做重新聚类，历史日报也不自动重算
- 机器之心当前无法稳定自动采集，尚未接入；后续若出现官方 Feed 可再评估
- Meta AI 接入的是 Meta Engineering 的 AI Research 分类 Feed，而非 ai.meta.com 的产品博客（后者没有官方 RSS，且列表页日期需从卡片上下文推断）
- Anthropic / DeepSeek / Kimi 依赖官方页面结构；页面改版时该来源会记为 failed，并在日志中明确标出，不影响其他来源
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
