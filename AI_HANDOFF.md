# AI_HANDOFF.md

Current Phase: Phase 5

Completed:
- 项目初始化
- Mobile 工程骨架
- Backend 工程骨架
- Android 静态 UI
- FastAPI mock API 与 Mobile 联调
- OpenAI / DeepMind / Hugging Face RSS
- 统一 RSS Collector、URL 标准化和规则去重
- LLM 中文标题 / 摘要 / Why it matters / importance_score
- 最近 24 小时多来源日报写入内存后通过 /api/v1/daily 提供

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- RSS sources -> RSSCollector -> RawArticle -> normalize -> 24h filter -> rule dedup -> LLM enrich -> in-memory DailyDigest
- LLM 使用环境变量配置，失败回退 RSS 原文，结果缓存到 backend/.cache
- GitHub 页面仍为 mock
- uv + CPython 3.11

Next:
Phase 6 - GitHub Trending 或定时刷新

Known Issues:
- 无语义级事件聚类
- 收藏未持久化
- 无定时刷新，仅启动时抓取一次
- 开发环境 CORS 允许所有来源，仅限 development
