# ai-daily

每天一份 5～10 分钟可读完的中文 AI 日报。后续系统会自动抓取 AI 新闻、GitHub Trending 和开源项目，经过筛选、去重和 AI 摘要后，通过后端提供给 Android App 阅读。

## 当前开发阶段

Phase 10.12 - Rich Summary + Mobile Reading Experience Optimization

今日 AI 新闻来自中外官方模型厂商、研究实验室与 AI 媒体的公开 RSS / 官方页面；GitHub 页来自官方 Trending。LLM 中文增强可选。日报、新闻正文、GitHub 项目和收藏持久化在 SQLite 中，重启后仍然存在。后端每天固定时间自动刷新。日报按**重要度排序**，首页是一条服务端 rank 顺序的新闻列表（**重点新闻 / 更多动态**两段，每条带 官方 / 研究 / 媒体 来源标签），可以按日期回看**历史日报**，也可以对**全部已收录新闻做全文搜索**。

AI Daily 的定位是「每天快速理解 AI 行业变化的中文简报」，**不是 RSS 阅读器**。因此详情页是 **AI 解读页**：中文标题 / 来源 / 时间 / Topic，然后是 **发生了什么？**（150~300 字详细摘要）、**核心信息**（3~5 条要点）、**为什么重要？**（100~200 字），最后是「查看来源」跳转原始网页。**用户端不再提供原文阅读功能**（Phase 10.12 删除），但原始正文仍然保存在数据库里，用于搜索、摘要重新生成、质量评估与未来的 RAG。整套系统仍在本地 Windows 电脑上长期运行，App 打开时主动拉取最新日报，**不使用系统 Push 通知**（见 "Push 状态"）。

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
GET /api/v1/news/{news_id}/content
GET /api/v1/search
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

发布前统一检查（后端跑测试 + release_check，Mobile 跑类型检查 + 测试 + bundle export）：

```powershell
.\scripts\check_backend.ps1
.\scripts\check_mobile.ps1
```

开发环境开启了宽松 CORS，仅用于本地联调，生产环境不要使用 `allow_origins=["*"]`。

> 维护命令（rebuild / backfill）会写数据库，因此受 production guard 保护：默认拒绝操作 `backend/data/ai_daily.db`，需要显式 `--allow-production` 并会先自动备份。详见 [环境隔离与维护命令安全](#环境隔离与维护命令安全phase-1010)。


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
- Mistral AI Blog RSS：`https://mistral.ai/rss.xml`
- Cohere Blog：`https://cohere.com/blog`（官方页面 HTML）
- Cursor Blog：`https://cursor.com/blog`（官方页面 HTML）

国内 AI 官方一手来源（Phase 10.13 新增，全部 `source_type=official`，都没有可用的 RSS，因此各自独立解析）：

- ByteDance Seed / 豆包：`https://seed.bytedance.com/zh/blog`（页面内嵌 `window._ROUTER_DATA` JSON，读 `article_list`；发布日期为 epoch 毫秒）
- 腾讯混元：`https://api.hunyuan.tencent.com/api/blog/publicList`（官方公开 JSON 接口，**POST** `{pageNum, pageSize}`；`hunyuan.tencent.com/news/blog` 是客户端渲染空壳，页面上没有任何文章标记）
- 百度文心：`https://ernie.baidu.com/index.xml`（Hugo 原生 RSS；`<link>` 是站内相对路径，靠 `base_url` 补全为绝对 URL）
- 智谱 GLM：`https://www.zhipuai.cn/zh/news`（React Server Components flight payload 中的 `newsItems`，`category` 决定走 `/zh/news/` 还是 `/zh/research/`）
- MiniMax：`https://www.minimax.cn/blog`（服务端渲染的 `/blog/` 卡片，卡片自带 `YYYY-MM-DD`；`minimaxi.com` 301 到该域名）

- 五个来源都不写“万能中国网站解析器”：一个来源一个 extractor，站点改版只会让该来源报 `PageStructureError`，不会静默产出错误数据
- 每个 extractor 都从真实页面验证过文章 URL、标题与发布时间字段，不是只把 URL 写进配置

研究来源（`source_type=research`，实验室研究而非二手报道）：

- Hugging Face Blog RSS：`https://huggingface.co/blog/feed.xml`
- Microsoft Research Blog RSS：`https://www.microsoft.com/en-us/research/feed/`

媒体来源（`source_type=media`，同一事件去重时让位于官方源）：

- TechCrunch AI RSS：`https://techcrunch.com/category/artificial-intelligence/feed/`
- Ars Technica AI RSS：`https://arstechnica.com/ai/feed/`（全站 AI 分类 Feed，进入 pipeline 前做 AI 相关性过滤）

- `source_type` 只有 `official` / `research` / `media` 三种，由后端唯一决定；客户端只渲染 `官方 / 研究 / 媒体` 标签，**不根据来源名称猜类型**
- **量子位（qbitai）已停止采集**：配置、测试与 fixture 均已删除，数据库中已有的历史新闻保持不动（`news_articles` 里的旧记录不删除，不做任何 destructive migration）
- **本项目不使用 X / Twitter 作为新闻源**：不接 X API / Twitter API、不抓取 X 页面、不做任何预留实现
- GitHub Trending 继续保持**独立逻辑**，不是 `NewsSource`：它是开发者信号，有自己的采集器、自己的 AI 筛选和自己的首页区块，不进入 dedupe / ranking / source_type
- 优先使用官方 RSS / Atom，其次官方公开页面，最后稳定媒体 RSS
- 只接入已确认可稳定公开采集的来源；没有稳定 Feed、且页面结构不适合轻量解析的来源不接入
- HTML 来源都在 `app/collectors/html.py` 中各自独立解析，任一来源失败只影响自身
- 机器之心未接入：服务端对所有请求（含 `robots.txt` 中声明的 sitemap 与实际文章页）统一返回同一个 3251 字节的机器人拦截页，没有可用的 RSS 或文章列表
- **AI 相关性过滤（`app/pipelines/ai_filter.py`）**：Ars Technica 是全站 AI 分类 Feed，含非 AI 报道，因此该来源标记 `requires_ai_filter=True`，在进入 issue window / dedup / ranking 之前先用确定性关键词规则过滤；判定要求证据来自**不同关键词家族**（例如 `robot` + `robotics` 属于同一家族，只算一条证据），避免一篇机器人评测靠同义词堆叠混进来。过滤只用标题与摘要，不调用 LLM
- Phase 10.13 补入国内 AI 品牌强信号：`doubao` / `豆包` / `bytedance seed` / `seedance` / `seedream`、`hunyuan` / `腾讯混元` / `混元`、`ernie` / `文心` / `文心大模型` / `文心一言`、`glm` / `chatglm` / `智谱` / `zhipu` / `autoglm`、`minimax` / `hailuo` / `海螺`。命中的是**模型 / 产品名**，不是公司名：`百度` / `腾讯` / `字节` 既不在强信号也不在弱信号里，所以公司名本身永远不能把一篇非 AI 报道放进日报
- 关键词边界允许**尾随数字**（`Hunyuan3D`、`混元3D`、`GLM4`、`Gemini2.5`），因为模型版本就是这么命名的；前边界仍然严格，`said` / `email` 依然不会命中 `ai`

### Source Health

每次 refresh 打印一张按来源对齐的表（`app/services/source_health.py`），列为**来源名 / OK-FAIL / 数量或错误类型**：

```text
Sources
OpenAI                 OK      1193
Anthropic              OK      11
...
Mistral AI             OK      86
Cohere                 OK      22
Microsoft Research     OK      10
Cursor                 OK      12
Ars Technica           OK      11

Failed: Mistral AI (timeout)
```

- 成功时第三列是**该来源这次交出多少条有效条目**（collector 的 `valid`：标题 / URL / 时间齐全，Ars Technica 还要通过 AI 过滤）
- 这一列**不是本次日报条数**：它在 issue window 过滤之前统计，所以 RSS 源的数字接近 Feed 全量（OpenAI 1193 表示 Feed 里有 1193 条，不代表当天日报有 1193 条）
- 失败时第三列是**错误类型**（`timeout` / `http 403` / `http 404` / `http 5xx` / `dns` / `connection` / `redirect` / `empty` / `parse` / `error`），不是整段 traceback；解析类错误（页面改版）归为 `parse`
- 有失败时表尾追加一行 `Failed: 来源（错误类型）`，便于当天就能发现某个 collector 挂了
- `consecutive_failures` 是**每次运行内**的计数，不做持久化：这一阶段只做 refresh 日志，不做数据库 Dashboard
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
OpenAI              OK      1193
Anthropic           OK      11
Google DeepMind     OK      100
Meta AI             OK      9
NVIDIA              OK      18
DeepSeek            OK      18
Qwen                OK      44
Kimi                OK      19
Mistral AI          OK      86
Cohere              OK      22
Cursor              OK      12
ByteDance Seed / 豆包  OK      8
腾讯混元              OK      9
百度文心              OK      18
智谱 GLM              OK      15
MiniMax             OK      13
Hugging Face        OK      862
Microsoft Research  OK      10
TechCrunch AI       OK      20
Ars Technica        OK      11
Candidates: 18
After dedup: 18

Article extraction:
Candidates: 18
RSS full content: 4
Web extracted: 13
RSS fallback: 1
Failed: 1
Rejected (low quality): 1
Cache hit: 0

Event dedup:
Candidates: 18
Clusters: 18
Duplicates merged: 0

Ranking:
Candidates: 18
Top stories: 10
Topics: 8
Companies: 5

GitHub Trending
Fetched: 14
Parsed: 14
AI candidates: 3
Metadata success: 14
Selected: 3

Digest saved: 2026-09-15
News: 18
GitHub: 3

Database
Daily digests: 1
News total: 18
GitHub repos total: 3
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
source       0.20   官方一手 > 研究实验室 > 媒体（Phase 10.13 从 0.14 上调）
recency      0.08   在 issue window 内的相对位置（越新越高）
content      0.05   正文完整度（web / rss_full > rss_summary fallback）
cluster      0.06   同一事件被多个来源报道时的小幅加成（有上限）
```

- `importance_score` 缺失时按中性值（35）处理，不会直接判 0，也不会因此排到最前
- Phase 10.13 把 `source_weight` 从 0.14 提到 0.20，差额来自 recency（0.10→0.08）、content（0.06→0.05）与 cluster（0.10→0.06）：这三个本来都只是辅助信号，不该单独改变日报顺序
- **来源仍然是权重，不是硬排序**：类内权重 `official 1.0 / research 0.55 / media 0.15`，跨越 official 与 media 的整档差距约 17 分，低于「重要性差 30 分」这个量级，所以媒体的大新闻（例如 importance 95）依然能超过普通的官方小更新（例如 importance 20）；反过来，重要性相差 20 分以内的两条新闻，才由来源等级决定先后
- 官方 / 研究 / 媒体在**同等重要性**下的顺序现在是明确且可测的：`official > research > media`
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

### 媒体精选（Phase 10.13）

排序只改变顺序、不删除文章，所以 Phase 10.13 之前媒体资讯即使排在最后也**全部**进入日报。现在在事件去重之后、最终排序之前增加一层明确的 **media selection**（`app/services/media_selection.py`）：

```text
collect -> window -> URL dedupe -> extract -> LLM enrich
        -> event dedup -> media selection -> ranking -> persist
```

只对 `source_type == media` 生效，三条规则：

```text
min_importance   60   媒体文章必须有真实的 importance_score，且 >= 60 才进入日报
max_total         5   每份日报最多 5 条媒体新闻
max_per_source    2   单一媒体来源最多 2 条
```

- **`importance_score` 为 `None` 的媒体文章不进入日报**：fallback 分数代表 pipeline 没有做出任何判断，不足以占用一个媒体名额
- **`official` / `research` 完全不受这三条规则限制**：数量上限是为了约束**二手**报道，套用到厂商自己的发布上会正好压制这个日报存在的理由
- 媒体候选之间的取舍顺序是 `importance_score` → 发布时间（越新越优先）→ `news_id`，因此结果不取决于抓取顺序
- 放在事件去重**之后**：同一事件已被官方 / 研究源代表时，那条媒体重复项早已被折叠掉，根本不会成为媒体候选，也就不会被"补回来"
- 媒体只负责补盲：官方通常不会第一时间发布的重大融资、收购、监管、诉讼、安全事故等，只要 `importance_score >= 60` 且没有更高等级来源覆盖，仍然能进入日报
- **不删除任何数据**：被筛掉的媒体文章照样写入 `news_articles`（仍可被搜索、仍可被以后的 refresh 或 rebuild 选中），只是**不建立当天日报的关联**；历史日报不会被重写，规则只影响后续 refresh
- 阈值、总量、单来源上限集中在 `MediaSelectionSettings`，可用 `media_settings=` 注入，不散落在业务代码里；`DigestStore` 只负责编排，裁剪逻辑不写在 `persist()` 内
- 调试输出：默认每个 refresh 只打印一行 `media selection: candidates=... selected=...`；`AI_DAILY_DEBUG_MEDIA_SELECTION=1` 额外逐条打印 `KEEP <来源> | <标题> | importance=NN` 与 `DROP <来源> | <标题> | reason=per_source_cap|total_cap|importance<60`，refresh CLI 也打印 `Media selection` 汇总块

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

首页分成两段（重点新闻 / 更多动态），见 [今日日报首页](#今日日报首页phase-107)。

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

Phase 10.6 已经算好顺序。这个首页只把那份顺序做成一个「每天 5～10 分钟能读完」的页面，**不改采集、不改 event dedup、不改正文提取、不改 ranking 算法**。Phase 10.11 之后结构更简单：**今日 AI 日报 → 新闻列表（服务端 rank 顺序）→ GitHub Trending**。

```text
今日 AI 日报
2026年9月13日 星期日

今日收录 12 条 AI 动态
精选 10 条重点新闻 · 3 个来源 · 6 个话题

⭐ 重点新闻        Top 10
  [官方] OpenAI · 2小时前
  ...
  [研究] Hugging Face · 5小时前
  ...

📰 更多动态        rank 11+
  ...

💻 GitHub Trending
  ...
```

### 两层分组

分组完全来自后端已经返回的字段，客户端不重新排序、不重新打分：

```text
is_top_story = true    重点新闻
其余                   更多动态
```

- **「今日必看」（rank 1~3）已在 Phase 10.11 删除**：不再有 `MUST_READ_LIMIT`，不再有单独的 must_read section 或对应文案。同一份 ranking 之前被展示两次，且「第 3 条」这条界带没有依据
- `is_top_story` 与 `rank` 都由后端给出，Mobile 只做切分，**不新增第二套排序**
- 所有新闻都会渲染：更多动态不是丢弃，只是排在后面；两段合起来读就是完整的 rank 1..N
- 旧日报没有 `is_top_story` 时不做猜测，全部进「更多动态」，顺序保持后端返回的顺序
- 分组与统计都在 `mobile/lib/digestSections.ts`（纯函数、可单测），不堆在 Component 里

### 来源类型 badge

每条新闻显示来源类型标签，**按后端返回的 `source_type` 渲染**，客户端**不根据来源名称猜类型**：

```text
official → 官方      research → 研究      media → 媒体
```

- 映射集中在 `mobile/lib/sourceType.ts`（纯函数、可单测），未知值不显示 badge 而不是显示错误标签
- 采用「每条新闻一个 badge」而不是「按来源类型重新分组」：分组会破坏当前全局 ranking 的阅读体验，badge 不会
- GitHub Trending 保持**独立区块**，它不是 `NewsSource`，没有 `source_type`

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

- 总新闻不足 10 条：重点新闻 section 自然变短或消失
- 没有更多动态：不显示「更多动态」标题（空 section 不渲染）
- 没有 GitHub 项目：不显示 GitHub section
- 空日报：显示空状态文案
- Backend 请求失败：显示错误文案 + 「重新加载」

### 首页只展示阅读相关内容（Phase 10.12）

首页顶部**不再显示任何后台状态信息**：没有「最后更新时间：xxxx」，没有「每天 08:00 自动刷新」，也没有 scheduler 运行状态。这些信息全部移到**设置页的「系统状态」**（见下文），首页只保留：日期、今日 AI 日报标题、日报概览、新闻列表（重点新闻 / 更多动态）、GitHub Trending。

首页是阅读界面，不是运维面板。空日报的提示也相应改成「今天还没有生成日报，稍后再来看看。」，不再解释刷新计划。

### 返回首页保持滚动位置（Phase 10.12）

从首页点进一篇文章、再返回时，列表**回到离开时的位置**，而不是跳到顶部。

原因：push 到详情页会 unmount 列表，返回时重新 mount 一个全新的 `ScrollView`，位置自然归零。位置是**列表的属性**而不是组件实例的属性，所以保存在 `mobile/lib/scrollMemory.ts`（按 key 记录 offset，纯函数可单测）：

```text
today                 今日日报
digest:2026-09-12     某一天的历史日报（每天各自独立）
```

- 滚回顶部意味着「下次从顶部开始」，所以顶部附近的 offset 会被记为「无需恢复」，而不是恢复到一个无意义的位置
- 恢复用非动画的 `scrollTo`：内容异步到达，从顶部动画滚下来会看到明显跳动
- 首次 `contentSizeChange` 时列表可能还没铺满，`scrollTo` 会被截断，因此允许**有限次**重试（`SCROLL_RESTORE_ATTEMPTS`），不做无限循环
- 保存 offset 只在 unmount 时做一次，滚动回调不 setState，因此滑动不会触发整页重渲染
- 位置只存在内存里：重启 App 后从今天日报顶部开始是正确默认值，不存在过期问题

## 历史日报与日期导航（Phase 10.8）

Phase 10.7 让首页值得读，Phase 10.8 解决「怎么方便地看昨天、前天」。**不改采集、不改 event dedup、不改正文提取、不改 ranking 算法，也不改 issue window**，只是把数据库里已经存在的日报按日期读出来。

### 入口

- Phase 10.11 起，**今日首页不再提供「历史日报 →」与「搜索历史新闻」入口**（见对应小节），入口收敛到「历史」Tab
- 「历史」Tab 列出数据库里**真实存在**的日报，按日期倒序
- 「历史」Tab 顶部保留「搜索全部历史新闻 →」入口，进入搜索页
- 点击任意一天进入日报页，复用今日首页的同一套 UI（重点新闻 / 更多动态 / GitHub Trending）

历史列表只显示真实存在的日报，**不会为不存在的日期生成空日报**。

被删掉的只是**今日首页上的两个跳转**：后端的历史日报 API（`/digests`、`/daily/{date}`）与全文搜索 API（`/search`）都原样保留，历史 Tab 与搜索页也都还在，只是不再从「今天读什么」这个页面往外分流。

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
Environment: development
Database:    F:\study\ai-daily\backend\data\ai_daily.db
Mode:        execute

Search index rebuilt
Articles: 1234
Indexed: 1234
```

- 幂等，可安全重复执行
- 只读 `news_articles`，只写索引：不抓 RSS、不调 LLM、不删文章、**不修改 digest 关联**
- 写数据库，因此受维护命令 guard 保护（见 [环境隔离与维护命令安全](#环境隔离与维护命令安全phase-1010)）

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

入口在「历史」页（不改 TabBar 结构）。**Phase 10.11 移除了 Today 页上的搜索入口**，搜索页本身与 `/api/v1/search` 后端能力都保留：

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
- 点击结果进入**现有** `NewsDetailScreen`，即中文解读页（发生了什么 / 核心信息 / 为什么重要 / 查看来源 / 收藏）；Phase 10.12 起不再有「查看原文内容」
- 本阶段不做搜索历史（不写 SQLite、不写 AsyncStorage）

## 环境隔离与维护命令安全（Phase 10.10）

Phase 10.10 不新增产品功能，只解决一件事：**让维护命令无法再误操作正式数据库。**

背景是一次真实事故：Phase 10.9 忘记设置临时 `DATABASE_URL`，`rebuild_search_index` 直接在正式的 `backend/data/ai_daily.db` 上运行。本阶段的目标是让同样的操作**无法再静默发生**。

### APP_ENV

```text
APP_ENV=development   # 默认
APP_ENV=test          # pytest
APP_ENV=production    # 正式运行
```

- 只有这三个值被识别，其他值（例如拼错的 `prodution`）会**回退到 development 并记录日志**，`release_check` 会报 FAIL，不会假装是正式环境
- 判断集中在 `app/config/environment.py`，不在各处散落 `os.getenv("APP_ENV")`
- `uv run pytest` 固定使用 `test`（在 `tests/conftest.py` 里于 import `app` 之前设置）

### 数据库优先级

```text
CLI --database-url  >  DATABASE_URL  >  默认 backend/data/ai_daily.db
```

`--database-url` 既接受 URL，也接受裸路径：`--database-url C:\temp\scratch.db`。

### 执行前显示

所有写库维护命令在执行前都打印同样的三行（**不包含任何 Secret**，数据库一栏是解析后的路径而不是连接串）：

```text
Environment: development
Database:    F:\study\ai-daily\backend\data\ai_daily.db
Mode:        execute          # 或 dry-run
```

带密码的 PostgreSQL URL 只会显示为 `***@host/db`。

### Production Guard

以下**任一**情况成立时，任何写库维护命令默认拒绝执行：

```text
APP_ENV=production
目标数据库就是默认的 backend/data/ai_daily.db
```

输出：

```text
Target database looks like the production/default AI Daily database.
Use --allow-production if intentional.
Detected because of: the default AI Daily database file.
```

必须显式加 `--allow-production` 才会继续。

**关键点：**默认正式 DB 是一个**不依赖环境变量的 sentinel**。即使 `APP_ENV` 被错写成 `development`（正是 Phase 10.9 的情形），只要目标是 `backend/data/ai_daily.db`，命令仍然拒绝执行。

`--dry-run` 例外：dry run 不修改任何东西，因此允许**描述**正式库上会做什么，并额外打印一行提示 real run 需要 `--allow-production`。

受保护命令的退出码：

```text
0  成功
2  被 production guard 拒绝
3  校验或备份失败而中止（数据库未被修改）
```

### 自动备份

对 production（或默认库）的**真实写操作**，执行顺序固定为：

```text
validate -> backup -> execute
```

产物：

```text
backups/pre_rebuild_search_index_YYYYMMDD_HHMMSS.db
backups/pre_rebuild_digests_YYYYMMDD_HHMMSS.db
backups/pre_backfill_article_content_YYYYMMDD_HHMMSS.db
```

- 使用 SQLite online backup API，因此即使 Backend 正在运行（数据库被占用）也能得到一致的副本（副本内容一致，但不保证与源文件逐字节相同）
- **备份失败立即终止，绝不再碰数据库**

PostgreSQL **暂不支持自动文件复制**。因为「无法回滚」不是一个可以写入的状态，对 production 的非 SQLite 目标命令会直接中止并说明原因，而不是在无法备份时继续写；只有 SQLite 会在写入前自动备份。

### Dry Run

`--dry-run` 至少覆盖三个命令，并且保证：

- 不修改业务数据
- 不创建永久 FTS 表
- 不 `VACUUM`
- 不修改 schema（**不调用 `init_db()`**）
- 不因为描述计划而创建数据库文件

只输出准备执行的操作。对不存在的数据库，dry run 报告 `Would index: 0 articles` 而不是创建一个空库。

### 受保护的命令

```bash
cd backend
uv run python -m app.jobs.rebuild_search_index            # 重建搜索索引
uv run python -m app.jobs.rebuild_digests --dates 2026-09-13
uv run python -m app.jobs.backfill_article_content --limit 20
```

三者都支持 `--database-url` / `--dry-run` / `--allow-production`，并共用同一个 guard 模块（`app/config/maintenance.py`），后续 rebuild / repair / migrate 类任务应复用同一入口。

### 只读诊断

```bash
cd backend
uv run python -m app.jobs.inspect_database
```

输出：

```text
Path / Size / SHA256 / Integrity / Foreign key check
Business table counts
FTS tables
```

以及：

```bash
uv run python -m app.jobs.release_check
```

检查 Database integrity、Foreign keys、Search backend、APP_ENV、APP_TIMEZONE、Scheduler、LLM 配置、必需目录、Production safety，输出 `PASS` / `WARN` / `FAIL`，有 FAIL 时退出码 `1`（便于脚本 gate）。它**不做** refresh、不抓 RSS、不调 LLM、不修改数据库。

两个命令都是**完全只读**：不 `create_all`、不升级 schema、不 `ensure_index`、不 `VACUUM`、不写任何数据。运行它们**不会改变文件的 SHA256**，也不会创建 `news_search_fts*`；这一点有回归测试覆盖。

`release_check` 的判定：

```text
PASS  一切正常
WARN  不阻塞发布但需要知情（SCHEDULER_ENABLED=false、目录尚未创建、未设置 APP_ENV）
FAIL  必须修复（未知 APP_ENV、不可用时区、LLM 已启用但缺少配置、数据库损坏、外键违规）
```

退出码 `0` 表示没有 FAIL（可能有 WARN），`1` 表示至少一个 FAIL。

### FTS 生命周期

只读路径（`inspect_database`、`release_check`、status 接口）不会创建 `news_search_fts*`。FTS 表只在**明确需要初始化搜索索引**的两处创建：

- API 启动（`app/main.py` 的 lifespan -> `ensure_index`）
- 显式的 `rebuild_search_index`

其他路径不会创建它：`index_items`（正常 refresh 写索引时调用）在表不存在时是 no-op，只读命令与 status 接口都不碰 schema。搜索能力探测也改成了只读（用内存库探测 tokenizer、用 `sqlite_master` 读已有索引），不再在真实数据库上创建 probe 表。

### 测试库强隔离

`uv run pytest` 绝对不可能访问 `backend/data/ai_daily.db`：

- `conftest.py` 在 import `app` 之前设置 `APP_ENV=test`，并指向 `tmp_path` 下的临时 SQLite
- `configure_database()` 与 `get_engine()` 在 `APP_ENV=test` 时发现默认正式 DB 会**直接抛错**，因此即使某个测试手写 `DATABASE_URL` 也绕不过去
- 有专门 regression test 覆盖

### Release 前统一检查

```powershell
.\scripts\check_backend.ps1     # uv run pytest + release_check
.\scripts\check_mobile.ps1      # tsc --noEmit + npm test + expo export
```

两者都在失败时以非 0 退出码结束，方便串进发布流程。

## 数据持久化

- 当前使用 SQLite + SQLAlchemy 2.x，适合个人单用户场景
- 数据库文件：`backend/data/ai_daily.db`（`backend/data/` 已加入 `.gitignore`，不会提交）
- 连接串由环境变量 `DATABASE_URL` 控制，默认 `sqlite:///./data/ai_daily.db`
- 相对路径始终相对 `backend/` 解析，与启动时的工作目录无关；目录不存在时会自动创建
- 日报日期（`date` 主键）仍由 `APP_TIMEZONE` 计算，默认 `Asia/Shanghai`；采集时间（`published_at`）与窗口（`window_start` / `window_end`）统一以 UTC 保存
- 一条新闻只属于一个窗口：`window_start < published_at <= window_end`，同一份日报的链接不会跨窗口重复
- 本阶段不做数据库迁移系统，表结构由 `Base.metadata.create_all()` 初始化；Phase 10.2 新增的 `window_start` / `window_end`、Phase 10.5 新增的 `content_original` 等正文字段、Phase 10.6 新增的 `rank` / `rank_score`、Phase 10.11 新增的 `content_raw`、Phase 10.12 新增的 `key_points_json` 都由轻量 `ALTER TABLE ADD COLUMN` 补列，旧数据库直接打开即可使用
- `key_points_json` 以 JSON 数组字符串保存 LLM 生成的中文要点；旧行该列为 NULL，读取时统一变成 `[]`，非字符串或损坏的值也会被丢弃而不是抛错

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

Phase 10.5 建立了「日报列表 / 新闻详情」两层内容。Phase 10.12 调整了第二层的定位：详情页不再展示原文，而是展示**中文结构化解读**（发生了什么 / 核心信息 / 为什么重要 + 查看来源），因为 AI Daily 是中文简报而不是 RSS 阅读器。原始正文仍然采集、清洗、入库，只是不再面向用户展示。

```text
日报列表                            新闻详情（AI 解读页）
中文标题                            中文标题 / 原始标题
中文摘要              点击          来源 badge · 来源 · 时间 · Topic
Why it matters       ───────►       发生了什么？（150~300 字）
importance score                    核心信息（3~5 条要点）
                                    为什么重要？（100~200 字）
                                    ────────────────────────
                                    收藏
                                    [ 查看来源 ]   ← 系统浏览器打开 url
```

**原始正文绝对不翻译、不改写**，中文解读与原始正文是两套独立字段：

```text
content_original  原始正文，英文新闻保持英文，中文新闻保持中文（不展示给用户）
title_cn          中文标题        ┐
summary           发生了什么      │ LLM 根据正文生成，绝不回写正文
key_points        核心信息        │
why_it_matters    为什么重要      │
importance_score  0-100          ┘
```

正文仍然保留在数据库里的原因：搜索索引需要它（Phase 10.9 的 FTS 覆盖 `content_original`），将来重新生成摘要、做质量评估、做 RAG 也都要用到。

### 正文提取 pipeline

`app/services/article_extractor.py` 是**所有来源共用**的一套提取逻辑（不是 15 个 parser），来源差异只体现在列表页怎么抓，这一点 `app/collectors/` 已经处理。正文来源按优先级：

```text
RSS full（content:encoded / Atom content，长度达标）
        ↓ 否则
source-specific selector / 网页正文提取
        ↓
cleaning
        ↓
quality check（good / low / fallback，确定性规则，不用 LLM）
        ↓ 质量不合格或抓取失败则
RSS summary fallback（最后兜底，文章不会丢）
```

网页正文提取内部再分两层：

```text
来源专用 selector（cohere / cursor / anthropic / deepseek / kimi）
        ↓ 未命中
通用正文提取（article / main / [role=main] / .prose / ...，取文本最多的候选）
        ↓
fallback
```

清洗规则：保留 paragraph / heading / list / quote / code / table（heading 保留层级、列表和引用保留标记），过滤 script、style、nav、footer、aside、form、iframe、noscript、button，以及按 `class` / `id` / `role` 命中的 nav、cookie、consent、banner、share、social、related、recommended、newsletter、subscribe、sign-in、login、ad、sidebar、author-card、comments、pagination、tags 等噪声。**判断只看标签名、`class`、`id` 和 `role`，不看正文文字**，所以正文里提到 cookie 不会被误删；`class` / `id` 按整词匹配，避免 `nav` 命中 `navigation-with-keyboard` 这类框架类名。正文容器在移除干扰元素后取**文本最多的候选**，因为页面里的小 `<article>` 卡片常常是相关推荐而不是正文。

文本后处理：HTML entity decode、Unicode 空白归一、连续空格与连续空行合并、重复段落与重复标题去重、极短孤立按钮文本与明显 footer 行丢弃；不影响 heading / list / quote / code block / 数字 / benchmark / URL。

正文以**规范化纯文本**保存（段落之间空行，标题/列表/引用带轻量 Markdown 标记），不保存 raw HTML。

### 正文质量检测 + 两层正文

`app/services/article_quality.py` 用确定性规则判断「这段文本到底是不是一篇文章」，**不调用 LLM**：

| 指标 | 含义 |
| --- | --- |
| `chars` / `paragraphs` / `avg_paragraph_chars` | 文本量、段落数、平均段落长度 |
| `noise_ratio` | 导航 / cookie / 分享 / footer 措辞段落占比 |
| `duplicate_ratio` | 重复段落占比（模板重复打印自己的样子） |
| `link_text_ratio` | 短标签段落占比（去掉标签后的菜单是什么样） |

长度阈值用**有效长度**（CJK 字符按 2.5 计），所以一段 160 字的中文正文是文章，而同样长度的英文不是。判定结果是 `good` / `low` / `fallback` 三档；**网页正文质量低就自动回退 RSS summary，绝不把垃圾正文存成正式 `content_original`**。

数据库保存两层正文：

```text
content_raw       从 RSS full content 或网页正文候选中取到的未完全清洗文本（诊断用，不对外返回）
content_original  清洗 + 质量检查后的正文（Phase 10.12 起不再展示给用户，供搜索 / 重新摘要 / 质量评估使用）
```

两层都用既有的 `create_all` + `ALTER TABLE ADD COLUMN` 补列，旧数据库可以直接打开，不做 destructive migration。

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

System prompt（`app/services/llm/prompts.py`，`PROMPT_VERSION=v3`，改了 prompt 就会让缓存失效）明确要求：

```text
只能使用正文中实际出现的信息
不得补充正文中不存在的事实、数字、日期、人名或结论
不得根据模型记忆猜测或补全
正文没有提到的内容就不要写进摘要
正文可以是英文，但输出必须是中文
不要夸张宣传，不要写营销式形容词
```

Phase 10.12 把输出结构从三个字段扩到四个，目标的读者是 AI 从业者与开发者：

```text
title_cn        简洁自然的中文标题
summary_cn      150~300 字，依次说明：谁发布 / 发布什么 / 技术或产品变化 /
                与过去相比的区别 / 为什么值得关注
key_points      3~5 条要点，优先提取技术指标、产品能力、开源信息、
                发布时间或可用性、性能数据
why_it_matters  100~200 字，解释对 AI 行业或开发者的影响
importance_score 0~100
```

为什么 importance_score 没变：它是排序输入，Phase 10.12 不改 ranking。

正文提取失败时退回 RSS summary，再退回现有 fallback；LLM 失败也不会丢文章，原文本地保存并可直接展示。

`key_points` 是**新增字段**，兼容规则是「旧数据返回空数组」：

- 数据库里 Phase 10.12 之前生成的摘要没有要点，读取时统一返回 `[]`，页面隐藏「核心信息」区块
- `PROMPT_VERSION` 升到 `v3`，旧缓存 key 自然失效：**新采集**的文章会用新结构生成，缓存里的旧摘要不会被重新生成，除非那篇文章重新进入 refresh 或重新跑一次 backfill
- 因此升级后第一天，日报里会同时存在「有要点的新文章」和「没有要点的老文章」，这是预期行为而不是 bug

### 正文 Cache

以 **canonical URL** 为 key 缓存成功提取的正文（默认 `backend/.cache/articles/`，可用 `ARTICLE_CACHE_DIR` 覆盖），第二次 refresh 直接复用，不再重复请求同一个页面。**失败结果不写入缓存**，所以一次性 403 / 超时以后仍会重试。

### 网络容错

正文抓取具备 timeout、User-Agent、redirect 上限，非 2xx / 非 HTML / 空正文都回退到 RSS summary，单篇文章异常孤立处理，不做无限 retry。**一个页面失败永远不会让整个 refresh 失败。**

### Article Detail API

详情拆成**两个接口**，元数据与正文分开请求：

```text
GET /api/v1/news/{news_id}          元数据 + 正文状态，不含正文
GET /api/v1/news/{news_id}/content  正文（Phase 10.12 起 Mobile 不再调用）
```

第二个接口**保留在后端**：正文仍然要能被搜索、被重新摘要、被质量评估。Phase 10.12 只是让客户端不再请求它，因为 AI Daily 的用户端是中文解读页而不是阅读器。

`GET /api/v1/news/{news_id}`（Phase 10.11 起不再返回正文）：

```json
{
  "id": "rss-4aeb82da9975e2f5",
  "source": "OpenAI",
  "source_type": "official",
  "url": "https://openai.com/index/...",

  "title_original": "Perplexity trusts GPT-6 Astra with end-to-end systems",
  "title_cn": "……",
  "summary": "……",
  "key_points": ["发布方：……", "模型：……", "许可：……"],
  "why_it_matters": "……",
  "importance_score": 88,
  "published_at": "...",

  "has_content": true,
  "content_language": "en",
  "content_extraction_method": "web",
  "content_quality": "good"
}
```

`GET /api/v1/news/{news_id}/content`：

```json
{
  "news_id": "rss-4aeb82da9975e2f5",
  "content_original": "Perplexity is using ...",
  "content_language": "en",
  "content_extraction_method": "web",
  "content_quality": "good"
}
```

语义约定：

- 文章不存在 → 两个接口都返回 **404**
- 文章存在但没有正文 → `/content` 返回 **200** + 空 `content_original`，客户端显示"没有可显示的原文"，不当成错误
- `has_content` 只是"是否有可展示正文"的提示，不是正文长度的替代品
- `content_raw` 是诊断字段，**任何接口都不返回**
- 日报/列表接口（`/daily`、`/daily/{date}`、`/favorites`、`/search`）都不返回正文，避免一次下发十几篇全文
- `key_points` 永远是数组：老数据（Phase 10.12 之前生成的摘要）没有这个字段，返回 `[]`，客户端据此隐藏「核心信息」区块

拆开的好处：打开详情页只下载元数据（几百字节），读原文是一次显式请求；日报列表页、搜索结果页也不再因为正文而变重。

### Mobile 新闻详情页

`mobile/screens/NewsDetailScreen.tsx` 是一个**AI 解读页**，不是原文阅读器。Phase 10.12 删除了「查看原文内容」按钮、原文展开区域与正文 loading 状态，页面上只保留中文解读和一条跳转来源的出口：

```text
中文标题
原始标题（如果有）
────────────────────────────────
来源 badge · 来源   ·   发布时间   ·   Topic
发生了什么？          ← summary，150~300 字
核心信息              ← key_points，3~5 条
为什么重要？          ← why_it_matters，100~200 字
────────────────────────────────
收藏
[ 查看来源 ]          ← 系统浏览器打开 article.url
```

规则说明：

- **只发一个请求**：页面只调用 `GET /api/v1/news/{news_id}`，不再调用 `/content`。正文仍然存在数据库里，只是用户端不展示
- **老数据兼容**：Phase 10.12 之前生成的摘要没有 `key_points`，此时「核心信息」区块整块隐藏，而不是显示一个空标题
- **不展示任何全文**：`content_original`、英文全文、中文全文都不出现在详情页
- **时间是绝对的**：详情页可能从今天的日报、历史日报或收藏进入，所以显示 `9月15日 周一 08:02` 这样的固定时间，不用「2小时前」这种在历史语境下会失真的说法
- **要点清洗集中在 `mobile/lib/readingView.ts`**（纯函数、可单测）：去空白、去重复，并容忍后端返回 null 或非数组；发布时间也在同一个模块里格式化成 `9月15日 周一 08:02`

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

- OpenAI 官网对非浏览器请求返回 403，该来源的正文会退回 RSS summary；实测 20 个来源里只有这一个稳定失败
- Cohere / Cursor / Anthropic / DeepSeek / Kimi / ByteDance Seed / 智谱 GLM / MiniMax 靠页面结构解析，站点改版会明确报错（`PageStructureError`），对应来源的正文退回 RSS summary，不会静默产出垃圾正文
- 腾讯混元读的是官方公开 JSON 接口而不是页面：接口字段变化同样会报结构错误，而不是返回空列表
- 五个国内来源都不提供"翻页"：ByteDance Seed 的 `?page=` 参数实测无效（每次返回同样 8 条），因此每个来源只取首页可见的那一批，接入至今的完整历史需要改采集方式
- Ars Technica 是全站 AI 分类 Feed，含非 AI 报道，进入 pipeline 前用确定性关键词规则过滤（不做 LLM 分类）；过滤是保守的，可能漏掉边缘报道
- 提取是启发式规则而非通用阅读器：个别站点结构或反爬变化时会退回 RSS summary，并在 `content_extraction_method` 与日志中标明
- `content_language` 只做脚本判定（中/英/日/韩/俄），不做统计语言识别
- 正文按纯文本/轻量标记保存，不保留原始 HTML 结构与图片
- `key_points` 的质量取决于模型与正文：正文很短时模型可能只给 0~2 条，短于 prompt 要求的 3 条不属于错误，页面会照实少显示
- TechCrunch 的少数推广型文章正文本身就是宣传稿，清洗规则无法把推广文案变成技术信息（属于来源筛选问题，不是清洗问题）
- 正文抓取失败的来源（如 OpenAI 403）生成的摘要依据的是 RSS 摘要，不如有全文时详细
- 不提供全文翻译、embeddings、向量检索、RAG 或语义搜索

## 跨来源事件去重

同一件事常被多个来源分别报道：OpenAI 官方发布一个模型，TechCrunch 报道它，Ars Technica 再转述一次。规则去重（canonical URL、48 小时内完全相同标题）看不见这种重复，日报里就会出现三条几乎一样的新闻。

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
官方一手源（official）> 研究实验室（research，Hugging Face / Microsoft Research）> 媒体（media，TechCrunch / Ars Technica）
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

### 设置页「系统状态」（Phase 10.12）

首页顶部原来的刷新信息移到了这里，数据来源仍是 `GET /api/v1/refresh/status`，**没有新增接口**：

```text
系统状态
  自动刷新     每天 08:00
  时区         Asia/Shanghai
  最近刷新     2026-09-15 08:02
  刷新状态     成功
```

- 接口失败或未加载完成时，四行都显示「暂无状态信息」，页面结构不变（不会整块消失）
- 还没有刷新记录时，「最近刷新」显示「暂无记录」，「刷新状态」显示「尚未刷新」
- 运行中的刷新显示「进行中」，失败的显示「失败」
- 时间按 `APP_TIMEZONE` 换算（`mobile/lib/systemStatus.ts`，纯函数、可单测），不受手机时区影响

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

维护命令在执行**正式库的真实写操作**前会自己先备份一份，命名与上面的手动备份区分开：

```text
backups/pre_rebuild_search_index_YYYYMMDD_HHMMSS.db
```

这些自动备份不会被 `backup_db.ps1` 的清理逻辑删除（它只匹配 `ai_daily_*.db`）。

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

#### 用本机 Android SDK 直接构建

本机**已经安装了 Android SDK** 与 JDK，只是对应的环境变量没有持久化：

```text
Android SDK installed at F:\software\Sdk
JDK at F:\software\JDK\jdk-22
ANDROID_HOME / ANDROID_SDK_ROOT are not persisted.
```

因此每次打开新的终端都要先设置（只影响当前终端，不修改系统环境变量）：

```powershell
$env:JAVA_HOME = "F:\software\JDK\jdk-22"
$env:ANDROID_HOME = "F:\software\Sdk"
$env:ANDROID_SDK_ROOT = "F:\software\Sdk"
```

然后构建：

```powershell
cd mobile
npx expo prebuild --platform android
.\android\gradlew.bat :app:assembleRelease
```

产物在 `mobile\android\app\build\outputs\apk\release\app-release.apk`。
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

- RSS / 官方页面 / 官方 JSON 接口（16 official + 2 research + 2 media，共 20 个来源）：真实，每次 refresh 逐个抓取并输出 source health
- 其中 16 official 里有 5 个是 Phase 10.13 新增的国内厂商（ByteDance Seed / 豆包、腾讯混元、百度文心、智谱 GLM、MiniMax）
- GitHub Trending：真实，独立的开发者信号，不是 `NewsSource`
- LLM：可选
- 数据存储：SQLite（`backend/data/ai_daily.db`）
- 自动定时：APScheduler 每日刷新 + 启动补偿（单进程内）
- Push：不使用（产品决策，Backend 代码保留为 dormant，默认 PUSH_ENABLED=false）
- 量子位（qbitai）：Phase 10.11 起停止采集，历史记录保留在数据库里
- X / Twitter：不使用，也不做任何预留实现

GitHub 热门项目来自官方 Trending 页面，`stars_delta` 表示页面上的 stars today，不是历史快照差值。

可选配置 GitHub Token，提高 REST metadata 的 rate limit：

```bash
GITHUB_TOKEN=ghp_xxx
```

没有 Token 时仍会请求公开仓库。Token 只用于后端，不会下发到 Mobile，也不要提交到 Git。
