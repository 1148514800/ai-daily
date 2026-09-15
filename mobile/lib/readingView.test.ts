import assert from 'node:assert/strict';
import { test } from 'node:test';

import { SUMMARY_FALLBACK, displayKeyPoints, publishedLabel } from './readingView.ts';

test('displayKeyPoints returns nothing when the article has no points', () => {
  assert.deepEqual(displayKeyPoints({}), []);
  assert.deepEqual(displayKeyPoints({ key_points: [] }), []);
  assert.deepEqual(displayKeyPoints({ key_points: undefined }), []);
});

test('displayKeyPoints keeps the backend order', () => {
  const points = ['发布方：Cohere', '模型：North Small Translate', '许可：开源权重'];

  assert.deepEqual(displayKeyPoints({ key_points: points }), points);
});

test('displayKeyPoints drops blanks and duplicates', () => {
  const points = ['发布方：Cohere', '   ', '', '发布方：Cohere', '许可：开源权重'];

  assert.deepEqual(displayKeyPoints({ key_points: points }), [
    '发布方：Cohere',
    '许可：开源权重',
  ]);
});

test('displayKeyPoints trims the surrounding whitespace of a bullet', () => {
  assert.deepEqual(displayKeyPoints({ key_points: ['  发布时间：今天  '] }), ['发布时间：今天']);
});

test('a malformed payload degrades to no bullets rather than throwing', () => {
  // The field is typed as a list, but a client must survive a server that sends
  // null or a bare string: the screen omits the section instead of crashing.
  assert.deepEqual(displayKeyPoints({ key_points: null as unknown as string[] }), []);
  assert.deepEqual(displayKeyPoints({ key_points: '一句话' as unknown as string[] }), []);
});

test('the summary fallback is the wording the screen shows', () => {
  assert.equal(SUMMARY_FALLBACK, '这条内容暂时没有摘要。');
});

test('publishedLabel renders the absolute moment in APP_TIMEZONE', () => {
  // 2026-09-15T00:02:11Z is 08:02 on the 15th in Asia/Shanghai, a Tuesday.
  assert.equal(publishedLabel('2026-09-15T00:02:11+00:00'), '9月15日 周二 08:02');
});

test('publishedLabel uses the local day, not the UTC day', () => {
  // 17:30Z is already the 16th in Asia/Shanghai.
  assert.equal(publishedLabel('2026-09-15T17:30:00+00:00'), '9月16日 周三 01:30');
});

test('publishedLabel returns nothing for a missing or broken timestamp', () => {
  assert.equal(publishedLabel(''), '');
  assert.equal(publishedLabel(null), '');
  assert.equal(publishedLabel(undefined), '');
  assert.equal(publishedLabel('不是时间'), '');
});
