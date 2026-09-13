import type { SearchResultItem } from '../types';

/** How long typing must pause before a search is sent. */
export const SEARCH_DEBOUNCE_MS = 300;
/** How many results one page holds. The backend caps this too. */
export const SEARCH_PAGE_SIZE = 20;

/**
 * The state the search screen is in, derived from the query and the response.
 *
 * Empty is its own state, not "zero results": before anything is typed the
 * screen should invite a search, and it must never quietly load the whole
 * archive as a default result set.
 */
export type SearchPhase = 'idle' | 'searching' | 'results' | 'empty';

export function searchPhase(
  query: string,
  state: { loading: boolean; hasResults: boolean },
): SearchPhase {
  if (!query.trim()) {
    return 'idle';
  }
  if (state.loading) {
    return 'searching';
  }
  return state.hasResults ? 'results' : 'empty';
}

/**
 * The date to show for a result: the digest it appeared in, or the day it was
 * published when it never reached one.
 *
 * An article can be stored before any digest covers it (its timestamp is still
 * ahead of every window), so ``digest_date`` is legitimately null. Falling back
 * to ``published_at`` keeps the row dated rather than blank, and the caller
 * only ever formats a ``YYYY-MM-DD``.
 */
export function resultDate(item: SearchResultItem): string | null {
  if (item.digest_date) {
    return item.digest_date;
  }
  const published = item.published_at;
  if (!published) {
    return null;
  }
  return published.slice(0, 10);
}

/** The text a result row shows under its title. */
export function resultExcerpt(item: SearchResultItem): string {
  return item.snippet || item.summary || '';
}
