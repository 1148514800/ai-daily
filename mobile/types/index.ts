export type NewsCategory = 'highlight' | 'model' | 'opensource' | 'tool';

export type NewsItem = {
  id: string;
  title_cn: string;
  title_original: string;
  summary: string;
  why_it_matters: string;
  /**
   * The short Chinese bullets behind 「核心信息」 on the detail screen. The
   * backend always sends a list, and sends `[]` for articles summarised before
   * the field existed, so the screen can treat "no bullets" as a normal state.
   */
  key_points?: string[];
  source: string;
  source_type: string;
  published_at: string;
  category: NewsCategory;
  tags: string[];
  url: string;
  importance_score?: number | null;
  /**
   * Rank inside the digest this item was returned with, 1-based. Absent when an
   * article is read on its own (a favorite), because a rank only means
   * something relative to one day's list.
   */
  rank?: number | null;
  /** The 0-100 score the rank was computed from. */
  rank_score?: number | null;
  /** True for the leading stories the digest calls out. The rest are still here. */
  is_top_story?: boolean | null;
  /**
   * The topic the backend classified this story into, e.g. "model_release".
   * Assigned by the server so the card shows the same label the ranking used.
   */
  topic?: string | null;
  /** The company the backend detected, or an empty string. */
  company?: string | null;
};

/**
 * One article for the detail screen: the list shape plus a description of the
 * stored original-language body.
 *
 * The body used to travel with this payload, then moved to its own endpoint in
 * Phase 10.11. Phase 10.12 stopped the app from reading it at all: the detail
 * screen is the Chinese reading view, so the descriptive fields below are
 * carried for completeness but never rendered. The backend keeps the body for
 * search, re-summarising and quality work.
 */
export type NewsDetail = NewsItem & {
  /** True when the backend has stored a body for this article. */
  has_content: boolean;
  /** BCP-47-ish code for the body, e.g. "en" / "zh". Empty if unknown. */
  content_language: string;
  /** How the body was obtained: rss_full / web / rss_summary / none. */
  content_extraction_method: string;
  /** The deterministic verdict on the body: good / low / fallback. */
  content_quality: string;
};

export type GitHubProject = {
  id: string;
  repo: string;
  name: string;
  description: string;
  language: string;
  stars: number;
  stars_delta: number | null;
  summary_cn: string;
  why_it_matters: string;
  url: string;
  rank?: number | null;
  forks?: number | null;
  license?: string | null;
  topics?: string[];
};

export type DailyDigest = {
  date: string;
  title: string;
  description: string;
  news: NewsItem[];
  github_projects: GitHubProject[];
  /**
   * The UTC issue window this digest covers: (window_start, window_end].
   * Present so history can explain why two days are separate; not shown in the
   * normal reading flow. Null for a digest written before windows existed.
   */
  window_start?: string | null;
  window_end?: string | null;
};

export type DigestSummary = {
  date: string;
  title: string;
  news_count: number;
  github_count: number;
  /** How many of `news_count` the digest presents as top stories. */
  top_story_count?: number;
  /** The digest's UTC issue window, carried for debug info only. */
  window_start?: string | null;
  window_end?: string | null;
};

/**
 * One search hit. Deliberately has no article body: the list stays light, and
 * tapping a result opens the Chinese reading view for that article.
 */
export type SearchResultItem = {
  news_id: string;
  title_cn: string;
  original_title: string;
  summary: string;
  source: string;
  published_at: string;
  /** The digest it was published in, or null when it never reached one. */
  digest_date?: string | null;
  topic?: string | null;
  company?: string | null;
  /** Short excerpt around the match, already plain text. */
  snippet: string;
};

export type SearchResponse = {
  query: string;
  total: number;
  items: SearchResultItem[];
};

export type FavoriteItemType = 'news' | 'github';

export type Favorite = {
  id: number;
  item_type: FavoriteItemType;
  created_at: string;
  item: NewsItem | GitHubProject;
};

export type RefreshRunSummary = {
  status: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  local_time: string | null;
  news_count: number;
  github_count: number;
  error: string | null;
};

export type RefreshStatus = {
  scheduler_enabled: boolean;
  scheduler_running: boolean;
  timezone: string;
  scheduled_time: string;
  is_running: boolean;
  last_run: RefreshRunSummary | null;
  next_run_at: string | null;
};

export type TabKey = 'today' | 'github' | 'favorites' | 'history' | 'settings';
