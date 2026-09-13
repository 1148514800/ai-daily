import assert from 'node:assert/strict';
import { test } from 'node:test';

import { buildDigestSections } from './digestSections.ts';
import type { NewsItem } from '../types';

function item(id: string, rank: number | null, isTop: boolean | null): NewsItem {
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
    rank,
    rank_score: 70,
    is_top_story: isTop,
  };
}

test('buildDigestSections splits top stories from the rest', () => {
  const sections = buildDigestSections([
    item('a', 1, true),
    item('b', 2, true),
    item('c', 3, false),
  ]);

  assert.deepEqual(
    sections.map((section) => section.key),
    ['top', 'more'],
  );
  assert.deepEqual(
    sections[0].items.map((entry) => entry.id),
    ['a', 'b'],
  );
  assert.deepEqual(
    sections[1].items.map((entry) => entry.id),
    ['c'],
  );
});

test('buildDigestSections never drops or reorders a story', () => {
  const items = [
    item('a', 1, true),
    item('b', 2, false),
    item('c', 3, true),
    item('d', 4, false),
  ];
  const sections = buildDigestSections(items);
  const flattened = sections.flatMap((section) => section.items.map((entry) => entry.id));

  assert.deepEqual([...flattened].sort(), ['a', 'b', 'c', 'd']);
  // Rank order is preserved across the split.
  assert.deepEqual(flattened, ['a', 'c', 'b', 'd']);
});

test('buildDigestSections restores rank order from an unordered payload', () => {
  const sections = buildDigestSections([
    item('c', 3, false),
    item('a', 1, true),
    item('b', 2, true),
  ]);

  assert.deepEqual(
    sections.flatMap((section) => section.items.map((entry) => entry.id)),
    ['a', 'b', 'c'],
  );
});

test('buildDigestSections puts an unflagged digest entirely in more', () => {
  const sections = buildDigestSections([item('a', null, null), item('b', null, null)]);

  assert.deepEqual(
    sections.map((section) => section.key),
    ['more'],
  );
  assert.equal(sections[0].items.length, 2);
});

test('buildDigestSections keeps a fully-top digest in one section', () => {
  const sections = buildDigestSections([item('a', 1, true), item('b', 2, true)]);

  assert.deepEqual(
    sections.map((section) => section.key),
    ['top'],
  );
});

test('buildDigestSections returns nothing for an empty digest', () => {
  assert.deepEqual(buildDigestSections([]), []);
});

test('buildDigestSections sorts unranked items last', () => {
  const sections = buildDigestSections([item('z', null, false), item('a', 1, false)]);

  assert.deepEqual(
    sections[0].items.map((entry) => entry.id),
    ['a', 'z'],
  );
});

test('buildDigestSections treats an explicit false like a missing flag', () => {
  const sections = buildDigestSections([
    item('a', 1, true),
    item('b', 2, false),
    item('c', 3, null),
  ]);
  const more = sections.find((section) => section.key === 'more');

  assert.deepEqual(
    more?.items.map((entry) => entry.id),
    ['b', 'c'],
  );
});
