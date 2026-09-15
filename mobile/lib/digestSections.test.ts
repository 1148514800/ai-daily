import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildDigestSections, summarizeDigest } from './digestSections.ts';
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

function digest(count: number): NewsItem[] {
  return Array.from({ length: count }, (_, index) =>
    item(`n${index + 1}`, {
      rank: index + 1,
      // The backend marks the leading ten; the rest are still returned.
      is_top_story: index < 10,
    }),
  );
}

function keys(sections: ReturnType<typeof buildDigestSections>): string[] {
  return sections.map((section) => section.key);
}

// --- sections ---

test('buildDigestSections no longer has a must-read tier', () => {
  const sections = buildDigestSections(digest(18));

  // Phase 10.11 removed 今日必看: the ranking is presented once, not twice.
  assert.deepEqual(keys(sections), ['top', 'more']);
  assert.ok(!sections.some((section) => (section.key as string) === 'must_read'));
  assert.ok(!sections.some((section) => section.title === '今日必看'));
});

test('buildDigestSections puts every top story in one section', () => {
  const sections = buildDigestSections(digest(18));
  const top = sections.find((section) => section.key === 'top');

  assert.equal(top?.items.length, 10);
  assert.equal(top?.title, '重点新闻');
});

test('buildDigestSections keeps the remaining stories in more', () => {
  const sections = buildDigestSections(digest(18));
  const more = sections.find((section) => section.key === 'more');

  assert.equal(more?.items.length, 8);
  assert.equal(more?.title, '更多动态');
});

test('buildDigestSections keeps every story exactly once', () => {
  const sections = buildDigestSections(digest(18));
  const ids = sections.flatMap((section) => section.items.map((entry) => entry.id));

  assert.equal(ids.length, 18);
  assert.equal(new Set(ids).size, 18);
});

test('buildDigestSections reads top-down without a second split', () => {
  const sections = buildDigestSections(digest(18));
  const ranks = sections.flatMap((section) => section.items.map((entry) => entry.rank));

  // One continuous ranking: 1..18, with no story pulled out of order.
  assert.deepEqual(ranks, Array.from({ length: 18 }, (_, index) => index + 1));
});

test('buildDigestSections handles a digest shorter than ten', () => {
  const sections = buildDigestSections([
    item('a', { rank: 1, is_top_story: true }),
    item('b', { rank: 2, is_top_story: true }),
    item('c', { rank: 3, is_top_story: true }),
  ]);

  assert.deepEqual(keys(sections), ['top']);
  assert.equal(sections[0].items.length, 3);
});

test('buildDigestSections omits an empty section rather than rendering a heading', () => {
  const sections = buildDigestSections([item('a', { rank: 1, is_top_story: true })]);

  assert.deepEqual(keys(sections), ['top']);
});

test('buildDigestSections returns nothing for an empty digest', () => {
  assert.deepEqual(buildDigestSections([]), []);
});

test('buildDigestSections puts an unflagged digest entirely in more', () => {
  // A digest written before ranking existed has no top story to call out.
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

test('buildDigestSections sorts unranked items last without regrouping them', () => {
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
    item('a', { source: 'Cohere' }),
    item('b', { source: 'Cohere' }),
    item('c', { source: 'Cohere' }),
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