import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  resultDate,
  resultExcerpt,
  searchPhase,
  SEARCH_DEBOUNCE_MS,
  SEARCH_PAGE_SIZE,
} from './search.ts';
import type { SearchResultItem } from '../types';

function item(extra: Partial<SearchResultItem> = {}): SearchResultItem {
  return {
    news_id: 'rss-1',
    title_cn: '标题',
    original_title: 'Title',
    summary: '',
    source: 'OpenAI',
    published_at: '2026-09-10T02:00:00+00:00',
    digest_date: '2026-09-10',
    topic: 'model_release',
    company: 'OpenAI',
    snippet: '',
    ...extra,
  };
}

// --- phases ---

test('an empty query is idle, not an empty result set', () => {
  // The screen must invite a search rather than loading the whole archive.
  assert.equal(searchPhase('', { loading: false, hasResults: false }), 'idle');
  assert.equal(searchPhase('   ', { loading: false, hasResults: false }), 'idle');
});

test('an empty query stays idle even while a previous request is in flight', () => {
  assert.equal(searchPhase('', { loading: true, hasResults: true }), 'idle');
});

test('a pending query is searching', () => {
  assert.equal(searchPhase('DeepSeek', { loading: true, hasResults: false }), 'searching');
});

test('a query with hits shows results', () => {
  assert.equal(searchPhase('DeepSeek', { loading: false, hasResults: true }), 'results');
});

test('a query without hits shows the empty state', () => {
  assert.equal(searchPhase('zzzz', { loading: false, hasResults: false }), 'empty');
});

// --- result presentation ---

test('resultDate prefers the digest the article appeared in', () => {
  assert.equal(resultDate(item({ digest_date: '2026-09-12' })), '2026-09-12');
});

test('resultDate falls back to the publication day when there is no digest', () => {
  // A future article has not been linked to any digest yet.
  const dated = item({ digest_date: null, published_at: '2026-09-14T08:00:00+00:00' });

  assert.equal(resultDate(dated), '2026-09-14');
});

test('resultDate returns nothing when there is no usable date', () => {
  assert.equal(resultDate(item({ digest_date: null, published_at: '' })), null);
  assert.equal(resultDate(item({ digest_date: null, published_at: undefined as never })), null);
});

test('resultExcerpt prefers the snippet and falls back to the summary', () => {
  assert.equal(resultExcerpt(item({ snippet: '…DeepSeek V4…' })), '…DeepSeek V4…');
  assert.equal(resultExcerpt(item({ snippet: '', summary: '一段摘要' })), '一段摘要');
  assert.equal(resultExcerpt(item({ snippet: '', summary: '' })), '');
});

// --- constants ---

test('search debounce keeps typing from firing a request per keystroke', () => {
  assert.equal(SEARCH_DEBOUNCE_MS, 300);
});

test('the page size stays within what the backend allows', () => {
  assert.ok(SEARCH_PAGE_SIZE > 0 && SEARCH_PAGE_SIZE <= 50);
});
