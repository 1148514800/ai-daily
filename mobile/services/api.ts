import type { DailyDigest, GitHubProject, NewsItem } from '../types';
import { API_BASE_URL } from './config';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`);
  } catch {
    throw new ApiError('网络连接失败', 0);
  }

  if (!response.ok) {
    throw new ApiError('内容加载失败', response.status);
  }

  return (await response.json()) as T;
}

export function fetchTodayDaily(): Promise<DailyDigest> {
  return request<DailyDigest>('/api/v1/daily');
}

export function fetchDailyByDate(date: string): Promise<DailyDigest> {
  return request<DailyDigest>(`/api/v1/daily/${date}`);
}

export function fetchNews(newsId: string): Promise<NewsItem> {
  return request<NewsItem>(`/api/v1/news/${encodeURIComponent(newsId)}`);
}

export function fetchGithubProjects(): Promise<GitHubProject[]> {
  return request<GitHubProject[]>('/api/v1/github');
}

export function previousDates(today: string, count: number): string[] {
  const [year, month, day] = today.split('-').map(Number);
  const cursor = new Date(year, month - 1, day);
  const dates: string[] = [];

  for (let index = 0; index < count; index += 1) {
    cursor.setDate(cursor.getDate() - 1);
    const nextYear = cursor.getFullYear();
    const nextMonth = String(cursor.getMonth() + 1).padStart(2, '0');
    const nextDay = String(cursor.getDate()).padStart(2, '0');
    dates.push(`${nextYear}-${nextMonth}-${nextDay}`);
  }

  return dates;
}
