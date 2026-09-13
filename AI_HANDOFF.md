# AI_HANDOFF.md

Current Phase: Phase 10.7 - Daily Home Experience

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
- 原始正文提取：统一提取 pipeline（RSS 全文 → 网页正文 → RSS 摘要），保留原语言，正文与 LLM 输入分离（Phase 10.5）
- LLM Grounded Summary：prompt 明确禁止补充正文之外的事实，PROMPT_VERSION 升到 v2（Phase 10.5）
- Article Detail API + Mobile 新闻详情页：详情页展示原语言正文，不翻译（Phase 10.5）
- 历史文章正文 backfill 一次性命令（Phase 10.5）
- 日报排序：新增确定性 ranking 模块，按 importance / source / recency / content / cluster 计算 0-100 rank_score（Phase 10.6）
- Top Stories：rank 前的新闻标记 is_top_story，非 Top 新闻仍然全部保留并关联到日报（Phase 10.6）
- 内容多样性：topic（10 类）与 company 的确定性识别 + soft diversity penalty，避免同一公司 / 同一 topic 霸榜（Phase 10.6）
- 日报首页：Mobile 按 rank 分出「今日必看（1~3）/ 重点新闻（4~10）/ 更多动态（11+）」三层，并加日报概览与 GitHub 区块（Phase 10.7）
- topic 中文标签与人类友好时间：API 返回 topic / company，客户端只做映射；相对时间只在当前日报使用，历史日报一律绝对时间（Phase 10.7）

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- 来源 -> Collector（RSS 或官方页面 HTML）-> issue window filter（window_start < published_at <= window_end，未来时间自然被剔除）-> rule dedup -> article extraction -> LLM enrich -> SQLite -> event dedup -> ranking -> daily_digest_news
- 两层内容：列表只有中文标题 / 摘要 / Why it matters / importance_score（NewsItem，正文字段 exclude），详情额外返回原始正文（NewsDetail）
- 正文提取（app/services/article_extractor.py）：所有来源共用一套 pipeline，不做 11 个 parser
- 正文来源优先级：RSS/Atom 自带完整正文（content:encoded / Atom content，长度 >= rss_full_min_chars）-> 抓取文章网页并清洗 -> RSS description / summary 兜底
- 正文清洗：保留 paragraph / heading / list / quote（带轻量标记），过滤 navbar / footer / cookie / 相关推荐 / 分享 / 广告 / script / style / 菜单 / 侧边栏 / 分页 / 标签 / 作者卡片
- 干扰判断只看标签名、class、id、role，不看正文文字（正文提到 cookie 不会误删）；class/id 按整词匹配，避免 `nav` 命中 `navigation-with-keyboard`
- 正文容器在移除干扰元素后取文本最多的候选，避免选中页面里的相关推荐小 <article> 卡片
- 正文语言：content_original 永远保持原语言，绝不翻译/改写；title_cn / summary / why_it_matters / importance_score 是另一组独立字段
- 数据库保存完整正文 content_original；送给 LLM 的只是按 LLM_CONTENT_MAX_CHARS（默认 6000）裁剪的视图，上限集中在 app/services/llm/settings.py
- 正文缓存以 canonical URL 为 key（backend/.cache/articles，可用 ARTICLE_CACHE_DIR 覆盖）；只缓存成功结果，失败会在下次 refresh 重试
- 网络容错：timeout / User-Agent / redirect 上限，非 2xx、非 HTML、空正文都回退 RSS 摘要，单篇异常隔离，一个页面失败不会让 refresh 失败
- Grounded summary：prompt 只允许使用正文事实，禁止补充正文之外的事实/数字/人名，禁止根据模型记忆猜测；正文可以是英文但输出必须是中文
- LLM 调用输入变化（v2）：body + title + source + published_at；PROMPT_VERSION 升为 v2，缓存 key 用 content（无正文时用 summary），prompt 变化会自然失效旧缓存
- GET /api/v1/news/{news_id} 扩展为 NewsDetail（原字段全部保留，向后兼容）；/daily、/daily/{date}、/favorites 仍不返回正文，避免列表下发全文
- Mobile NewsDetailScreen 追加「原文内容」区块（分隔线 + 原文内容 · 英文原文 + 原始标题 + 原语言正文），渲染拆分在 mobile/lib/articleBody.ts（纯函数、可单测）；不提供自动翻译全文
- 历史正文 backfill：uv run python -m app.jobs.backfill_article_content（--limit / --date），可中断、可重复、已提取跳过、单篇失败继续，不重建日报、不改 digest 关联
- 可观察性：refresh 打印 Article extraction 汇总（Candidates / RSS full content / Web extracted / RSS fallback / Failed / Cache hit）；AI_DAILY_DEBUG_EXTRACTION=1 打印每篇 method 与字符数，绝不打印正文
- 排序（app/services/news_ranker.py）：确定性 ranking，rank_score = importance*0.60 + source*0.14 + recency*0.10 + content*0.06 + cluster*0.10，再乘 100；不让 LLM 决定顺序，LLM 只提供 importance_score
- 多样性重排：先按 rank_score 排序，再从头贪心选择，与前文重复 company / topic / source 时扣 soft penalty（company 3.0 / topic 2.0 / source 1.0，单条封顶 8.0），是软约束而非硬配额
- topic 与 company 识别（app/services/news_topics.py）：确定性关键词规则，无 embeddings / NER；topic 10 类（model_release / agent / research / open_source / product / developer_tools / hardware / business / policy / other），company 命中 OpenAI / Anthropic / Google DeepMind / Meta / NVIDIA / DeepSeek / Alibaba Qwen / Moonshot Kimi / Hugging Face 等；英文关键词按整词匹配
- Top Stories：TOP_STORY_LIMIT 默认 10（环境变量可覆盖），daily_digest_news 增加 rank / rank_score，is_top_story 读取时按当前 limit 计算；非 Top 新闻仍然全部保留并关联，只是标记为 false
- 排序顺序在整份日报上单调不增（贪心覆盖全列表），因此 rank_score 可以与顺序一一对应
- 可观察性：refresh 打印 Ranking 汇总（Candidates / Top stories / Topics / Companies）；AI_DAILY_DEBUG_RANKING=1 打印每条新闻的分数构成
- 日报首页（Mobile）：DigestView 分三层渲染 —— 今日必看（rank 1~3，大标题 + 最多 3 行摘要 + 强调左边框）、重点新闻（rank 4~10）、更多动态（rank 11+）；分组与概览统计都在 mobile/lib/digestSections.ts（纯函数）
- MUST_READ_LIMIT = 3 是阅读体验常量，与后端 TOP_STORY_LIMIT = 10 解耦；客户端只读取 rank / is_top_story / topic，不重新排序或打分
- 日报概览在客户端由 payload 现算：总数 / 重点条数 / 来源去重 / topic 去重（忽略空 source 与 other），不新增 LLM 调用或接口请求
- topic 中文标签集中在 mobile/lib/topics.ts（model_release → 模型 等 10 项，other 不显示）；API 返回 topic / company，后端复用 news_topics 的同一套标签，不重新实现分类
- 人类友好时间集中在 mobile/lib/relativeTime.ts：按 APP_TIMEZONE 换算，< 1 分钟「刚刚」、< 1 小时分钟、< 6 小时小时、同一天「今天 HH:MM」、前一天「昨天 HH:MM」、更早「M月D日 HH:MM」
- 相对时间只在「当前日报」使用：digest.date != 今天时直接给绝对时间，因此打开历史日报不会把旧新闻显示成「刚刚」；无法解析的时间返回空字符串
- 空 section 不渲染：今日必看不足 3 条只显示实际条数，没有更多动态 / 没有 GitHub 项目时不显示对应标题
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

Not in scope（Phase 10.7）:
- 未改 ranking 算法、采集、event dedup、正文提取：本阶段只重排展示与标签
- 未引入新新闻源、LLM 日报总结、搜索、登录、个性化推荐、embeddings / RAG、全文翻译、云部署、图片抓取、动画
- 未新增第二套评分：Mobile 只信任后端 rank / rank_score / is_top_story / topic，Top 3 只是视觉层级
- 未把 topic 存进数据库：topic / company 仍由 news_topics 的纯函数按需计算，规则变更后历史文章一起生效
- 未改 Scheduler / issue window / Push / 本地部署 / 数据库 schema

Not in scope（Phase 10.6）:
- 未引入 embeddings / 向量数据库 / RAG / 语义搜索 / 推荐系统 / 用户画像 / Agent
- 未新增新闻源，未做全文翻译、云部署、HTTPS、Push
- 未让 LLM 参与排序：LLM 只提供 importance_score，最终顺序是确定性计算
- 未删除任何排名靠后的新闻：diversity penalty 是 soft penalty，非 Top 新闻仍然全部保存在 news_articles 并关联到日报
- 未引入 Alembic；rank / rank_score 走既有 ALTER TABLE ADD COLUMN 补列
- 未改 Scheduler 每天 08:00 语义，未改 issue window，未重新设计 Mobile

Not in scope（Phase 10.5）:
- 未做全文自动翻译、embeddings、向量数据库、RAG、语义搜索、Agent
- 未新增新闻源，未做用户系统、云部署、HTTPS、Mobile 大规模重设计
- 未改 Scheduler 每天 08:00 语义，未改 issue window，未改 Phase 10.4 阈值或重新设计 event dedup
- 未引入 Alembic（正文字段走既有 create_all + ALTER TABLE ADD COLUMN 补列）
- 未在启动时抓取全部历史正文，只提供可选的一次性 backfill 命令

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
- 真机（Android APK）验收未在本环境执行：当前机器没有 Android SDK（ANDROID_HOME / adb 均缺失），也没有连接的设备，只能完成 tsc + 单元测试 + 真实 API payload 验证
- 时间显示按 APP_TIMEZONE 固定 +08:00 偏移换算，因此设备时区不影响结果；若以后把 APP_TIMEZONE 改为有夏令时的时区，需要改成真正的时区换算
- topic / company 继承 Phase 10.6 的规则局限：一条新闻同时提到多家公司只记第一家；分类失败不显示标签（回退 category）
- Top 3 是固定的 3 条：当天如果只有 1~2 条新闻，今日必看就只有 1~2 条，不做补齐
- ranking 是启发式的：importance_score 由 LLM 给出，模型偏差会直接体现在顺序上；权重是保守的初始值，可能需要按真实日报继续校准
- topic / company 是关键词规则，一条同时提到多家公司的新闻只记第一家（COMPANY_RULES 顺序）；分类失败落到 other / 空，只影响 diversity，不影响是否保留
- diversity 是 soft penalty：真实数据里某个来源一天发很多条时，仍然可能占据较多 Top Stories 位置，penalty 只保证不会无脑霸榜
- rank 只对当前日报有意义：收藏与单独读取新闻不返回 rank；同一新闻在不同日报中的排名可能不同
- 历史日报不会自动重新排序，需要手动跑一次 rebuild_digests 才会写入 rank / rank_score
- OpenAI 官网对非浏览器请求返回 403，该来源正文会退回 RSS summary（其余 10 个来源可正常提取正文）
- 正文提取是启发式规则而非通用阅读器，个别站点改版或反爬变化时会退回 RSS summary，并在 content_extraction_method 与日志中标明
- content_language 只做脚本判定（中/英/日/韩/俄），不做统计语言识别
- 正文按规范化纯文本 + 轻量标记保存，不保留原始 HTML 结构与图片
- 正文提取以 canonical URL 缓存，URL 变化（例如站点改路径）会重新抓取一次
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
