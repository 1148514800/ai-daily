# AI_HANDOFF.md

Current Phase: Phase 10.12 - Rich Summary + Mobile Reading Experience Optimization

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
- 历史日报与日期导航：新增「历史」入口与列表（只显示真实存在的日报），看某天日报时可在**真实日报**之间前后切换，API /digests 补充 top_story_count 与 window（Phase 10.8）
- digest 客户端内存 cache（date -> DailyDigest，仅进程内），9-13 → 9-12 → 9-13 往返不再重复请求；后端 SQLite 仍是唯一 source of truth（Phase 10.8）
- 全局新闻搜索：SQLite FTS5（优先 trigram）全文索引覆盖全部已收录新闻，标题 / 中文摘要 / 英文原文 / source / company / topic 都可搜（Phase 10.9）
- 搜索后端启动时探测，FTS5 不可用自动退化为 SQL LIKE；搜索不可用绝不会导致 Backend 启动失败（Phase 10.9）
- 环境隔离与维护命令安全：新增 APP_ENV（development / test / production），集中配置；pytest 固定为 test（Phase 10.10）
- 维护命令共享 production guard：`--database-url` / `--dry-run` / `--allow-production`，默认拒绝写默认正式数据库（Phase 10.10）
- 正式库写入前固定 validate -> backup -> execute，备份失败立即中止；备份为 `backups/pre_<command>_YYYYMMDD_HHMMSS.db`（Phase 10.10）
- 新增只读诊断命令 inspect_database 与 release_check，完全不写数据库、不创建 schema、不创建 FTS（Phase 10.10）
- 新增发布前脚本 scripts/check_backend.ps1 与 scripts/check_mobile.ps1（Phase 10.10）
- 来源质量升级：删除量子位（qbitai），新增 Mistral AI / Cohere / Microsoft Research / Cursor / Ars Technica，共 15 个来源（11 official + 2 research + 2 media）（Phase 10.11）
- source_type 统一为 official / research / media：Hugging Face 由 blog 改为 research；GitHub Trending 仍不是 NewsSource（Phase 10.11）
- Ars Technica 是全站 AI 分类 Feed，进入 pipeline 前先做确定性 AI 相关性过滤（app/pipelines/ai_filter.py），要求证据来自不同关键词家族（Phase 10.11）
- 正文清洗升级：扩展噪声词表、来源专用 selector（cohere / cursor / anthropic / deepseek / kimi）、重复块去重（Phase 10.11）
- 正文质量检测（app/services/article_quality.py）：确定性规则判 good / low / fallback，网页正文质量低自动回退 RSS summary（Phase 10.11）
- 两层正文：news_articles 新增 content_raw（诊断用，不对外返回），content_original 是清洗后给 App 展示的正文（Phase 10.11）
- 正文按需加载：详情 API 不再返回正文，新增 GET /api/v1/news/{news_id}/content；Mobile 点击「查看原文内容」才请求（Phase 10.11）
- 日报首页减法：删除「今日必看」三层结构（改回重点新闻 / 更多动态两段），删除今日首页的历史日报与搜索入口（Phase 10.11）
- Source Health：refresh 打印按来源对齐的成功 / 失败 / 条数 / 错误类型表（app/services/source_health.py）（Phase 10.11）
- LLM 摘要结构升级：新增 key_points（3~5 条中文要点），summary 扩到 150~300 字、why_it_matters 扩到 100~200 字，PROMPT_VERSION 升到 v3（Phase 10.12）
- news_articles 新增 key_points_json（JSON 数组字符串）；旧行 NULL 读回 []，非字符串 / 损坏值丢弃，不做 destructive migration（Phase 10.12）
- 删除用户端原文阅读功能：Mobile 不再调用 GET /api/v1/news/{id}/content，删除「查看原文内容」按钮 / 原文区域 / 正文 loading 状态 / newsContent reducer / articleBody 渲染（Phase 10.12）
- 详情页改为 AI 解读页：发生了什么？/ 核心信息 / 为什么重要？/ 查看来源，只发一个请求（GET /api/v1/news/{id}）（Phase 10.12）
- 首页删除后台状态信息（「最后更新」与「每天 08:00 自动刷新」），改到设置页「系统状态」区块，复用 GET /api/v1/refresh/status，未新增接口（Phase 10.12）
- 返回列表保持滚动位置：mobile/lib/scrollMemory.ts（按 key 记录 offset）+ hooks/useScrollRestoration.ts，today 与每天的历史日报各记一份（Phase 10.12）
- 返回首页不再闪 loading：mobile/lib/todayCache.ts（单个 slot 保存当天日报 + 记录「哪一天已经问过」）+ hooks/useTodayDigest.ts；今日首页命中缓存时直接进 success，不发请求也不出现「正在加载今日资讯...」，TodayScreen 除替换 hook 外未改 UI（Phase 10.12）
- 今日缓存只在缓存日期过期（App 跨过午夜）时才后台静默刷新：刷新失败继续展示缓存、不显示错误页；刷新成功后自动替换为新日报；未缓存（首次启动）仍正常显示 loading，失败仍显示错误 + 重试（Phase 10.12）

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- 来源配置（app/config/sources.py）：15 个来源，`source_type` 只有 official / research / media 三种，priority 只在同一 type 内排序（official 10~30 / research 60~70 / media 120~130）；`requires_ai_filter` 标记需要在进入 pipeline 前做 AI 相关性过滤的来源
- 来源 -> Collector（RSS 或官方页面 HTML）-> optional AI filter -> issue window filter（window_start < published_at <= window_end，未来时间自然被剔除）-> rule dedup -> article extraction -> LLM enrich -> SQLite -> event dedup -> ranking -> daily_digest_news
- 来源 UI 只有一层：Mobile 按后端返回的 `source_type` 渲染 官方 / 研究 / 媒体 badge，不按来源名称猜类型，也不按类型重新分组（保证 ranking 阅读体验不变）
- 两层内容：列表只有中文标题 / 摘要 / key_points / Why it matters / importance_score（NewsItem，正文字段 exclude）；详情（NewsDetail）也不含正文，只给 `has_content` / `content_language` / `content_extraction_method` / `content_quality`
- 正文接口保留但用户端不再调用：正文仍能从 `GET /api/v1/news/{news_id}/content`（NewsContent：news_id / content_original / content_language / content_extraction_method / content_quality）取出，语义未变（文章不存在 404，文章存在但没有正文返回 200 + 空正文）；Phase 10.12 只是 Mobile 不再请求它
- 正文提取（app/services/article_extractor.py）：所有来源共用一套 pipeline，不做 15 个 parser
- 正文来源优先级：RSS/Atom 自带完整正文（content:encoded / Atom content，长度 >= rss_full_min_chars）-> 抓取文章网页并清洗 -> RSS description / summary 兜底
- 正文清洗：保留 paragraph / heading / list / quote / code / table（带轻量标记），过滤 script / style / nav / footer / aside / form / iframe / noscript / button，以及按 class / id / role 命中的 nav / cookie / consent / banner / share / social / related / recommended / relevant（相关推荐模块）/ newsletter / subscribe / sign-in / login / ad / sidebar / author-card / comments / pagination / tags / affiliate / disclaimer（站点声明块）等噪声
- 干扰判断只看标签名、class、id、role，不看正文文字（正文提到 cookie 不会误删）；class/id 按整词匹配，避免 `nav` 命中 `navigation-with-keyboard`
- 正文容器在移除干扰元素后取文本最多的候选，避免选中页面里的相关推荐小 <article> 卡片；来源专用 selector（cohere / cursor / anthropic / deepseek / kimi）优先于通用提取
- 文本后处理包含重复段落 / 重复标题去重（_drop_duplicate_blocks），避免站点模板把同一段打印多次
- 正文质量检测（app/services/article_quality.py）：确定性规则看 chars / paragraphs / avg_paragraph_chars / noise_ratio / duplicate_ratio / link_text_ratio，长度用有效长度（CJK 字符按 2.5 计），输出 good / low / fallback；网页正文判为 low 就回退 RSS summary，绝不把垃圾正文存成正式 content_original
- 两层正文：news_articles.content_raw 保存未完全清洗的原始候选（诊断用，任何接口都不返回），content_original 是清洗 + 质量检查后的正文；Phase 10.12 起 content_original 不再展示给用户，供搜索索引 / 重新生成摘要 / 质量评估使用；两层都走 create_all + ALTER TABLE ADD COLUMN，旧库直接可用
- 正文语言：content_original 永远保持原语言，绝不翻译/改写；title_cn / summary / key_points / why_it_matters / importance_score 是另一组独立字段
- 数据库保存完整正文 content_original；送给 LLM 的只是按 LLM_CONTENT_MAX_CHARS（默认 6000）裁剪的视图，上限集中在 app/services/llm/settings.py
- 正文缓存以 canonical URL 为 key（backend/.cache/articles，可用 ARTICLE_CACHE_DIR 覆盖）；只缓存成功结果，失败会在下次 refresh 重试
- 网络容错：timeout / User-Agent / redirect 上限，非 2xx、非 HTML、空正文都回退 RSS 摘要，单篇异常隔离，一个页面失败不会让 refresh 失败
- Grounded summary：prompt 只允许使用正文事实，禁止补充正文之外的事实/数字/人名，禁止根据模型记忆猜测；正文可以是英文但输出必须是中文
- LLM 调用输入变化（v3）：body + title + source + published_at；PROMPT_VERSION 升为 v3，缓存 key 用 content（无正文时用 summary），prompt 变化会自然失效旧缓存
- LLM 输出结构（v3）：title_cn / summary_cn（150~300 字，交代谁发布 / 发布什么 / 技术变化 / 与过去的区别 / 为什么值得关注）/ key_points（3~5 条，优先技术指标、产品能力、开源信息、发布时间、性能数据）/ why_it_matters（100~200 字）/ importance_score；prompt 明确禁止夸张宣传与营销式形容词，并禁止「改变整个 AI 行业」这类无依据判断
- key_points 兼容：ArticleEnrichment.key_points 默认 []，并把显式 null 归一化为 []；DB 存 key_points_json，旧行 NULL / 非字符串 / 损坏值读回 []，API 永远返回数组（老数据 → 空数组 → 详情页隐藏「核心信息」区块）
- key_points 清洗在 app/services/llm/enrich.py 的 clean_key_points：trim、去空、去重、保序，但不补齐条数（正文很短时给 2 条是正常结果，不是错误）
- 详情拆成两个接口：GET /api/v1/news/{news_id} 返回元数据 + 正文状态（不再返回正文），GET /api/v1/news/{news_id}/content 返回正文；/daily、/daily/{date}、/favorites、/search 都不返回正文，避免列表下发全文
- Mobile NewsDetailScreen 是 AI 解读页（Phase 10.12）：中文标题 / 原始标题 / 来源 badge · 来源 · 发布时间 · Topic / 发生了什么？（summary）/ 核心信息（key_points，无要点时整块隐藏）/ 为什么重要？（why_it_matters）/ 收藏 / 「查看来源」；**只调用 GET /api/v1/news/{news_id}**，不调用 /content，页面不出现任何全文
- 详情页时间用绝对时间（9月15日 周一 08:02）：详情可能从今天日报、历史日报或收藏进入，相对时间在历史语境下会失真
- 要点展示清洗在 mobile/lib/readingView.ts（纯函数 + 单测）：trim、去空、去重，并容忍后端返回 null 或非数组
- 已删除的 Mobile 模块：lib/newsContent.ts（正文状态机）、lib/articleBody.ts（正文渲染拆分）、components/UpdateHint.tsx（首页「最后更新」）及其测试
- 首页不再显示任何后台状态信息（最后更新时间 / 每天 08:00 自动刷新 / scheduler 状态），这些信息移到设置页「系统状态」区块，仍然只用 GET /api/v1/refresh/status，未新增接口；状态取不到时四行都显示「暂无状态信息」，区块不会消失（mobile/lib/systemStatus.ts，纯函数 + 单测）
- 列表滚动位置恢复：mobile/lib/scrollMemory.ts 按 key 记录 offset（today / digest:YYYY-MM-DD 各一份），hooks/useScrollRestoration.ts 在 mount 时用非动画 scrollTo 恢复、在 contentSizeChange 时有限次重试、在 unmount 时保存；只存内存，不跨 App 重启
- 历史正文 backfill：uv run python -m app.jobs.backfill_article_content（--limit / --date），可中断、可重复、已提取跳过、单篇失败继续，不重建日报、不改 digest 关联
- 可观察性：refresh 打印 Article extraction 汇总（Candidates / RSS full content / Web extracted / RSS fallback / Failed / Cache hit）；AI_DAILY_DEBUG_EXTRACTION=1 打印每篇 method 与字符数，绝不打印正文
- Source Health：refresh 打印按来源对齐的表（来源名 / OK-FAIL / collector 的 valid 条数或错误类型），失败时表尾追加 Failed 行；数量在 issue window 过滤**之前**统计，所以 RSS 源接近 Feed 全量、不等于当日日报条数；错误类型是分类结果（timeout / http 403 / dns / connection / redirect / empty / parse / error）而不是 traceback，consecutive_failures 只在单次运行内计数，不做持久化
- 来源失败隔离：HTML 来源各自独立解析（app/collectors/html.py），单个来源失败只影响自身，其余来源仍会生成日报
- 排序（app/services/news_ranker.py）：确定性 ranking，rank_score = importance*0.60 + source*0.14 + recency*0.10 + content*0.06 + cluster*0.10，再乘 100；不让 LLM 决定顺序，LLM 只提供 importance_score
- 多样性重排：先按 rank_score 排序，再从头贪心选择，与前文重复 company / topic / source 时扣 soft penalty（company 3.0 / topic 2.0 / source 1.0，单条封顶 8.0），是软约束而非硬配额
- topic 与 company 识别（app/services/news_topics.py）：确定性关键词规则，无 embeddings / NER；topic 10 类（model_release / agent / research / open_source / product / developer_tools / hardware / business / policy / other），company 命中 OpenAI / Anthropic / Google DeepMind / Meta / NVIDIA / DeepSeek / Alibaba Qwen / Moonshot Kimi / Hugging Face 等；英文关键词按整词匹配
- Top Stories：TOP_STORY_LIMIT 默认 10（环境变量可覆盖），daily_digest_news 增加 rank / rank_score，is_top_story 读取时按当前 limit 计算；非 Top 新闻仍然全部保留并关联，只是标记为 false
- 排序顺序在整份日报上单调不增（贪心覆盖全列表），因此 rank_score 可以与顺序一一对应
- 可观察性：refresh 打印 Ranking 汇总（Candidates / Top stories / Topics / Companies）；AI_DAILY_DEBUG_RANKING=1 打印每条新闻的分数构成
- 日报首页（Mobile）：DigestView 只分两段 —— 重点新闻（is_top_story = true）、更多动态（其余），顺序就是后端 rank 顺序；分组与概览统计都在 mobile/lib/digestSections.ts（纯函数）
- 「今日必看」与其 MUST_READ_LIMIT = 3 已在 Phase 10.11 删除：同一份 ranking 之前被展示两次，且「第 3 条」这条界带没有依据；is_top_story / rank / rank_score 后端能力全部保留
- 来源类型 badge：mobile/lib/sourceType.ts 把官方返回的 source_type 映射为 官方 / 研究 / 媒体，未知值不显示 badge 而不是显示错误标签
- 今日首页不再提供「历史日报 →」与「搜索历史新闻」入口（Phase 10.11 删除）；两个能力仍在：历史 Tab（含搜索入口）与 /api/v1/digests、/api/v1/search 后端接口都保留
- 日报概览在客户端由 payload 现算：总数 / 重点条数 / 来源去重 / topic 去重（忽略空 source 与 other），不新增 LLM 调用或接口请求
- topic 中文标签集中在 mobile/lib/topics.ts（model_release → 模型 等 10 项，other 不显示）；API 返回 topic / company，后端复用 news_topics 的同一套标签，不重新实现分类
- 人类友好时间集中在 mobile/lib/relativeTime.ts：按 APP_TIMEZONE 换算，< 1 分钟「刚刚」、< 1 小时分钟、< 6 小时小时、同一天「今天 HH:MM」、前一天「昨天 HH:MM」、更早「M月D日 HH:MM」
- 相对时间只在「当前日报」使用：digest.date != 今天时直接给绝对时间，因此打开历史日报不会把旧新闻显示成「刚刚」；无法解析的时间返回空字符串
- 空 section 不渲染：没有更多动态 / 没有 GitHub 项目时不显示对应标题
- 历史日报由 GET /api/v1/digests（列表）+ GET /api/v1/daily/{date}（单日）提供；列表只返回 date / title / news_count / github_count / top_story_count / window，**不返回任何新闻正文**
- top_story_count 与 get_news 使用同一个 TOP_STORY_LIMIT，所以列表说多少条重点，点进去就是多少条
- 日期导航在「真实日报列表」上前后移动（mobile/lib/digestHistory.ts 的纯函数 findNeighbours），不是 date ± 1 day：数据库缺哪天就跳过哪天，绝不打开不存在的日期
- Today 复用 GET /api/v1/daily 既有的「有今天用今天、没有用最新一份」语义，客户端只决定标题（今日 / YYYY年M月D日）与是否展示 fallback 提示，不伪造今天日报
- 历史日报是 snapshot：只读 SQLite，不触发采集 / LLM，GitHub 也取当天保存的那批
- 客户端 cache（mobile/lib/digestCache.ts）只在内存里，key 为 date，命中不发请求；失败结果不缓存，后端 SQLite 仍是唯一 source of truth
- 搜索索引（app/services/news_search.py）：独立 FTS5 表 news_search_fts，字段 news_id(UNINDEXED) / title_cn / title_original / summary / why_it_matters / content_original / source / company / topic
- 搜索后端探测顺序：fts5-trigram -> fts5(unicode61) -> LIKE；探测用独立连接建临时表，不污染调用方事务；没有 FTS5 时 search_backend() 返回 like，功能退化但不报错
- trigram 索引每三个字符，所以中文无需分词、英文可子串命中；少于 3 字符的词（模型 / AI / V4）无法用 trigram 表达，改由同一条 SQL 里的 LIKE 处理，绝不丢弃
- 查询词全部包成 FTS5 字符串字面量（内部双引号翻倍），所以 " ' - ( ) * : 等特殊字符都不会造成 SQL error 或 500
- LIKE fallback 会把 % 与 _ 转义为字面量（ESCAPE），并照样在 SQL 里完成，不做 Python 全表扫描
- 排序只用 BM25（标题权重最高）+ 发布时间兜底，不复用 news_ranker，也不看 importance_score
- snippet 围绕命中词截取（优先含词的 summary，其次正文），最多 200 字符，纯文本；没有命中词的候选会被跳过
- 索引用 news_id 替换而不是追加；写入发生在 upsert_many / set_content 的同一个事务里，回滚不留脏索引
- 已有库第一次启用时由启动流程补建索引（app/main.py -> ensure_index）；init_db 只建表不填充，保持打开数据库的开销很小
- rebuild 命令：uv run python -m app.jobs.rebuild_search_index（幂等，只读 news_articles，不碰 digest 关联，不调 RSS / LLM）
- 搜索结果不返回 content_original；digest_date 取 daily_digest_news 关联，未进日报的文章为 null
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
- 主新闻优先级：官方一手源（official）> 研究实验室（research，Hugging Face / Microsoft Research）> 媒体（media）；同类内依次比较 source priority、importance_score、内容完整度、更早发布时间，最后用 news_id 兜底
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

Not in scope（Phase 10.12）:
- 未删除后端正文能力：content_original / content_raw / GET /api/v1/news/{id}/content / backfill 命令全部保留，只删除了用户端入口
- 未改采集、event dedup、ranking、issue window、日报生成：本阶段只改 LLM 输出结构、详情页展示与首页/设置页的信息层级
- 未改 importance_score 语义与取值区间：它是排序输入，ranking 不在本阶段范围内
- 未接入 X / Twitter，未做任何预留实现
- 未引入 LLM 分类、embeddings、RAG、语义搜索、向量库、多 Agent
- 未做数据库迁移框架：key_points_json 走既有的 create_all + ALTER TABLE ADD COLUMN
- 未重新生成历史摘要：老文章没有 key_points 时正常显示空数组（详情页隐藏「核心信息」），需要时会重新进入 refresh 或跑 backfill
- 未新增任何接口：设置页「系统状态」复用 GET /api/v1/refresh/status
- 未做滚动位置的持久化（不写 AsyncStorage / SQLite），只存进程内存
- 首页缓存同样只存进程内存（不写磁盘、不做 stale-while-revalidate 时间窗、不引入 Redux / React Query）；刷新只发生在缓存所属日期已过期时，且失败不影响已展示内容
- 未改 Mobile Push 状态：仍然完全不发系统通知

Not in scope（Phase 10.11）:
- 未接入 X / Twitter：不接 X API / Twitter API、不抓 X 页面、不做任何预留实现
- 未重新设计 ranking / event dedup / issue window：只补齐了 source_type 改名后残留的 tier 映射（research 之前落到 unknown）
- 未改 LLM Grounded Summary 原则与 PROMPT_VERSION，未引入 LLM 分类或 LLM 正文质量判断
- 未引入 trafilatura / Playwright / Selenium：正文提取仍是 BeautifulSoup + 确定性规则
- 未做数据库迁移框架，未删除任何历史新闻（量子位旧记录保留），未做 destructive migration
- 未删除后端历史日报与全文搜索能力，也未删除对应 API；只移除了今日首页上的两个入口
- 未做 source health 数据库 Dashboard / 持久化：只有 refresh 日志
- 未新增 Push / 用户系统 / 云部署 / HTTPS / embeddings / RAG / 语义搜索

Not in scope（Phase 10.10）:
- 未新增任何产品功能：Search / Ranking / 日报 / Mobile UI 行为均未改动
- 未改 Mobile runtime（screens / components / navigation / services / types / android）：本阶段只跑测试、bundle export 与改 README 构建说明
- 未引入 PostgreSQL migration、Alembic、云部署、HTTPS、RAG、embeddings、新新闻源
- 未修改已经稳定的 API contract（/search 响应字段保持不变）
- 未安装 Android SDK，未修改系统级环境变量

Not in scope（Phase 10.7）:
- 未改 ranking 算法、采集、event dedup、正文提取：本阶段只重排展示与标签
- 未引入新新闻源、LLM 日报总结、搜索、登录、个性化推荐、embeddings / RAG、全文翻译、云部署、图片抓取、动画
- 未新增第二套评分：Mobile 只信任后端 rank / rank_score / is_top_story / topic（当时的「今日必看 rank 1~3」只是视觉层级，已在 Phase 10.11 删除）
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

Not in scope（Phase 10.8）:
- 未引入搜索 / 全文搜索 / embedding / RAG / 个性化推荐 / 登录 / 云同步
- 未新增新闻源，未调整 ranking 参数，未用 LLM 生成日报总结，未做自动历史 backfill
- 未做日历（Calendar）大组件：只有历史列表 + 前一天 / 后一天
- 未改 issue window、Scheduler 08:00、Mobile API contract、收藏、Push、本地部署
- 未改动数据库表结构（history 只是把已有 digest 读出来）

Not in scope（Phase 10.9）:
- 未引入 embedding / 向量数据库 / semantic search / RAG / AI 问答 / query rewriting / 自动翻译 query
- 未做用户画像、个性化搜索、搜索历史同步（当前页面生命周期也不保存 query）
- 未新增新闻源，未调整 ranking 参数，未做云部署
- 未改 issue window、Scheduler 08:00、Mobile API contract、收藏、Push、本地部署

Phase 10.10 安全机制:
- APP_ENV：development（默认）/ test / production，集中在 app/config/environment.py；未知值回退 development 并告警，release_check 报 FAIL
- pytest 固定 APP_ENV=test，并且在 import app 之前设置，保证全进程一致
- 测试库隔离双保险：conftest 指向 tmp_path；configure_database() / get_engine() 在 APP_ENV=test 时遇到默认正式 DB 直接抛错，测试手写 DATABASE_URL 也绕不过
- 数据库优先级：CLI --database-url > DATABASE_URL > 默认 backend/data/ai_daily.db；--database-url 也接受裸路径
- 维护命令统一 guard（app/config/maintenance.py）：rebuild_search_index / rebuild_digests / backfill_article_content，后续 rebuild / repair / migrate 类任务复用
- Production Guard：APP_ENV=production **或** 目标就是默认 ai_daily.db 任一成立即拒绝；默认 DB 是独立于环境变量的 sentinel，APP_ENV 写错也无法绕过
- 拒绝信息：Target database looks like the production/default AI Daily database. / Use --allow-production if intentional.
- 退出码：0 成功 / 2 guard 拒绝 / 3 校验或备份失败中止
- 执行顺序 validate -> backup -> execute；备份用 SQLite online backup API，Backend 运行时也能得到一致副本；备份失败立即终止，绝不写库
- 自动备份命名 backups/pre_<command>_YYYYMMDD_HHMMSS.db；副本内容一致但不保证逐字节相同（online backup API）；PostgreSQL 明确 unsupported，且因为无法备份所以对 production 的非 SQLite 目标直接中止
- dry run：--dry-run 不写业务数据、不建永久 FTS 表、不 VACUUM、不调 init_db()（不建表不加列）、不创建数据库文件、不抓网页；dry run 允许描述正式库并额外提示 real run 需要 --allow-production
- inspect_database：只读报告 Path / Size / SHA256 / Integrity / Foreign key check / Business table counts / FTS tables，不 create_all、不升级 schema、不 ensure_index、不 VACUUM、不写数据，运行前后 SHA256 不变
- release_check：只读检查 Database integrity / Foreign keys / Search backend / APP_ENV / APP_TIMEZONE / Scheduler / LLM 配置 / Required directories / Production safety，输出 PASS / WARN / FAIL，有 FAIL 退出码 1；不做 refresh、不抓 RSS、不调 LLM、不改数据库
- FTS 生命周期：只读路径（inspect_database / release_check / status）不会创建 news_search_fts*；只在 API 启动 ensure_index 与显式 rebuild_search_index 两处创建；正常写入路径 index_items 在表不存在时是 no-op
- 搜索能力探测改为只读：supported_backend 用内存库探测 tokenizer，existing_index_backend / usable_backend 只读 sqlite_master，探测不再在真实数据库上建 probe 表
- scripts/check_backend.ps1（uv run pytest + release_check）与 scripts/check_mobile.ps1（tsc --noEmit + npm test + expo export），失败时非 0 退出
- Android SDK 实际位于 F:\software\Sdk，JDK 位于 F:\software\JDK\jdk-22；ANDROID_HOME / ANDROID_SDK_ROOT / JAVA_HOME 未持久化，脚本只在自身进程内设置，不改系统环境

Known Issues:
- OpenAI 官网对非浏览器请求返回 403，该来源正文稳定退回 RSS summary；实测 15 个来源里只有这一个稳定失败（Phase 10.11）
- Cohere / Cursor / Anthropic / DeepSeek / Kimi 依赖页面结构：站点改版会让该来源的采集或正文退回 RSS summary，collector 会明确报错（source health 记为 parse），不会静默产出垃圾正文
- Ars Technica 是全站 AI 分类 Feed，AI 过滤是保守的关键词规则，可能漏掉边缘的 AI 报道
- source_type 的 tier 映射（news_ranker 权重 / event_dedup 主新闻选择）现在由测试绑定到 NEWS_SOURCE_TYPES，但两者仍是两份手写表，新增 source_type 需要同时改
- AI 相关性过滤只作用于标记了 requires_ai_filter 的来源，其他来源的过滤仍依赖各自 Feed 的分类质量
- 维护命令的 production guard 保护的是「写库命令」；直接运行 uvicorn 或 refresh 仍会按 DATABASE_URL / 默认库正常写日报（这是产品行为，不是漏网）
- --dry-run 对 backfill 只列出待处理文章，不预演抓取结果（会触发网络请求的预演没有意义）
- 备份目录默认是仓库根的 backups/，可用 AI_DAILY_BACKUP_DIR 覆盖；自动备份不会被 backup_db.ps1 的保留策略清理，长期需要手动归档
- APP_ENV 只影响 CORS、guard 与诊断输出，不改变数据库选择；数据库选择始终由 DATABASE_URL 决定

- 真机（Android APK）验收未在本环境执行：没有连接的设备。本机**已安装** Android SDK（`F:\software\Sdk`）与 JDK（`F:\software\JDK\jdk-22`），但 ANDROID_HOME / ANDROID_SDK_ROOT / JAVA_HOME 未持久化，adb 不在 PATH 上；本阶段只完成 tsc + 单元测试 + expo export + 真实 API payload 验证（Phase 10.10 修正）
- 搜索索引表由 create_all / ensure_table 管理，不在 SQLite 备份或 ALTER 补列的覆盖范围内：它随时可以用 rebuild_search_index 重建，所以不需要备份
- 少于 3 字符的查询走 LIKE，因此在大库上比 trigram MATCH 慢；当前量级（个人单用户）完全够用，若文章数上万需要改成分词或专门的前缀索引
- 搜索是词面子串匹配，不做同义词 / 词形还原：搜「发布」不会命中「推出」，搜 `release` 不会命中 `released` 之外的变形
- 多词查询是 AND 语义（所有词都要出现），没有做 OR / 短语 / 排除语法
- snippet 按第一个出现的词截取，多个命中词时只围绕最早的那个
- 搜索结果没有分页 UI：Mobile 只请求第一页（20 条），更多结果目前靠收窄关键词
- FTS5 不可用时（极旧的 Python 或未编译 FTS5 的 SQLite）搜索退化为全表 LIKE，日志会明确打印 Search backend: LIKE fallback
- digest cache 只活在 App 进程内：杀掉进程或切后端地址后第一次打开仍会请求一次，没有持久缓存，也没有跨设备的离线阅读
- 历史列表一次返回全部日期，没有分页；当前量级（个人单用户、一天一条）足够，若积累到数千天需要再加分页
- 历史日报的 GitHub 区块来自当天保存的关联；如果那天 GitHub 采集失败，历史日报里就没有 GitHub 内容（不会用今天的 Trending 补）
- 前一天 / 后一天按数据库里的真实日报跳转，因此某天漏跑时会直接跳过：这是有意行为，但用户无法从 UI 看出中间少了哪一天
- 时间显示按 APP_TIMEZONE 固定 +08:00 偏移换算，因此设备时区不影响结果；若以后把 APP_TIMEZONE 改为有夏令时的时区，需要改成真正的时区换算
- topic / company 继承 Phase 10.6 的规则局限：一条新闻同时提到多家公司只记第一家；分类失败不显示标签（回退 category）
- Top Stories 是固定的 10 条（TOP_STORY_LIMIT）：当天不足 10 条时重点新闻就只有实际条数，不做补齐；Phase 10.11 删掉的是客户端那层「今日必看」，不是这个后端能力
- ranking 是启发式的：importance_score 由 LLM 给出，模型偏差会直接体现在顺序上；权重是保守的初始值，可能需要按真实日报继续校准
- topic / company 是关键词规则，一条同时提到多家公司的新闻只记第一家（COMPANY_RULES 顺序）；分类失败落到 other / 空，只影响 diversity，不影响是否保留
- diversity 是 soft penalty：真实数据里某个来源一天发很多条时，仍然可能占据较多 Top Stories 位置，penalty 只保证不会无脑霸榜
- rank 只对当前日报有意义：收藏与单独读取新闻不返回 rank；同一新闻在不同日报中的排名可能不同
- 历史日报不会自动重新排序，需要手动跑一次 rebuild_digests 才会写入 rank / rank_score
- OpenAI 官网对非浏览器请求返回 403，该来源正文会退回 RSS summary（共 15 个来源，其余来源可正常提取正文）
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
