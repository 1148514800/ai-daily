import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  MUST_READ_LIMIT,
  buildDigestSections,
  summarizeDigest,
} from './digestSections.ts';
import type { NewsItem } from '../types';

type Extra = Partial<Pick<NewsItem, 'rank' | 'is_top_story' | 'source' | 'topic' | 'company'>>;

function item(id: string, extra: Extra = {}): NewsItem {
  return {
    id,
    title_cn: `标题 ${id}`,
    title_original: `Title ${id}`,
    summary: '',
    why_it_matters: '',
    source: 'OpenAI',
    source_type: 'official',
    published_at: '2026-09-13T00:00:00+00:00',
    category: 'highlight',
    tags: ['OpenAI'],
    url: `https://example.com/${id}`,
    importance_score: 50,
    rank: null,
    rank_score: null,
    is_top_story: null,
    topic: '',
    company: '',
    ...extra,
  };
}

/** A digest with `total` stories, the first ten marked as top stories. */
function digest(total: number): NewsItem[] {
  return Array.from({ length: total }, (_, index) => {
    const rank = index + 1;
    const isTop = rank <= 10;
    return item(`n${rank}`, { rank, is_top_story: isTop });
  });
}

function keys(sections: { key: string }[]): string[] {
  return sections.map((section) => section.key);
}

// --- the three tiers ---

test('buildDigestSections puts ranks 1-3 in must read', () => {
  const sections = buildDigestSections(digest(18));
  const mustRead = sections.find((section) => section.key === 'must_read');

  assert.deepEqual(
    mustRead?.items.map((entry) => entry.id),
    ['n1', 'n2', 'n3'],
  );
});

test('buildDigestSections puts ranks 4-10 in top stories', () => {
  const sections = buildDigestSections(digest(18));
  const top = sections.find((section) => section.key === 'top');

  assert.deepEqual(
    top?.items.map((entry) => entry.id),
    ['n4', 'n5', 'n6', 'n7', 'n8', 'n9', 'n10'],
  );
});

test('buildDigestSections puts rank 11 and beyond in more', () => {
  const sections = buildDigestSections(digest(18));
  const more = sections.find((section) => section.key === 'more');

  assert.equal(more?.items.length, 8);
  assert.equal(more?.items[0].id, 'n11');
});

test('buildDigestSections keeps every story across the three tiers', () => {
  const sections = buildDigestSections(digest(18));
  const flattened = sections.flatMap((section) => section.items.map((entry) => entry.id));

  assert.deepEqual(flattened, Array.from({ length: 18 }, (_, index) => `n${index + 1}`));
});

test('buildDigestSections splits at the documented boundary', () => {
  assert.equal(MUST_READ_LIMIT, 3);
  const sections = buildDigestSections(digest(11));
  const byKey = Object.fromEntries(sections.map((section) => [section.key, section.items.length]));

  assert.deepEqual(byKey, { must_read: 3, top: 7, more: 1 });
});

// --- short digests ---

test('buildDigestSections handles a digest shorter than three', () => {
  const sections = buildDigestSections([
    item('a', { rank: 1, is_top_story: true }),
    item('b', { rank: 2, is_top_story: true }),
  ]);

  assert.deepEqual(keys(sections), ['must_read']);
  assert.equal(sections[0].items.length, 2);
});

test('buildDigestSections handles a digest shorter than ten', () => {
  const sections = buildDigestSections([
    item('a', { rank: 1, is_top_story: true }),
    item('b', { rank: 2, is_top_story: true }),
    item('c', { rank: 3, is_top_story: true }),
    item('d', { rank: 4, is_top_story: true }),
  ]);

  assert.deepEqual(keys(sections), ['must_read', 'top']);
  assert.equal(sections[1].items.length, 1);
});

test('buildDigestSections omits an empty section rather than rendering a heading', () => {
  // Exactly three top stories and nothing else: only "must read" exists.
  const sections = buildDigestSections([
    item('a', { rank: 1, is_top_story: true }),
    item('b', { rank: 2, is_top_story: true }),
    item('c', { rank: 3, is_top_story: true }),
  ]);

  assert.deepEqual(keys(sections), ['must_read']);
});

test('buildDigestSections marks exactly the first three as must read, never more', () => {
  // Guards the boundary from the other side: a fourth top story must not creep
  // into the landing tier just because it is also flagged.
  const sections = buildDigestSections(digest(10));
  const mustRead = sections.find((section) => section.key === 'must_read');
  const top = sections.find((section) => section.key === 'top');

  assert.equal(mustRead?.items.length, MUST_READ_LIMIT);
  assert.equal(top?.items.length, 7);
  assert.ok(!mustRead?.items.some((entry) => entry.rank === 4));
});

test('buildDigestSections never duplicates a story between tiers', () => {
  const sections = buildDigestSections(digest(20));
  const ids = sections.flatMap((section) => section.items.map((entry) => entry.id));

  assert.equal(new Set(ids).size, ids.length);
});

test('buildDigestSections handles a digest with no more news', () => {
  const sections = buildDigestSections(digest(10));

  assert.deepEqual(keys(sections), ['must_read', 'top']);
});

test('buildDigestSections returns nothing for an empty digest', () => {
  assert.deepEqual(buildDigestSections([]), []);
});

test('buildDigestSections puts an unflagged digest entirely in more', () => {
  const sections = buildDigestSections([item('a'), item('b')]);

  assert.deepEqual(keys(sections), ['more']);
});

// --- ordering ---

test('buildDigestSections restores rank order from an unordered payload', () => {
  const sections = buildDigestSections([
    item('c', { rank: 3, is_top_story: true }),
    item('a', { rank: 1, is_top_story: true }),
    item('b', { rank: 2, is_top_story: true }),
  ]);

  assert.deepEqual(
    sections[0].items.map((entry) => entry.id),
    ['a', 'b', 'c'],
  );
});

test('buildDigestSections sorts unranked items last', () => {
  const sections = buildDigestSections([item('z'), item('a', { rank: 1, is_top_story: true })]);

  assert.deepEqual(
    sections[0].items.map((entry) => entry.id),
    ['a'],
  );
  assert.deepEqual(
    sections[1].items.map((entry) => entry.id),
    ['z'],
  );
});

// --- overview ---

test('summarizeDigest counts total, top stories, sources and topics', () => {
  const overview = summarizeDigest([
    item('a', { is_top_story: true, source: 'OpenAI', topic: 'model_release' }),
    item('b', { is_top_story: true, source: 'OpenAI', topic: 'agent' }),
    item('c', { is_top_story: false, source: 'Anthropic', topic: 'model_release' }),
  ]);

  assert.deepEqual(overview, { total: 3, topStories: 2, sources: 2, topics: 2 });
});

test('summarizeDigest counts a repeated source once', () => {
  const overview = summarizeDigest([
    item('a', { source: '量子位' }),
    item('b', { source: '量子位' }),
    item('c', { source: '量子位' }),
  ]);

  assert.equal(overview.sources, 1);
});

test('summarizeDigest counts a repeated topic once', () => {
  const overview = summarizeDigest([
    item('a', { topic: 'research' }),
    item('b', { topic: 'research' }),
  ]);

  assert.equal(overview.topics, 1);
});

test('summarizeDigest ignores the unclassified topic', () => {
  const overview = summarizeDigest([
    item('a', { topic: 'other' }),
    item('b', { topic: 'research' }),
  ]);

  assert.equal(overview.topics, 1);
});

test('summarizeDigest ignores blank sources and topics', () => {
  const overview = summarizeDigest([
    item('a', { source: '', topic: '' }),
    item('b', { source: 'OpenAI', topic: 'research' }),
  ]);

  assert.equal(overview.sources, 1);
  assert.equal(overview.topics, 1);
});

test('summarizeDigest handles an empty digest', () => {
  assert.deepEqual(summarizeDigest([]), {
    total: 0,
    topStories: 0,
    sources: 0,
    topics: 0,
  });
});
