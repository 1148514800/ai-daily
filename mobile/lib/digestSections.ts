import type { NewsItem } from '../types';

export type DigestSection = {
  key: 'top' | 'more';
  title: string;
  caption: string;
  items: NewsItem[];
};

/**
 * Split a digest into "重点新闻" and "更多新闻".
 *
 * The backend ranks every story and marks the leading ones with
 * `is_top_story`, so the split is a read, not a re-decision: a story the server
 * put in the top ten never moves into "more" because of something counted
 * here. Rank order is preserved (and restored if the payload ever arrives out
 * of order), so the two sections read top-down.
 *
 * A digest written before ranking existed has no flags at all. Then there is no
 * top story to call out, and everything goes to "更多新闻" in the order given
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
      title: '更多新闻',
      caption: `${more.length} 条`,
      items: more,
    });
  }
  return sections;
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
