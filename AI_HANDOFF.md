# AI_HANDOFF.md

Current Phase: Phase 10.13 - First-party AI sources + media curation

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
- 新增 5 个国内 AI 官方一手来源（ByteDance Seed / 豆包、腾讯混元、百度文心、智谱 GLM、MiniMax），全部 source_type=official，共 20 个来源（16 official + 2 research + 2 media）；每个来源一个独立 extractor，不写"万能中国网站解析器"（Phase 10.13）
- 五个来源的采集方式各不相同：ByteDance Seed 读页面内嵌 window._ROUTER_DATA JSON；腾讯混元读官方公开 JSON 接口（POST，唯一非文档型来源，走自己的 fetch_hunyuan_listing）；百度文心是 Hugo 原生 RSS，靠新增的 NewsSource.base_url 把站内相对链接补成绝对 URL；智谱 GLM 读 RSC flight payload 的 newsItems；MiniMax 读服务端渲染的 /blog/ 卡片（Phase 10.13）
- AI 相关性过滤补入国内品牌强信号（doubao/豆包/seedance/seedream、hunyuan/混元、ernie/文心、glm/chatglm/智谱/zhipu/autoglm、minimax/hailuo/海螺）；命中的是模型/产品名而非公司名，百度/腾讯/字节不在任何词表里（Phase 10.13）
- 关键词边界从 (?![a-z0-9]) 放宽为 (?![a-z])，让 Hunyuan3D / 混元3D / GLM4 / Gemini2.5 这类带版本号的模型名能命中；前边界仍严格，said / email 不会命中 ai（Phase 10.13）
- 来源等级强化：SOURCE_TYPE_RANKS 由 {official 1.0, research 0.6, media 0.35} 改为 {official 1.0, research 0.55, media 0.15}，source_weight 由 0.14 提到 0.20（差额来自 recency 0.10→0.08、content 0.06→0.05、cluster 0.10→0.06）；跨越 official 与 media 的整档差距约 17 分，仍然只是权重不是硬排序（Phase 10.13）
- 媒体精选层（app/services/media_selection.py）：事件去重之后、最终 ranking 之前，只对 source_type=media 生效的三条规则 —— min_importance=60、max_total=5、max_per_source=2；importance_score 为 None 的媒体文章不进入日报；official / research 完全不受这三条限制（Phase 10.13）
- 媒体精选不删除任何数据：被筛掉的文章照样写入 news_articles（仍可搜索、仍可被以后的 refresh 或 rebuild 选中），只是不建立当天日报关联；历史日报不被重写，规则只影响后续 refresh（Phase 10.13）
- 阈值集中在 MediaSelectionSettings（可注入），裁剪逻辑不写在 DigestStore.persist() 内；refresh 默认只多一行 media selection 汇总，AI_DAILY_DEBUG_MEDIA_SELECTION=1 逐条打印 KEEP / DROP 与原因（Phase 10.13）
- Phase 10.14 把"一个公司 = 一个新闻源"的假设去掉：NewsSource 新增 organization / channel 两个字段，一家公司可以有多个官方渠道（Anthropic 的 newsroom / research / engineering 是同一个 organization 的三个 channel），来源总数由 20 增至 33（29 official + 2 research + 2 media）（Phase 10.14）
- NEWS_CHANNELS 定义 9 类官方渠道：news / research / product / engineering / developer / model / security / changelog / cloud；channel 与 source_type 严格分离 —— Anthropic Institute 是 organization=anthropic + channel=research + source_type=official，因为"谁发布的"决定可信等级，"发在哪个栏目"决定内容渠道（Phase 10.14）
- 新增 13 个官方渠道：anthropic-research / anthropic-engineering / cursor-changelog / cohere-research / nvidia-developer / meta-ai-blog / alibaba-model-studio / google-ai / google-gemini / google-research / google-cloud-ai / tencent-cloud-ai / tencent-workbuddy，全部 source_type=official、priority 42~58（official 档位仍在 60 的 research 之下）（Phase 10.14）
- 修复 Anthropic 漏源：newsroom extractor 不再只认 /news/，改为接受 /news/ /research/ /institute/ /engineering/，以及同域下自带发布日期的顶层文章卡片（找回 /claude-fable-and-mythos-5-1）；/category/ /tag/ /author/ /research/team/ 仍然排除（Phase 10.14）
- 修复腾讯漏源：腾讯云 AI（channel=cloud）与混元（channel=model）是两个独立渠道，WorkBuddy 单独作为 channel=product；腾讯云公告是全站运维公告，启用 requires_ai_filter 后 GLM-5v-Turbo / DeepSeek-V4-Flash 这类模型更新通知能进候选，负载均衡 / 计费等非 AI 条目被丢弃（Phase 10.14）
- HTML 采集路径补齐 AI 相关性过滤：过去 requires_ai_filter 只在 RSS 路径生效，现在 parse_html_page 走同一个 _result_from_entries，所以腾讯云 / Google Cloud AI 这类宽泛官方渠道标记后真的会被过滤（Phase 10.14）
- AI 强信号补充 AI factory / AI factories / physical AI（实测在 NVIDIA feed 上找回 3 条真实 AI 新闻、放进 0 条 GeForce NOW 游戏推广）；仍然坚持命中的是模型 / 平台词汇而不是公司名，腾讯 / 百度 / Google / NVIDIA 不在任何词表里（Phase 10.14）
- source_health 新增 EMPTY 与 UNSUPPORTED：EMPTY 表示请求成功但本次窗口没有内容，FAIL 表示 extractor / 网络 / 结构错误；"这周很安静"和"页面结构变了"不再混为一谈（Phase 10.14）
- refresh 新增 Official Source Coverage 区块：按 organization 分组、按 channel 列出 OK / EMPTY / FAIL / UNSUPPORTED 与条数，末尾一行汇总 official coverage: 33/39 channels OK, 6 unsupported（Phase 10.14）
- 明确记录 6 个没有稳定公开来源的渠道（UNSUPPORTED_CHANNELS，每条带原因）：openai/developer、bytedance/cloud、moonshot/changelog、minimax/product、baidu/cloud、zhipu/developer；火山引擎新闻列表自 2025-10-15 起未更新，因此不接入（"页面废弃"而不是"最近没更新"）（Phase 10.14）
- 同一事件多来源去重继续复用 event_dedup：official 渠道之间、official 与 media 之间同一事件只保留一条，代表条目按 official > research > media 选择（本阶段只加测试，未重写选择逻辑）（Phase 10.14）
- 不重复请求：Anthropic 只抓一个 newsroom 列表再按 path 区分 channel，Google 的 5 个 Feed 各自是独立官方 Feed 而不是同一页面的重复抓取（Phase 10.14）

Current Architecture:
- Expo + React Native + TypeScript
- FastAPI /api/v1
- 来源配置（app/config/sources.py）：33 个来源（29 official + 2 research + 2 media，另有 6 个官方渠道因无稳定来源记为 unsupported），`source_type` 只有 official / research / media 三种，priority 只在同一 type 内排序（official 10~58 / research 60~70 / media 120~130）；`organization` 表示公司归属（openai / anthropic / google / ...），`channel` 表示官方渠道类型（news / research / product / engineering / developer / model / security / changelog / cloud），两者与 `source_type` 互不替代；`requires_ai_filter` 标记需要在进入 pipeline 前做 AI 相关性过滤的来源（RSS 与 HTML 两条路径都生效）；`base_url` 只用于补全站内相对链接（Hugo Feed），不是第二个抓取地址
- 来源 -> Collector（RSS / 官方页面 HTML / 官方 JSON 接口）-> optional AI filter -> issue window filter（window_start < published_at <= window_end，未来时间自然被剔除）-> rule dedup -> article extraction -> LLM enrich -> SQLite -> event dedup -> media selection -> ranking -> daily_digest_news
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
- 每个 HTML 来源一个独立 extractor（Phase 10.13 后共 9 个：anthropic / kimi / deepseek / cohere / cursor / bytedance-seed / tencent-hunyuan / zhipu-glm / minimax）；页面结构变化时抛 PageStructureError，collector 记为 failed 并只影响该来源，绝不静默返回空列表或错误数据
- 腾讯混元是唯一"非文档型"来源：listing 是 POST-only JSON 接口，走自己的 fetch_hunyuan_listing（可被测试注入），不经过 fetch_html
- 百度文心是唯一使用 NewsSource.base_url 的来源：Hugo Feed 的 <link> 是站内相对路径（/blog/posts/x/），用 base_url 补成绝对 URL；没有 base_url 时该条目按"无法读取"跳过而不是猜一个域名
- 排序（app/services/news_ranker.py）：确定性 ranking，rank_score = importance*0.60 + source*0.20 + recency*0.08 + content*0.05 + cluster*0.06，再乘 100；不让 LLM 决定顺序，LLM 只提供 importance_score（Phase 10.13 提高 source 权重，差额取自 recency / content / cluster）
- 来源等级权重（Phase 10.13）：SOURCE_TYPE_RANKS = official 1.0 / research 0.55 / media 0.15，未知类型 0.10；跨越 official 与 media 的整档差距约 17 分，因此仍然是权重而非硬排序 —— 媒体 importance=95 仍可超过官方 importance=20（实测分界点在重要性相差 30 分处）
- 媒体精选（app/services/media_selection.py，Phase 10.13）：事件去重之后、ranking 之前，仅对 source_type=media 生效。MediaSelectionSettings(min_importance=60, max_total=5, max_per_source=2)；importance_score 为 None 的媒体文章不进入日报（fallback 分数等于没有判断）；official / research 完全不受限；候选取舍顺序 importance -> published_at（越新优先）-> news_id，结果与抓取顺序无关；输出保持调用方顺序
- 媒体精选只影响 daily_digest_news 关联，不删除 news_articles 里的任何行，也不重写历史日报；被筛掉的文章仍可被搜索、仍可被以后的 refresh 或 rebuild 选中
- 媒体精选可观察性：默认只多一行 media selection 汇总（candidates / below threshold / dropped per-source / dropped total / selected）；AI_DAILY_DEBUG_MEDIA_SELECTION=1 逐条打印 KEEP <source> | <title> | importance=NN 与 DROP <source> | <title> | reason=per_source_cap|total_cap|importance<60；refresh CLI 打印 Media selection 汇总块与 Source classes 分布
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

Verified（Phase 10.14）:
- 后端完整测试：uv run pytest -> 856 passed, 5 skipped（Phase 10.13 基线 801 passed；本阶段新增 55 个用例 + 8 个 HTML fixture）
- 新增测试文件：tests/test_phase_10_14_coverage.py —— source metadata（organization / channel / source_type 合法性、channel 不等于 source_type、同一公司多渠道同 organization）、Anthropic 多路径（/news/ /research/ /institute/ 顶层文章 + /category/ /tag/ /author/ /research/team/ 排除 + 无日期卡片跳过）、腾讯多渠道（Hunyuan 与 Cloud 独立、WorkBuddy 版本不塌缩成一条）、宽泛官方渠道 AI 过滤（非 AI 丢弃 / AI 保留 / 已收敛渠道不过滤）、organization 分组与覆盖率输出、EMPTY 与 FAIL 区分、unsupported 渠道带原因、事件去重（三渠道同一事件 -> 1 条、official 胜 media）、渠道失败隔离
- 真实 refresh（uv run python -m app.collectors.refresh，2026-09-19）：33 个来源全部请求成功，无 FAIL；Official Source Coverage 汇总为 official coverage: 33/39 channels OK, 6 unsupported
- 真实 refresh 的 organization / channel 覆盖（有效条目数）：anthropic news 13 / research 10 / engineering 24；tencent model 9 / cloud 3 / product 70；google cloud 20 / product 20+20 / research 100+100；openai news 1210；meta research 9+10；nvidia news 10 / developer 100；alibaba model 44+414；bytedance model 8；baidu model 18；zhipu news 15；minimax news 13；cohere news 22 / research 6；cursor news 12 / changelog 5；moonshot news 19；deepseek news 18；mistral news 87；huggingface research 862；microsoft research 10；techcrunch news 20；ars-technica news 13
- 真实 refresh 的漏斗：Fetched 3314 -> In window 37 -> After dedup 37 -> event dedup 后 37（Official 10 / Research 0 / Media 27）-> media selection 选中 4（淘汰 6 条 importance<60、17 条 per-source cap）-> 当天日报 14 条（official 10 / media 4）；rank 前 3 分别是 NVIDIA Developer AIPerf、Google Cloud AI 基础设施漏洞扫描、Anthropic x Accenture 嵌入式评估
- 历史窗口回归（collect_all_sources()，2026-09-09 ~ 2026-09-19）：Anthropic /institute/measuring-pace-of-ai-development（09-17）、Tencent WorkBuddy 5.5.6 / 5.5.5（09-10）、Tencent Cloud GLM-5v-Turbo 下线通知（09-17）、OpenAI astra-for-law（09-17）、Cursor changelog/projects（09-10）、Cohere building-multilingual-bridges（09-10）、阿里云百炼 happyoyster-1.0-adventure（09-17）均在窗口内被采集
- 数据安全：refresh 前后 news_articles 108 行不变（本次无新增文章写入）；未重算任何历史日报

Not in scope（Phase 10.14）:
- 未修改 Mobile：本阶段只改后端采集 / 来源配置 / 健康输出，UI、接口与缓存一行未动
- 未新增任何 API：Official Source Coverage 只是 refresh 的 stdout，覆盖率不落库、不对外暴露
- 未重写已经稳定的 extractor：Seed / 智谱 / MiniMax / Kimi / Cohere / Cursor 的解析逻辑保持原样，只补了真正漏源的渠道
- 未实现 Hot Topics / 48h 热点池：留给下一阶段
- 未调整 ranking、媒体精选阈值（60 / 5 / 2）与 Daily Digest issue window
- 未修改数据库 schema：organization / channel 只存在于来源配置与运行时报告，不新增列、不做迁移
- 未做 organization 级别的榜单多样性限制：本阶段只把 organization 贯穿到 config / health / debug，不重构 ranking
- 未引入浏览器自动化或新依赖：13 个新渠道全部复用 feedparser / BeautifulSoup / httpx
- 未接入需要登录、第三方转载、搜索结果页、微信公众号或 X / Twitter 的来源
- 未对未支持渠道做兜底抓取：UNSUPPORTED 是结论，不是待办

Verified（Phase 10.13）:
- 后端完整测试：uv run pytest -> 799 passed（Phase 10.12 基线 708 passed，本阶段新增 91 个用例）
- 新增测试文件：tests/test_phase_10_13_sources.py（5 个来源的解析 / 空列表 / 结构变化 / 无效日期 / 重复链接 + 端到端 collector）、tests/test_media_selection.py（阈值 / 总量 / 单来源上限 / 官方与研究豁免 / 与事件去重的顺序 / 持久化 / 调试输出 / settings）；tests/test_news_ranker.py 与 tests/test_ai_filter.py 补充来源等级与国内关键词用例
- 真实 refresh（uv run python -m app.collectors.refresh，2026-09-17）：20 个来源全部 OK，其中 ByteDance Seed 8 / 腾讯混元 9 / 百度文心 18 / 智谱 GLM 15 / MiniMax 13 条有效条目
- 真实 refresh 的漏斗：Fetched 2513 -> In window 38 -> After dedup 38 -> candidates 38 -> event dedup 38（无重复）-> Source classes official 16 / research 1 / media 21 -> media selection 选中 3（淘汰 5 条 importance<60，13 条 per-source cap）-> 最终日报 20 条（official 16 / research 1 / media 3）
- 真实 refresh 的前 12 名里官方占 11 条（NVIDIA / Google DeepMind / Mistral AI / Cohere / OpenAI），媒体只在第 12~16 名补盲（Anthropic 安全评估、华为芯片、苹果 AI 服务器），验证了"官方整体前移、媒体明显减少且仍能补盲"
- 数据安全验证：refresh 前后逐日对比 daily_digests 的 title / description / window 与 daily_digest_news 的 news_id 多重集，4 份历史日报全部 unchanged=True，只新增当天一份；news_articles 行数 33 -> 71（只增不删）
- 未重跑 rebuild_digests，历史日报的 rank / rank_score 保持原样

Not in scope（Phase 10.13）:
- 未修改 Mobile：本阶段只改采集 / 来源分类 / 排序 / 媒体精选，UI、接口与缓存逻辑一行未动
- 未新增任何 API：媒体精选是后端内部行为，日报接口返回的字段与语义不变
- 未删除数据库里的原始新闻：被筛掉的媒体文章仍然写入 news_articles，仍可被搜索，也仍可被以后的 refresh 或 rebuild 选中；"精选"只影响日报最终链接哪些文章
- 未重写历史日报：规则只对后续 refresh 生效，除非主动跑 rebuild_digests
- 未改动 event dedup 的代表文章选择逻辑：它本来就已经是 official > research > media（SOURCE_TYPE_RANK + priority），本阶段只为其增加了测试
- 未引入新的大型依赖：5 个新来源都用现有的 feedparser / BeautifulSoup / httpx，没有加浏览器自动化或解析框架
- 未做数据库迁移：本阶段没有新增列或表
- 未接入 X / Twitter、微信公众号、搜索引擎结果页或任何需要登录 / 代理的来源
- 未引入 LLM 分类或 LLM 媒体取舍：媒体规则是确定性的计数与阈值，不额外调用模型
- 未对 Mobile Push、Scheduler、GitHub Trending、搜索做任何改动
- 未修改既有 AI 关键词的语义：只新增国内品牌强信号，并把边界放宽到允许尾随数字

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
- Phase 10.14 的 organization / channel 是来源配置的静态属性，没有写进数据库：debug 输出与 health 报告能看到公司覆盖，但已入库的历史新闻无法按 organization 反查（需要时从 source 名称映射）
- Official Source Coverage 只在 refresh 进程中构建，不持久化：看不到"某个 channel 连续 N 天为 0"的趋势。判断"最近真没更新"还是"结构悄悄变了"目前仍靠人工对比 EMPTY 与 FAIL
- 一个公司多个 channel 时，同一事件仍可能先被两个 channel 各自采到再靠 event_dedup 合并：合并依赖标题 / URL 规则，官方渠道之间标题差异较大时可能保留两条
- 阿里云百炼模型广场一次交出 414 条（历史全量模型列表），远超其他官方渠道：这些条目都在 issue window 之外，不进入日报，但会让 Fetched 计数显著偏大
- 腾讯云公告是宽泛运维公告列表，AI 过滤是保守关键词规则：涉及模型 / 智能体的通知能进候选，但措辞里没有模型名的 AI 相关公告可能被丢弃
- Anthropic newsroom 的 extractor 接受"同域 + 自带日期"的顶层文章卡片：如果 Anthropic 以后在 /news/ 之外加入非文章页面但带日期，需要按实际链接复查
- nvidia 主 feed 启用 requires_ai_filter，而 nvidia-developer 故意不启用：实测该过滤会误删开发者博客里的真实文章（Dense vs. MoE Models、BioNeMo Inference Runtime），而开发者 feed 本身没有游戏推广需要排除
- 火山引擎（bytedance/cloud）不接入是因为新闻列表自 2025-10-15 起未更新：如果该页面恢复更新，需要重新评估并新增 extractor
- 已标记 unsupported 的 6 个渠道（openai/developer、bytedance/cloud、moonshot/changelog、minimax/product、baidu/cloud、zhipu/developer）只是"当前没有稳定公开来源"，不是永久结论
- OpenAI 官网对非浏览器请求返回 403，该来源正文稳定退回 RSS summary；实测 33 个来源的采集全部成功，只有正文抓取在这一家稳定失败（Phase 10.14）
- Phase 10.13 的 5 个国内来源都只取"首页可见的那一批"，没有实现翻页：ByteDance Seed 的 ?page= 参数实测无效（每次返回同样 8 条），腾讯混元接口虽然支持 pageNum 但只请求第 1 页（pageSize=50，当前 9 条已全量），智谱 / MiniMax / 百度文心的列表页本身不提供分页；因此首次接入之前的完整历史不会被补齐，只有列表当前可见的文章能进入日报
- 国内来源靠页面结构解析（腾讯混元是 JSON 字段）：站点改版会明确报 PageStructureError 并记为 failed，需要按新结构更新对应 extractor；这类失败不会静默降级成"今天没有新闻"
- 媒体精选的阈值 / 上限是保守的初始值（60 / 5 / 2），需要按真实日报继续校准：如果某天媒体只有 1~2 条重要新闻，上限不会补足；如果某天官方源集体失败，媒体同样不会被自动放宽
- 媒体精选只作用于后续 refresh：历史日报不受影响，也不会自动重算；如需重算必须主动跑 rebuild_digests
- 来源权重提高后，"同一天同来源多条新闻"的观感更明显：source_weight 变大后 NVIDIA 这类一天发很多条、重要度也不低的官方源会更集中地占据前半段，目前只靠 diversity 的 source_repeat_penalty=1.0 做轻微打散
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
