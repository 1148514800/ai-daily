export type NewsCategory = 'highlight' | 'model' | 'opensource' | 'tool';

export type NewsItem = {
  id: string;
  title_cn: string;
  title_original: string;
  summary: string;
  why_it_matters: string;
  source: string;
  source_type: string;
  published_at: string;
  category: NewsCategory;
  tags: string[];
  url: string;
  importance_score?: number | null;
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
};

export type DigestSummary = {
  date: string;
  title: string;
  news_count: number;
  github_count: number;
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
