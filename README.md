# ai-daily

每天一份 5～10 分钟可读完的中文 AI 日报。后续系统会自动抓取 AI 新闻、GitHub Trending 和开源项目，经过筛选、去重和 AI 摘要后，通过后端提供给 Android App 阅读。

## 当前开发阶段

Phase 10.9 - Global News Search

今日 AI 新闻来自中外官方模型厂商与 AI 媒体的公开 RSS / 官方页面；GitHub 页来自官方 Trending。LLM 中文增强可选。日报、新闻正文、GitHub 项目和收藏持久化在 SQLite 中，重启后仍然存在。后端每天固定时间自动刷新。日报按**重要度排序**，首页分为**今日必看 / 重点新闻 / 更多动态**三层，可以按日期回看**历史日报**，也可以对**全部已收录新闻做全文搜索**。

当前阶段建立了**两层内容**：日报列表只显示中文标题 / 摘要 / Why it matters，点击进入详情后可以阅读**原始语言的完整正文**。原始正文永远是原文，不会被翻译或重写；中文摘要是另一个独立字段，由 LLM 严格根据正文生成。整套系统仍在本地 Windows 电脑上长期运行，App 打开时主动拉取最新日报，**不使用系统 Push 通知**（见 "Push 状态"）。

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
- 去重分两层：先做保守规则去重（canonical URL、48 小时内完全相同标题），再做保守的事件级去重（见 "跨来源事件去重"）
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
Sources
OpenAI: X
Anthropic: X
Google DeepMind: X
...
量子位: X
Candidates: X
After dedup: X

Article extraction:
Candidates: 12
RSS full content: 3
Web extracted: 7
RSS fallback: 1
Failed: 1
Cache hit: 4

Event dedup:
Candidates: 12
Clusters: 12
Duplicates merged: 0

Ranking:
Candidates: 12
Top stories: 10
Topics: 6
Companies: 3

GitHub Trending
Fetched: X
...

Digest saved: 2026-09-13
News: 12
GitHub: 5

Database
Daily digests: 2
News total: 15
GitHub repos total: 4
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

## 日报排序 + Top Stories + 内容多样性

一次 refresh 可能有几十条候选，日报是从上往下读的，所以顺序本身就决定了第一屏值不值得看。Phase 10.6 在写入前对最终新闻做一次**确定性排序**：

```text
抓取到的新闻
      ↓
去重（规则 + 事件）
      ↓
质量评分（rank_score）
      ↓
多样性调整（soft penalty）
      ↓
稳定排序
      ↓
Top Stories
```

排序完全由 `app/services/news_ranker.py` 计算，**不让 LLM 决定最终排名**：把 30 条新闻发给模型排序既不稳定、又贵、也无法测试。LLM 只提供 `importance_score`，作为其中一个输入信号。

### rank_score 的组成

每个信号归一化到 `0..1` 后按权重加权，乘 100 得到 `0..100` 的 `rank_score`：

```text
importance   0.60   LLM importance_score（核心信号，但不是唯一信号）
source       0.14   官方一手 > 社区博客 > 科技媒体
recency      0.10   在 issue window 内的相对位置（越新越高）
content      0.06   正文完整度（web / rss_full > rss_summary fallback）
cluster      0.10   同一事件被多个来源报道时的小幅加成（有上限）
```

- `importance_score` 缺失时按中性值（35）处理，不会直接判 0，也不会因此排到最前
- 来源只是加权因素之一：来源层级差距刻意留小，媒体的大新闻仍然可以超过普通的官方新闻
- 正文长度**只是弱信号**：长度会饱和，不会出现「文章越长越重要」
- recency 只在同一窗口内比较，不会压过巨大的 importance 差距（不是「最新 = 第一名」）
- 同一事件被多个来源报道时，`cluster size` 提供很小的加成，且封顶

### topic 与 company 识别

只做确定性关键词规则，不引入 embeddings、NER 模型或 LLM 分类，规则集中在 `app/services/news_topics.py`：

```text
topic    model_release / agent / research / open_source / product /
         developer_tools / hardware / business / policy / other
company  OpenAI / Anthropic / Google DeepMind / Meta / NVIDIA /
         DeepSeek / Alibaba Qwen / Moonshot Kimi / Hugging Face / ...
```

- 规则按固定顺序求值，第一个命中者胜出；命中不了就是 `other` / 空
- 更具体的 topic 排在前面，所以 `chip export ban` 归为 policy 而不是 hardware / business
- 英文关键词按整词匹配，`meta` 不会命中 `metadata`，`api` 不会命中 `capital`
- 分类只用于 diversity penalty，错了只会让日报多样性差一点，不会丢新闻

### 多样性重排（soft penalty）

先按 `rank_score` 排序，再从头贪心选择下一条：如果候选与前文重复公司 / topic / 来源，就扣除对应 penalty。

```text
company_repeat_penalty   3.0
topic_repeat_penalty     2.0
source_repeat_penalty    1.0
max_diversity_penalty    8.0   ← 单条新闻最多被扣这么多
```

- 是 **soft penalty，不是硬限制**：不会出现「每家公司最多 1 条」，当天真有 3 条 OpenAI 大新闻时仍然可以全部进入 Top Stories
- penalty 有上限，所以最多只会让一条新闻下降约一个 importance 档位，明显更重要的新闻依然排在前面
- `other` 不算「相同 topic」：分类失败不应该把两条无关新闻互相推开
- 贪心排序覆盖整份日报（不只是 Top 10），因此 `rank_score` 从上到下单调不增
- 所有阈值集中在 `RankingSettings`，`rank_score` 的计算与调整都能被单测覆盖

### Top Stories

```text
TOP_STORY_LIMIT = 10   （可用环境变量 TOP_STORY_LIMIT 覆盖）
```

- **不删除任何新闻**：排名靠后的新闻仍然保存在数据库，并且仍然关联到日报，只是标记为 `is_top_story = false`
- `daily_digest_news` 增加 `rank` 与 `rank_score` 两列（`rank` 由 `position` 推导，`is_top_story` 读取时按当前 `TOP_STORY_LIMIT` 计算），因此调整 Top N 不需要重写历史
- `rank` 放在关联表而不是 `news_articles`：同一条新闻在不同日报里的排名可能不同
- 旧数据库通过既有的 `ALTER TABLE ADD COLUMN` 补列即可打开，不需要 Alembic

### API

`GET /api/v1/daily` 与 `GET /api/v1/daily/{date}` 的新闻顺序改为 rank 顺序，每条新闻新增：

```json
{
  "rank": 1,
  "rank_score": 71.5,
  "is_top_story": true,
  "topic": "business",
  "company": "OpenAI"
}
```

`topic` / `company` 是 Phase 10.7 的最小 API 扩展：由后端复用排序时的同一套确定性标签，客户端只做中文映射。已有字段全部保留，`GET /api/v1/news/{id}` 同样带上 topic（详情页字段仍是列表字段的超集）。收藏 / 单独读取一条新闻时不带 rank（rank 只在某一份日报里有意义），但会带 topic。

`GET /api/v1/digests` 保留原有 `date` / `title` / `news_count` / `github_count`，Phase 10.8 追加 `top_story_count` 与 `window_start` / `window_end`（向后兼容，只增不改）。它**只返回计数**，永远不带新闻正文，历史列表因此保持轻量。

Phase 10.9 新增 `GET /api/v1/search`（见 [全局新闻搜索](#全局新闻搜索phase-109)），已有接口全部保持不变。

### Mobile 显示

首页分成三层，见 [今日日报首页](#今日日报首页phase-107)。

### 可观察性

refresh 默认打印一行汇总：

```text
Ranking:
Candidates: 12
Top stories: 10
Topics: 6
Companies: 3
```

设置 `AI_DAILY_DEBUG_RANKING=1` 可以看到每条新闻的分数构成：

```bash
cd backend
AI_DAILY_DEBUG_RANKING=1 uv run python -m app.collectors.refresh
```

```text
#1 score=71.5 importance=0.9 source=0.3 recency=0.7 content=0.9 cluster=0.0 diversity=0.0 topic=business company=OpenAI
```

## 今日日报首页（Phase 10.7）

Phase 10.6 已经算好顺序。Phase 10.7 只把这份顺序做成一个「每天 5～10 分钟能读完」的首页，**不改采集、不改 event dedup、不改正文提取、不改 ranking 算法**。

```text
今日 AI 日报
2026年9月13日 星期日

今日收录 12 条 AI 动态
精选 10 条重点新闻 · 3 个来源 · 6 个话题

🔥 今日必看        Top 3
  #1 ...（大标题 + 最多 3 行摘要）
  #2 ...
  #3 ...

⭐ 重点新闻        rank 4~10
  ...

📰 更多动态        rank 11+
  ...

💻 GitHub Trending
  ...
```

### 三层分组

分组完全来自后端已经返回的字段，客户端不重新排序、不重新打分：

```text
rank 1~3     今日必看   is_top_story = true，且 rank <= 3
rank 4~10    重点新闻   is_top_story = true
rank 11+     更多动态   其余全部
```

- `is_top_story` 与 `rank` 都由后端给出，Mobile 只做切分；Top 3 的「3」是**阅读体验**上的常量（`MUST_READ_LIMIT`），与后端 `TOP_STORY_LIMIT=10` 解耦，所以调整首屏层级不需要改排序契约
- 所有新闻都会渲染：11+ 不是丢弃，只是排在后面
- 旧日报没有 `is_top_story` 时不做猜测，全部进「更多动态」，顺序保持后端返回的顺序
- 分组与统计都在 `mobile/lib/digestSections.ts`（纯函数、可单测），不堆在 Component 里
- 新闻详情页与原文阅读逻辑不变

### 日报概览

顶部数字由当前 digest 在本地算出，不新增任何 LLM 调用或接口请求：

```text
今日收录 N 条 AI 动态      ← news.length
精选 M 条重点新闻 · S 个来源 · T 个话题
                            ← is_top_story 计数 / source 去重 / topic 去重
```

- 空 source 与 `other` topic 不计入统计，否则会把「没分类」说成一种话题
- 没有来源或话题时对应片段直接省略，不显示 `0 个来源`

### topic 标签与时间

**topic**：分类仍然只发生在后端（Phase 10.6 的确定性规则），API 现在把 `topic` / `company` 一起返回（最小扩展，不重新实现分类）。客户端只做中文映射，集中维护在 `mobile/lib/topics.ts`：

```text
model_release → 模型      agent → Agent       research → 研究
open_source → 开源        product → 产品      developer_tools → 开发工具
hardware → 硬件           business → 商业     policy → 政策
other → （不显示）
```

- 每张卡片**最多一个** topic 标签；`other` 不显示，「没分类」不是读者需要的信息
- 后端没有给 topic 时回退到原来的 category 标签，不会出现英文枚举值

**时间**：`mobile/lib/relativeTime.ts` 统一处理，并且**只在「当前日报」使用相对表述**：

```text
< 1 分钟     刚刚
< 1 小时     35分钟前
< 6 小时     2小时前
同一天       今天 09:30
前一天       昨天 22:00
更早         9月10日 09:30
```

- 时间按 `APP_TIMEZONE`（Asia/Shanghai）换算，不看手机时区，所以卡片与日报日期永远一致
- 打开历史日报时不使用相对表述（digest 日期不是今天 → 直接给绝对时间），因此不会把一周前的新闻说成「刚刚」
- 时间戳缺失或不可解析时返回空字符串，卡片不显示时间而不是显示 `Invalid Date`

### 空状态与异常

- 今日必看不足 3 条：该 section 只显示实际条数（1~2 条），不补空位
- 总新闻不足 10 条：重点新闻 section 自然变短或消失
- 没有更多动态：不显示「更多动态」标题（空 section 不渲染）
- 没有 GitHub 项目：不显示 GitHub section
- 空日报：显示空状态文案（日报每天 08:00 更新）
- Backend 请求失败：显示错误文案 + 「重新加载」

## 历史日报与日期导航（Phase 10.8）

Phase 10.7 让首页值得读，Phase 10.8 解决「怎么方便地看昨天、前天」。**不改采集、不改 event dedup、不改正文提取、不改 ranking 算法，也不改 issue window**，只是把数据库里已经存在的日报按日期读出来。

### 入口

- Today 页面标题下方有一个「历史日报 →」入口，切到「历史」Tab
- 「历史」Tab 列出数据库里**真实存在**的日报，按日期倒序
- 点击任意一天进入日报页，复用 Phase 10.7 的同一套 UI（今日必看 / 重点新闻 / 更多动态 / GitHub Trending）

历史列表只显示真实存在的日报，**不会为不存在的日期生成空日报**。

### 列表内容

`GET /api/v1/digests` 只返回计数与窗口，不含新闻正文：

```json
{
  "date": "2026-09-12",
  "title": "今日 AI 日报",
  "news_count": 2,
  "github_count": 1,
  "top_story_count": 2,
  "window_start": "2026-09-11T00:00:00+00:00",
  "window_end": "2026-09-12T00:00:00+00:00"
}
```

- `top_story_count` 用与 `get_news` 相同的 `TOP_STORY_LIMIT` 推导，所以列表说「10 条重点」时，点进去一定也是 10 条
- `window_start` / `window_end` 保留在 API 里（Debug / 开发信息可用），但**默认不在 UI 展示**，普通用户看不到 `(..., ...]` 这类技术字段

### Previous / Next 规则

日期导航**不是** `date ± 1 day`，而是在**已存在的日报列表**上前后移动：

```text
09-10   09-12   09-13

查看 09-12：
  前一天 → 09-10
  后一天 → 09-13
```

因为 09-11 从来没有生成过日报，导航会直接跳过它，不会打开一个假日期。到了边界（最新 / 最早）对应的按钮变灰不可点，边界是可见的而不是静默失效。切换时是**替换**当前页面而不是压栈，所以连看 5 天不会攒出 5 层 Back。

### Today 与 latest 的关系

「今天」和「最新日报」并不是同一件事：后端每天 08:00 刷新，刷新之前当天根本没有日报。`GET /api/v1/daily` 本来就已经是「有今天 → 今天，没有 → 最新一份」。客户端只决定怎么**标注**这个结果：

- 是今天 → 标题「今日 AI 日报」
- 不是今天 → 标题「2026年9月12日 AI 日报」，并在标题下注明「今天还没有生成日报，以下是 9月12日 的日报。」

客户端**不会伪造**今天日报。历史日报不显示「今日已读完」，因为它不是今天。

### 历史 snapshot

历史日报是快照：`daily_digests` + `daily_digest_news` + `daily_digest_github` 里存的就是那一天的内容。

- 打开历史日报只读 SQLite，**不触发任何采集**（不会重新抓 RSS、不会重新跑 LLM、不会重新算 GitHub）
- 历史日报展示的 GitHub 项目是**当天保存的那批**，不是今天最新的 Trending
- 下拉/重试只是重新读数据库
- 收藏仍然基于原来的稳定 `news_id`，同一条新闻不会因为从历史日报进入就多出一份收藏

### 客户端 cache

`mobile/lib/digestCache.ts` 是一个仅存活于当前 App 进程的内存 cache，key 是 `date`：

```text
09-13 → 09-12 → 09-13   第二次打开 09-13 不发请求
```

- 命中 cache 时直接渲染，没有 loading 闪烁；未命中才走网络
- 失败的结果不写进 cache，所以「重新加载」是真的重新请求
- 只有内存，不落盘；重启 App 一律重新读后端
- **后端 SQLite 仍然是唯一 source of truth**

### 异常状态

- 没有任何日报：「暂无历史日报」
- 某日期没有日报：`GET /api/v1/daily/{date}` 404 → 「该日期没有日报。」（不是通用崩溃文案）
- Backend 不可达：沿用「无法连接 AI Daily 服务」+「重新加载」
- 日报存在但 `news = 0`：正常展示空状态，不崩溃（例如某天只抓到了 GitHub 项目）

## 全局新闻搜索（Phase 10.9）

解决「我以前看到过的那条 AI 新闻，现在怎么快速找到？」。搜索覆盖**全部已收录新闻**，不只是今天或某一份日报。不改采集、不改 event dedup、不改正文提取、不改 daily ranking、不改 issue window。

### 后端选择（FTS5 / LIKE）

搜索后端在启动时**探测**而不是假设，按能力从高到低选择：

```text
Search backend: FTS5 (trigram)
Search backend: FTS5 (unicode61)
Search backend: LIKE fallback
```

1. `fts5-trigram`：FTS5 + trigram tokenizer。索引每三个字符，所以查询就是**子串匹配**——中文不需要分词，英文也能命中单词中间片段。
2. `fts5`：FTS5 但没有 trigram。按 token 匹配，对以空格分词的语言有效；中文分词不可用，因此非 ASCII 词走 `LIKE`。
3. `like`：完全没有 FTS5。全部用 `LIKE`，但仍在 SQL 里执行，不做 Python 全表扫描。

没有 FTS5 时 **Backend 仍然能正常启动**：搜索退化为 `LIKE`，只有搜索能力降级，不影响日报、历史、详情、收藏。

### trigram 的两个真实限制

- **少于 3 个字符的词无法用 trigram 表达**（trigram 的定义如此）。`模型`、`AI`、`V4` 这类词改由同一条 SQL 里的 `LIKE` 处理，**不会**被丢掉——否则短查询会退化成「匹配全部」而不是缩小结果。
- **trigram 默认大小写不敏感**，`DeepSeek` / `deepseek` / `DEEPSEEK` 等价。

### 索引

独立 FTS 表 `news_search_fts`，字段为：

```text
news_id (UNINDEXED)  title_cn  title_original  summary
why_it_matters       content_original            source  company  topic
```

- `content_original` 是 Phase 10.5 已清洗的纯文本，索引不复制原始 HTML
- `company` / `topic` 也建索引，所以能直接搜分类；但**返回给客户端时按文章文本重新计算**，规则变更对老结果立即生效

### 索引同步

索引是派生数据，跟着写入一起更新（在同一个事务里，回滚不会留下脏索引）：

```text
news_articles  --upsert_many-->  index 更新（新新闻 / 摘要变化）
news_articles  --set_content-->  index 更新（正文 backfill 后立即能搜到）
```

- 按 `news_id` **替换**而不是追加，所以同一篇文章永远不会出现两条索引
- 已有数据库第一次启用时由启动流程自动补建，用户不需要删库重建
- 写入时若还没有 FTS 表，索引写入是 no-op，不会报错

### Rebuild 命令

```bash
cd backend
uv run python -m app.jobs.rebuild_search_index
```

```text
Search backend: FTS5 (trigram)

Search index rebuilt
Articles: 1234
Indexed: 1234
```

- 幂等，可安全重复执行
- 只读 `news_articles`，只写索引：不抓 RSS、不调 LLM、不删文章、**不修改 digest 关联**

### Search API

```text
GET /api/v1/search?q=DeepSeek&limit=20&offset=0
```

```json
{
  "query": "DeepSeek",
  "total": 12,
  "items": [
    {
      "news_id": "...",
      "title_cn": "...",
      "original_title": "...",
      "summary": "...",
      "source": "DeepSeek",
      "published_at": "2026-09-10T02:00:00+00:00",
      "digest_date": "2026-09-10",
      "topic": "model_release",
      "company": "DeepSeek",
      "snippet": "…DeepSeek 正式发布 V4.1…"
    }
  ]
}
```

- **不返回 `content_original`**：搜索可能返回几十条，列表必须轻量；正文点击后走 `GET /api/v1/news/{id}`
- `limit` 上限 50（`limit` / `offset` 由 FastAPI 校验，越界返回 422）
- 空 query 或缺少 query：返回 200 + 空结果（前端不必特判），**不会**默认吐出全部历史新闻
- `digest_date` 取 `daily_digest_news` 关联；文章还没进入任何日报（例如时间戳仍在未来的文章）时为 `null`，不伪造日期

### 搜索排序

搜索排序与 Daily Ranking 是**两套不同语义**，不复用 `news_ranker.py`：

```text
文本相关度（FTS BM25） > 发布时间（弱 tie breaker）
```

BM25 权重按列配置，标题命中明显高于正文深处命中：

```text
title_cn / title_original  10
summary                     5
source / company / topic   3~4
content_original            1
why_it_matters              2
```

`importance_score` **不参与**搜索排序：搜索结果要"和搜的词相关"，而不是重跑一次日报排序。

### Snippet

围绕命中词截取（命中词前后各取一段，最多 200 字符），优先取含命中词的 `summary`，否则取正文，并加 `…` 标明省略。没有命中词的候选会被跳过，避免给出与查询无关的开头段落；无命中时兜底给正文开头，仍返回纯文本（无 HTML、无换行）。

### Mobile 搜索页

入口在 Today 与「历史」页（不改 TabBar 结构），进入后是一个独立的搜索页：

```text
搜索 AI 新闻

[ 搜索 DeepSeek / Agent / GPT-6… ]

搜索结果 12 条

模型 | DeepSeek · 9月10日
DeepSeek 发布 V4.1
…DeepSeek 正式发布 V4.1 Flash 模型…
```

- 输入为空：显示「搜索历史 AI 新闻」，**不自动拉全部历史新闻**
- 输入过程中 300ms debounce，避免每敲一个字符发一次请求
- query 改变时旧响应不会覆盖新结果（每个请求带自己的 query，回来时如果已不是当前 query 就丢弃）
- 没有结果：「没有找到相关内容」
- Backend 失败：沿用「无法连接 AI Daily 服务」+「重新尝试」
- 点击结果进入**现有** `NewsDetailScreen`，中文摘要 / Why it matters / 原语言正文 / 查看原文 / 收藏全部照旧
- 本阶段不做搜索历史（不写 SQLite、不写 AsyncStorage）

## 数据持久化

- 当前使用 SQLite + SQLAlchemy 2.x，适合个人单用户场景
- 数据库文件：`backend/data/ai_daily.db`（`backend/data/` 已加入 `.gitignore`，不会提交）
- 连接串由环境变量 `DATABASE_URL` 控制，默认 `sqlite:///./data/ai_daily.db`
- 相对路径始终相对 `backend/` 解析，与启动时的工作目录无关；目录不存在时会自动创建
- 日报日期（`date` 主键）仍由 `APP_TIMEZONE` 计算，默认 `Asia/Shanghai`；采集时间（`published_at`）与窗口（`window_start` / `window_end`）统一以 UTC 保存
- 一条新闻只属于一个窗口：`window_start < published_at <= window_end`，同一份日报的链接不会跨窗口重复
- 本阶段不做数据库迁移系统，表结构由 `Base.metadata.create_all()` 初始化；Phase 10.2 新增的 `window_start` / `window_end`、Phase 10.5 新增的 `content_original` 等正文字段、Phase 10.6 新增的 `rank` / `rank_score` 都由轻量 `ALTER TABLE ADD COLUMN` 补列，旧数据库直接打开即可使用

存储内容：

```text
news_articles        新闻元数据 + 原始正文（稳定 ID upsert）
github_projects      GitHub 项目（repo 稳定 ID upsert）
daily_digests        每天的日报（date 主键，一天一条，含 UTC window_start / window_end）
daily_digest_news    日报与新闻的排序关系（含 position / rank / rank_score）
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

- 只读 `news_articles` 里的 `published_at`（UTC），按 issue window 重新判断归属，再重建 `daily_digest_news` 关联；重建后的顺序与正常 refresh 一致（同一套 ranking），并写回 `rank` / `rank_score`
- 窗口优先取该日报已保存的 `window_start` / `window_end`；没有保存时按 `DAILY_REFRESH_HOUR` + `APP_TIMEZONE` 推导为 `(cutoff(D-1), cutoff(D)]`，例如 08:00 Asia/Shanghai 下 2026-09-12 的窗口是 `2026-09-11T00:00Z .. 2026-09-12T00:00Z`
- 命令会把推导出的窗口写回该日报，方便下次继续沿用
- 不重新调用 RSS 或 LLM，也不删除任何 `news_articles` 原始记录
- 只重建传入日期的日报关系，其他日期不受影响；GitHub 关联保持不变
- 命令幂等，可重复执行

## 原始正文 + 中文摘要 + 新闻详情

日报列表适合快速浏览，但用户点进一条新闻后想读的是**原文**。Phase 10.5 建立两层内容：

```text
日报列表                            新闻详情
中文标题                            中文标题 / 中文摘要 / Why it matters
中文摘要              点击          来源 · 发布时间
Why it matters       ───────►       ────────────────────────
importance score                    原文内容（原始语言，不翻译）
                                    原始标题
                                    原语言完整正文
                                    ────────────────────────
                                    查看原文（系统浏览器打开 url）
```

**原始正文绝对不翻译、不改写**，中文摘要与原始正文是两套独立字段：

```text
content_original  原始正文，英文新闻保持英文，中文新闻保持中文
title_cn          中文标题        ┐
summary           中文摘要        ├ LLM 根据正文生成，绝不回写正文
why_it_matters    为什么值得关注  │
importance_score  0-100          ┘
```

### 正文提取 pipeline

`app/services/article_extractor.py` 是**所有来源共用**的一套提取逻辑（不是 11 个 parser），来源差异只体现在列表页怎么抓，这一点 `app/collectors/` 已经处理。正文来源按优先级：

```text
RSS/Atom 自带完整正文（content:encoded / Atom content，长度达标）
        ↓ 否则
抓取文章网页并清洗
        ↓ 失败则
RSS description / summary（最后兜底，文章不会丢）
```

清洗规则：保留 paragraph / heading / list / quote（heading 保留层级、列表和引用保留标记），过滤 navbar、footer、cookie 提示、推荐阅读、分享按钮、广告、script、style、菜单、侧边栏、分页、标签、作者卡片。判断只看标签名、`class`、`id` 和 `role`，不看正文文字，所以正文里提到 cookie 不会被误删；`class` / `id` 按整词匹配，避免 `nav` 命中 `navigation-with-keyboard` 这类框架类名。正文容器在移除干扰元素后取**文本最多的候选**，因为页面里的小 `<article>` 卡片常常是相关推荐而不是正文。

正文以**规范化纯文本**保存（段落之间空行，标题/列表/引用带轻量 Markdown 标记），不保存 raw HTML。

### 完整正文与 LLM 输入分离

数据库保存尽可能完整的正文；送给 LLM 的只是裁剪后的视图：

```text
完整正文
      ├── 数据库 content_original：完整保存
      │
      └── LLM 输入：按 LLM_CONTENT_MAX_CHARS 裁剪（默认 6000 字符）
```

上限集中在 `app/services/llm/settings.py`，不在调用处散落 magic number，可用环境变量覆盖：

```bash
LLM_CONTENT_MAX_CHARS=6000
```

长文不会因为 token 限制在数据库里被截断。

### Grounded summary

System prompt（`app/services/llm/prompts.py`，`PROMPT_VERSION=v2`，改了 prompt 就会让缓存失效）明确要求：

```text
只能使用正文中实际出现的信息
不得补充正文中不存在的事实、数字、日期、人名或结论
不得根据模型记忆猜测或补全
正文没有提到的内容就不要写进摘要
正文可以是英文，但输出必须是中文
```

正文提取失败时退回 RSS summary，再退回现有 fallback；LLM 失败也不会丢文章，原文本地保存并可直接展示。

### 正文 Cache

以 **canonical URL** 为 key 缓存成功提取的正文（默认 `backend/.cache/articles/`，可用 `ARTICLE_CACHE_DIR` 覆盖），第二次 refresh 直接复用，不再重复请求同一个页面。**失败结果不写入缓存**，所以一次性 403 / 超时以后仍会重试。

### 网络容错

正文抓取具备 timeout、User-Agent、redirect 上限，非 2xx / 非 HTML / 空正文都回退到 RSS summary，单篇文章异常孤立处理，不做无限 retry。**一个页面失败永远不会让整个 refresh 失败。**

### Article Detail API

扩展已有的 `GET /api/v1/news/{news_id}`（不新增重复 API）

```json
{
  "id": "rss-4aeb82da9975e2f5",
  "source": "OpenAI",
  "url": "https://openai.com/index/...",

  "title_original": "Perplexity trusts GPT-6 Astra with end-to-end systems",
  "content_original": "Perplexity is using ...",
  "content_language": "en",
  "content_extraction_method": "web",

  "title_cn": "……",
  "summary": "……",
  "why_it_matters": "……",
  "importance_score": 88,

  "published_at": "..."
}
```

原有字段全部保留，向后兼容。`content_original` 只在详情接口返回：日报/列表接口（`/daily`、`/daily/{date}`、`/favorites`）刻意不返回正文，避免一次下发十几篇全文。

### Mobile 新闻详情页

`mobile/screens/NewsDetailScreen.tsx` 在原有布局下方追加"原文内容"区块：分隔线 + `原文内容 · 英文原文` + 原始标题 + 原语言正文（渲染在 `mobile/lib/articleBody.ts`，纯函数、可单测，只做展示拆分，不改写正文）。英文正文保持英文，中文正文保持中文，**不提供"自动翻译全文"**。如果正文只拿到了 RSS 摘要，会明确提示未能抓取正文，而不是假装是全文。"查看原文"仍然用系统浏览器打开 `article.url`。

### 历史文章 backfill

不强制在启动时抓全部历史正文。新 refresh 正常抓；已经存在数据库里的历史新闻用一次性命令补：

```bash
cd backend
uv run python -m app.jobs.backfill_article_content --limit 20
uv run python -m app.jobs.backfill_article_content --date 2026-09-12
```

- 只读数据库里已有的 `news_articles`，只补正文
- 可中断、可重复运行，已成功提取的自动跳过
- 单篇失败继续处理下一篇
- **不重新生成日报、不修改 `daily_digest_news` 关联、不删除任何原始记录**

### 已知限制

- OpenAI 官网对非浏览器请求返回 403，该来源的正文会退回 RSS summary（其余 10 个来源可正常抓取正文）
- 提取是启发式规则而非通用阅读器：个别站点结构或反爬变化时会退回 RSS summary，并在 `content_extraction_method` 与日志中标明
- `content_language` 只做脚本判定（中/英/日/韩/俄），不做统计语言识别
- 正文按纯文本/轻量标记保存，不保留原始 HTML 结构与图片
- 不提供全文翻译、embeddings、向量检索、RAG 或语义搜索

## 跨来源事件去重

同一件事常被多个来源分别报道：OpenAI 官方发布一个模型，TechCrunch 报道它，量子位再转述一次。规则去重（canonical URL、48 小时内完全相同标题）看不见这种重复，日报里就会出现三条几乎一样的新闻。

`app/services/event_dedup.py` 在规则去重之后再加一层**保守、可解释、确定性**的事件级去重，只影响 `daily_digest_news` 关联：

```text
规则去重 -> 事件去重 -> 日报关联
```

- 不使用 embedding、向量数据库、RAG 或额外 LLM 调用，refresh 成本与可复现性不变
- **不删除任何新闻**：所有采集到的文章仍然写入 `news_articles`，只是不再重复出现在同一份日报里，方便将来做详情页、来源追踪和重新聚类

### 聚类规则

先做两个否决判断，再做文本相似度判断，任何一步不通过就保持两条新闻：

1. **时间窗口**：两条新闻必须同为有时间的新闻，且发布时间相差不超过 48 小时（与规则去重同一时间尺度）
2. **版本否决**：两条标题/正文各自出现的「带数字的标识」如果完全不同，直接否决。`GPT-5` 与 `GPT-6`、5 亿美元与 8 亿美元都是两个事件
3. **立场否决**：出现相反结果的词对（`fails`/`passes`、`drops`/`rises`、`launch`/`deprecate` 等）直接否决，因为这是对同一话题的两次不同报道
4. **文本相似度**（Sørensen-Dice，token 为拉丁词 + 数字 + 中文二元组）：
   - 有正文：`body_similarity >= 0.62`，且标题相似度达到 `0.45`（有共同标识时降到 `0.30`）
   - 无正文（只有标题）：标题相似度必须达到 `0.90`，且共享一个标识
   - 跨语言特例：标题相似度 `>= 0.70` 且共享同一个「有名字的数字」（如 `500m`）时，正文门槛降到 `0.45`。两种语言转述同一事实时摘要用词差得更远

所有阈值集中在 `EventDedupSettings`，默认值如下：

```text
max_hours_apart              = 48.0
body_min                     = 0.62
title_min                    = 0.45
title_min_with_shared_term   = 0.30
title_exact_threshold        = 0.90
title_relaxed_min            = 0.70
body_min_with_shared_figure  = 0.45
```

判断结果永远是「为什么」而不是一个不透明的分数，例如 `reason=shared_term_text_similarity score=0.72 shared=gpt-6 hours_apart=2.0`。

### 主新闻选择

一个事件簇里最终保留哪条，按顺序比较：

```text
官方一手源 > 社区一手内容（Hugging Face）> 媒体（TechCrunch / 量子位）
```

同类来源内依次比较：来源配置的 priority、`importance_score`、内容完整程度（摘要长度）、更早的发布时间（原始公告），最后用 news_id 兜底，所以结果永远不取决于抓取顺序。

### 可观察性

刷新日志默认只加一行统计：

```text
event dedup: candidates=12 clusters=12 merged=0
```

命令行会打印同样的汇总：

```text
Event dedup:
Candidates: 12
Clusters: 12
Duplicates merged: 0
```

设置 `AI_DAILY_DEBUG_EVENT_DEDUP=1` 可以看到每个簇的 `KEEP` / `MERGE` 详情与原因（日志级别仍为 INFO，默认不刷屏）：

```text
KEEP OpenAI: OpenAI 发布 GPT-6 Astra 新模型
MERGE TechCrunch AI: OpenAI 推出 GPT-6 Astra 前沿模型
  reason=shared_term_text_similarity score=0.72 shared=gpt-6 hours_apart=2.0
```

`uv run python -m app.collectors.refresh` 在 `AI_DAILY_DEBUG_GITHUB=1` 时会一并打印这些细节。

正文提取同样有默认汇总 + 可选明细（`AI_DAILY_DEBUG_EXTRACTION=1`，只打印方法与字符数，**绝不打印正文**）：

```text
OpenAI | WEB | 8432 chars
DeepMind | CACHE | 12540 chars
TechCrunch | FALLBACK | HTTP 403
```

### 已知限制

- 阈值是规则而非语义理解：换个说法的两条新闻可能仍然判为两个事件（宁可少合并，也不要错误合并，合并错了会静默隐藏一条真新闻）
- 中文按字符二元组比较，对同义改写（「发布」/「推出」）不敏感
- 同一事件跨越 48 小时的两篇报道不会合并
- 只在写入 `daily_digest_news` 前运行，`news_articles` 不参与聚类，也不做跨日重新聚类

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
- LLM 的输入是**提取到的原始正文**（按 `LLM_CONTENT_MAX_CHARS` 裁剪，默认 6000 字符），不是只有 RSS 摘要；正文抓取失败时自动退回 RSS 摘要
- 提取到的完整正文单独保存在数据库 `news_articles.content_original`，不受上面这个裁剪影响
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
