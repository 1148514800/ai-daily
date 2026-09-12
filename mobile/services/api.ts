import type {
  DailyDigest,
  DigestSummary,
  Favorite,
  FavoriteItemType,
  GitHubProject,
  NewsItem,
  RefreshStatus,
} from '../types';
import { apiBaseUrl } from './config';

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

/**
 * Request budget. Without this, a host that silently drops packets (a phone on
 * the wrong Wi-Fi, a laptop that changed IP) leaves the UI stuck on "loading"
 * until the OS TCP timeout, which can take minutes.
 */
const REQUEST_TIMEOUT_MS = 12000;

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, fallbackMessage = '内容加载失败' } = options;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method,
      headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new ApiError('连接 AI Daily 服务超时，请检查后端地址与网络', 0);
    }
    throw new ApiError('无法连接 AI Daily 服务，请检查后端地址与网络', 0);
  } finally {
    clearTimeout(timer);
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

export function fetchRefreshStatus(): Promise<RefreshStatus> {
  return request<RefreshStatus>('/api/v1/refresh/status');
}
