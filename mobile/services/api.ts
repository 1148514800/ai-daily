import type {
  DailyDigest,
  DigestSummary,
  Favorite,
  FavoriteItemType,
  GitHubProject,
  NewsItem,
} from '../types';
import { API_BASE_URL } from './config';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'DELETE';
  body?: unknown;
  fallbackMessage?: string;
};

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, fallbackMessage = '内容加载失败' } = options;

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError('网络连接失败，请检查后端是否已启动', 0);
  }

  if (!response.ok) {
    throw new ApiError(fallbackMessage, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function fetchTodayDaily(): Promise<DailyDigest> {
  return request<DailyDigest>('/api/v1/daily');
}

export function fetchDailyByDate(date: string): Promise<DailyDigest> {
  return request<DailyDigest>(`/api/v1/daily/${date}`);
}

export function fetchDigests(): Promise<DigestSummary[]> {
  return request<DigestSummary[]>('/api/v1/digests');
}

export function fetchNews(newsId: string): Promise<NewsItem> {
  return request<NewsItem>(`/api/v1/news/${encodeURIComponent(newsId)}`);
}

export function fetchGithubProjects(date?: string): Promise<GitHubProject[]> {
  const query = date ? `?date=${encodeURIComponent(date)}` : '';
  return request<GitHubProject[]>(`/api/v1/github${query}`);
}

export function fetchFavorites(): Promise<Favorite[]> {
  return request<Favorite[]>('/api/v1/favorites');
}

export function addFavorite(
  itemType: FavoriteItemType,
  itemId: string,
): Promise<Favorite> {
  return request<Favorite>('/api/v1/favorites', {
    method: 'POST',
    body: { item_type: itemType, item_id: itemId },
    fallbackMessage: '收藏失败',
  });
}

export function deleteFavorite(favoriteId: number): Promise<void> {
  return request<void>(`/api/v1/favorites/${favoriteId}`, {
    method: 'DELETE',
    fallbackMessage: '取消收藏失败',
  });
}
