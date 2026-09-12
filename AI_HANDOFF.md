# AI_HANDOFF.md

Current Phase: Phase 6

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

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- RSS -> Collector -> 24h filter -> rule dedup -> LLM enrich -> DigestStore
- GitHub Trending HTML -> AI filter -> GitHub REST metadata -> optional LLM enrich -> GitHubStore
- LLM 使用环境变量配置，失败回退原文，结果缓存到 backend/.cache
- uv + CPython 3.11

Next:
Phase 7 - 定时刷新或收藏持久化

Known Issues:
- 无语义级事件聚类
- 收藏未持久化
- 无定时刷新，仅启动时抓取一次
- 开发环境 CORS 允许所有来源，仅限 development
