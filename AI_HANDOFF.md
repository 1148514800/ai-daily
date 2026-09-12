# AI_HANDOFF.md

Current Phase: Phase 7

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

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- RSS -> Collector -> 24h filter -> rule dedup -> LLM enrich -> SQLite
- GitHub Trending HTML -> AI filter (strong/weak + strict fallback) -> GitHub REST metadata -> optional LLM enrich -> SQLite
- Database -> API -> Mobile：数据库是唯一 source of truth，API 读取全部来自 SQLite
- SQLAlchemy 2.x + SQLite（backend/data/ai_daily.db），表结构由 metadata.create_all() 初始化，暂不引入 Alembic
- 日报日期按 APP_TIMEZONE（默认 Asia/Shanghai）计算，采集时间仍保存 UTC
- LLM 使用环境变量配置，失败回退原文，结果缓存到 backend/.cache
- uv + CPython 3.11

Next:
Phase 8 - 定时刷新（scheduling）

Known Issues:
- 无语义级事件聚类
- GitHub 强关键词列表仍需按实际误报迭代
- 未配置 GITHUB_TOKEN 时 REST metadata 易被匿名 rate limit 限制，此时自动使用 strict fallback
- 无定时刷新，仅启动时抓取一次
- 收藏为单用户模型，没有登录与多设备同步
- 数据库 schema 变更依赖 create_all()，尚无迁移机制
- 开发环境 CORS 允许所有来源，仅限 development
