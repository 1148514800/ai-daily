import type { NewsItem } from '../types';

/**
 * The digest's reading sections, in the order they are rendered.
 *
 * Phase 10.11 removed 今日必看: the first three stories used to be pulled into a
 * separate "must read" tier on top of the ranking, which meant the same ranking
 * was presented twice and the boundary at rank 3 was arbitrary. There are now
 * two sections and one rule — the server's rank order is the reading order.
 */
export type DigestSectionKey = 'top' | 'more';

export type DigestSection = {
  key: DigestSectionKey;
  title: string;
  caption: string;
  items: NewsItem[];
};

/**
 * Split a digest into 重点新闻 / 更多动态.
 *
 * The backend ranks every story and marks the leading ones with
 * `is_top_story`, so the split is a read of the payload rather than a second
 * opinion: a story the server put in the top ten never moves down because of
 * something counted here. Rank order is preserved (and restored if the payload
 * ever arrives out of order), so both sections read top-down and the whole
 * digest reads 1..N.
 *
 * A digest written before ranking existed has no flags at all. Then there is no
 * top story to call out, and everything goes to 更多动态 in the order given
 * rather than being guessed at on the client.
 */
export function buildDigestSections(news: NewsItem[]): DigestSection[] {
  const ranked = [...news].sort(compareByRank);
  const top = ranked.filter((item) => item.is_top_story === true);
  const more = ranked.filter((item) => item.is_top_story !== true);

  const sections: DigestSection[] = [];
  if (top.length > 0) {
    sections.push({
      key: 'top',
      title: '重点新闻',
      caption: `Top ${top.length}`,
      items: top,
    });
  }
  if (more.length > 0) {
    sections.push({
      key: 'more',
      title: '更多动态',
      caption: `${more.length} 条`,
      items: more,
    });
  }
  return sections;
}

export type DigestOverview = {
  /** Total stories in the digest, every section included. */
  total: number;
  /** How many the digest presents as top stories. */
  topStories: number;
  /** Distinct sources across the digest. */
  sources: number;
  /** Distinct topics, ignoring the unclassified bucket. */
  topics: number;
};

/**
 * The numbers shown in the digest header.
 *
 * Derived entirely from the payload the server already sent, so the overview
 * costs no extra request and cannot disagree with the list below it. Blank and
 * unknown values are skipped instead of being counted as their own source or
 * topic, which would inflate both figures.
 */
export function summarizeDigest(news: NewsItem[]): DigestOverview {
  const sources = new Set<string>();
  const topics = new Set<string>();
  let topStories = 0;

  for (const item of news) {
    if (item.source) {
      sources.add(item.source);
    }
    // `other` means "could not classify", so counting it as a topic would claim
    // coverage the digest does not actually have.
    if (item.topic && item.topic !== 'other') {
      topics.add(item.topic);
    }
    if (item.is_top_story === true) {
      topStories += 1;
    }
  }

  return { total: news.length, topStories, sources: sources.size, topics: topics.size };
}

/** Rank ascending, with unranked items last and a stable id fallback. */
function compareByRank(left: NewsItem, right: NewsItem): number {
  const leftRank = typeof left.rank === 'number' ? left.rank : Number.MAX_SAFE_INTEGER;
  const rightRank = typeof right.rank === 'number' ? right.rank : Number.MAX_SAFE_INTEGER;
  if (leftRank !== rightRank) {
    return leftRank - rightRank;
  }
  return left.id.localeCompare(right.id);
}