import type { FavoriteItem } from '../types';
import { getNewsByIds } from './news';
import { getReposByIds } from './github';

export const favoriteItems: FavoriteItem[] = [
  { id: 'fav-news-1', kind: 'news', newsId: 'n-20260910-01' },
  { id: 'fav-news-2', kind: 'news', newsId: 'n-20260910-08' },
  { id: 'fav-news-3', kind: 'news', newsId: 'n-20260908-01' },
  { id: 'fav-gh-1', kind: 'github', repoId: 'gh-llama-cpp' },
  { id: 'fav-gh-2', kind: 'github', repoId: 'gh-vllm' },
];

export function getFavoriteNews() {
  return getNewsByIds(
    favoriteItems.filter((item) => item.kind === 'news').map((item) => item.newsId),
  );
}

export function getFavoriteRepos() {
  return getReposByIds(
    favoriteItems.filter((item) => item.kind === 'github').map((item) => item.repoId),
  );
}
