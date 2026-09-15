import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  INITIAL_CONTENT_STATE,
  contentButtonLabel,
  contentEmptyMessage,
  contentRequestNeeded,
  contentSectionTitle,
  newsContentReducer,
  type NewsContentState,
} from './newsContent.ts';
import type { NewsContent } from '../types';

const BODY = 'Cohere released North Small Translate today.\n\nThe model is open-weight.';

function content(overrides: Partial<NewsContent> = {}): NewsContent {
  return {
    news_id: 'rss-1',
    content_original: BODY,
    content_language: 'en',
    content_extraction_method: 'web',
    content_quality: 'good',
    ...overrides,
  };
}

/** Drive the reducer the way the screen does, including the request effect. */
function expand(state: NewsContentState, payload: NewsContent | Error): NewsContentState {
  let next = newsContentReducer(state, { type: 'expand' });
  if (contentRequestNeeded(next)) {
    next = newsContentReducer(next, { type: 'loadStarted' });
    next =
      payload instanceof Error
        ? newsContentReducer(next, { type: 'loadFailed', message: payload.message })
        : newsContentReducer(next, { type: 'loadSucceeded', content: payload });
  }
  return next;
}

// --- default state ---

test('the original text is hidden and unrequested to begin with', () => {
  assert.equal(INITIAL_CONTENT_STATE.expanded, false);
  assert.equal(INITIAL_CONTENT_STATE.status, 'idle');
  assert.equal(contentRequestNeeded(INITIAL_CONTENT_STATE), false);
});

test('the button invites the original text before anything is loaded', () => {
  assert.equal(contentButtonLabel(INITIAL_CONTENT_STATE), '查看原文内容');
});

// --- expand / collapse ---

test('expanding starts a request instead of showing the body', () => {
  const opened = newsContentReducer(INITIAL_CONTENT_STATE, { type: 'expand' });

  assert.equal(opened.expanded, true);
  assert.equal(opened.status, 'loading');
  assert.equal(opened.body, '');
  assert.equal(contentRequestNeeded(opened), true);
});

test('a successful load shows the body and stops asking for it', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content());

  assert.equal(shown.status, 'ready');
  assert.equal(shown.expanded, true);
  assert.equal(shown.body, BODY);
  assert.equal(shown.language, 'en');
  assert.equal(shown.extractionMethod, 'web');
  assert.equal(shown.quality, 'good');
  assert.equal(contentRequestNeeded(shown), false);
});

test('collapsing hides the body without discarding it', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content());
  const closed = newsContentReducer(shown, { type: 'collapse' });

  assert.equal(closed.expanded, false);
  assert.equal(closed.body, BODY);
  assert.equal(closed.status, 'ready');
});

test('re-expanding uses the local copy and never requests again', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content());
  const closed = newsContentReducer(shown, { type: 'collapse' });
  const reopened = newsContentReducer(closed, { type: 'expand' });

  assert.equal(reopened.expanded, true);
  assert.equal(reopened.body, BODY);
  // The whole point: the screen sees no reason to fetch anything.
  assert.equal(contentRequestNeeded(reopened), false);
  assert.equal(contentButtonLabel(reopened), '收起原文');
});

test('collapsing while loading does not cancel or restart the request', () => {
  const loading = newsContentReducer(INITIAL_CONTENT_STATE, { type: 'expand' });
  const inFlight = newsContentReducer(loading, { type: 'loadStarted' });
  const closed = newsContentReducer(inFlight, { type: 'collapse' });
  const reopened = newsContentReducer(closed, { type: 'expand' });

  assert.equal(reopened.status, 'loading');
  assert.equal(contentRequestNeeded(reopened), false);
});

test('expanding an already open section changes nothing', () => {
  const opened = newsContentReducer(INITIAL_CONTENT_STATE, { type: 'expand' });
  assert.equal(newsContentReducer(opened, { type: 'expand' }), opened);
});

// --- failure ---

test('a failed load is visible and offers a retry', () => {
  const failed = expand(INITIAL_CONTENT_STATE, new Error('原文加载失败'));

  assert.equal(failed.status, 'error');
  assert.equal(failed.expanded, true);
  assert.equal(failed.error, '原文加载失败');
  assert.equal(failed.body, '');
});

test('retrying goes back to loading and asks for the body again', () => {
  const failed = expand(INITIAL_CONTENT_STATE, new Error('boom'));
  const retried = newsContentReducer(failed, { type: 'retry' });

  assert.equal(retried.status, 'loading');
  assert.equal(retried.error, '');
  assert.equal(contentRequestNeeded(retried), true);
});

test('retrying a load that did not fail is ignored', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content());
  assert.equal(newsContentReducer(shown, { type: 'retry' }), shown);
});

test('a failure after a success keeps the retry path honest', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content());
  const failed = newsContentReducer(shown, { type: 'loadFailed', message: '网络中断' });

  assert.equal(failed.status, 'error');
  assert.equal(failed.error, '网络中断');
  // The failed section stays open so the retry is reachable, and the toggle
  // still says what it will do: close the section.
  assert.equal(failed.expanded, true);
  assert.equal(contentButtonLabel(failed), '收起原文');
  // The retry is what fetches again, not the toggle.
  assert.equal(contentRequestNeeded(failed), false);
});

test('a load already in flight is never started twice', () => {
  const inFlight = newsContentReducer(
    newsContentReducer(INITIAL_CONTENT_STATE, { type: 'expand' }),
    { type: 'loadStarted' },
  );
  const again = newsContentReducer(inFlight, { type: 'loadStarted' });

  assert.equal(again, inFlight);
  assert.equal(contentRequestNeeded(again), false);
});

// --- empty state ---

test('an article with no stored body is an empty state, not an error', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content({ content_original: '' }));

  assert.equal(shown.status, 'empty');
  assert.equal(shown.expanded, true);
  assert.equal(contentEmptyMessage(shown), '这篇内容暂时没有可显示的原文。');
});

test('a body that is only the feed summary says so', () => {
  const shown = expand(
    INITIAL_CONTENT_STATE,
    content({ content_extraction_method: 'rss_summary', content_quality: 'low' }),
  );

  assert.equal(shown.status, 'ready');
  assert.equal(
    contentEmptyMessage(shown),
    '未能抓取正文，这里显示的是该来源提供的摘要。',
  );
});

test('a real body carries no notice', () => {
  const shown = expand(INITIAL_CONTENT_STATE, content());
  assert.equal(contentEmptyMessage(shown), '');
});

// --- labels ---

test('the section heading names the language the body is in', () => {
  // The caller resolves the code to a name via lib/articleBody's languageLabel,
  // so this only decides how the heading is worded.
  assert.equal(contentSectionTitle('英文原文'), '原文内容 · 英文原文');
  assert.equal(contentSectionTitle('中文原文'), '原文内容 · 中文原文');
  assert.equal(contentSectionTitle(''), '原文内容');
  assert.equal(contentSectionTitle('原文'), '原文内容');
  assert.equal(contentSectionTitle(null as unknown as string), '原文内容');
});

test('the button label tracks the state', () => {
  const loading = newsContentReducer(INITIAL_CONTENT_STATE, { type: 'expand' });
  assert.equal(contentButtonLabel(loading), '正在加载原文…');

  const shown = expand(INITIAL_CONTENT_STATE, content());
  assert.equal(contentButtonLabel(shown), '收起原文');
  assert.equal(contentButtonLabel(newsContentReducer(shown, { type: 'collapse' })), '查看原文内容');
});

test('an unknown action leaves the state alone', () => {
  const state = newsContentReducer(INITIAL_CONTENT_STATE, { type: 'nonsense' } as never);
  assert.deepEqual(state, INITIAL_CONTENT_STATE);
});
