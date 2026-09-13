import { useMemo } from 'react';
import { findNeighbours, sortByDateDesc } from '../lib/digestHistory';
import { fetchDigests } from '../services/api';
import type { DigestSummary } from '../types';
import { useAsyncResource } from './useAsyncResource';

/**
 * The stored digest list, plus the neighbours of one date within it.
 *
 * Both the Today screen and an open digest need to know what comes before and
 * after, and neither should re-implement "previous/next over real digests".
 * Loading the list once here keeps that rule in one place.
 */
export function useDigestHistory(date?: string) {
  const { status, data, error, reload } = useAsyncResource(fetchDigests);
  const summaries: DigestSummary[] = useMemo(
    () => sortByDateDesc(data ?? []),
    [data],
  );
  const neighbours = useMemo(
    () => (date ? findNeighbours(summaries.map((s) => s.date), date) : null),
    [summaries, date],
  );

  return { status, summaries, error, reload, neighbours };
}
