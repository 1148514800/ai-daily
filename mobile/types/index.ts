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
  stars_delta: number;
  summary_cn: string;
  why_it_matters: string;
  url: string;
};

export type DailyDigest = {
  date: string;
  title: string;
  description: string;
  news: NewsItem[];
  github_projects: GitHubProject[];
};

export type TabKey = 'today' | 'github' | 'favorites' | 'history';
