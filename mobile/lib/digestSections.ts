import type { NewsItem } from '../types';

/**
 * How many leading stories get the most prominent treatment.
 *
 * This is a reading-experience choice, not a ranking one: the server decides
 * the order and which stories are top stories (`is_top_story`, the top ten),
 * and the client only decides how much visual weight the first few get. The
 * value is deliberately separate from the server's `TOP_STORY_LIMIT` so the
 * landing page can change without touching the ranking contract.
 */
export const MUST_READ_LIMIT = 3;

/** Section keys, in reading order. */
export type DigestSectionKey = 'must_read' | 'top' | 'more';

export type DigestSection = {
  key: DigestSectionKey;
  title: string;
  caption: string;
  items: NewsItem[];
};

/**
 * Split a digest into 今日必看 / 重点新闻 / 更多动态.
 *
 * The backend ranks every story and marks the leading ones with
 * `is_top_story`, so the split is a read, not a re-decision: a story the server
 * put in the top ten never moves into "more" because of something counted
 * here. Rank order is preserved (and restored if the payload ever arrives out
 * of order), so the two sections read top-down.
 *
 * A digest written before ranking existed has no flags at all. Then there is no
 * top story to call out, and everything goes to 更多动态 in the order given
 * rather than being guessed at on the client.
 */
export function buildDigestSections(news: NewsItem[]): DigestSection[] {
  const ranked = [...news].sort(compareByRank);
  const marked = ranked.filter((item) => item.is_top_story === true);
  const more = ranked.filter((item) => item.is_top_story !== true);
  const mustRead = marked.slice(0, MUST_READ_LIMIT);
  const top = marked.slice(MUST_READ_LIMIT);

  const sections: DigestSection[] = [];
  if (mustRead.length > 0) {
    sections.push({
      key: 'must_read',
      title: '今日必看',
      caption: `Top ${mustRead.length}`,
      items: mustRead,
    });
  }
  if (top.length > 0) {
    sections.push({
      key: 'top',
      title: '重点新闻',
      caption: `${top.length} 条`,
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
