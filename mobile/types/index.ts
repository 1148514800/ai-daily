export type NewsCategory = 'highlight' | 'model' | 'opensource' | 'tool';

export type NewsItem = {
  id: string;
  title: string;
  originalTitle: string;
  summary: string;
  source: string;
  publishedAt: string;
  category: NewsCategory;
  whyItMatters: string;
  tags: string[];
  url: string;
};

export type GitHubRepo = {
  id: string;
  name: string;
  description: string;
  stars: number;
  starsDelta: number;
  language: string;
  summaryZh: string;
  whyWatch: string;
  url: string;
};

export type DailyDigest = {
  date: string;
  title: string;
  description: string;
  highlight: string;
  newsIds: string[];
};

export type FavoriteItem =
  | { id: string; kind: 'news'; newsId: string }
  | { id: string; kind: 'github'; repoId: string };

export type TabKey = 'today' | 'github' | 'favorites' | 'history';
