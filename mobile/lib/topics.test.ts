import assert from 'node:assert/strict';
import { test } from 'node:test';

import { KNOWN_TOPICS, topicLabel } from './topics.ts';

test('topicLabel maps every backend topic to a Chinese label', () => {
  assert.equal(topicLabel('model_release'), '模型');
  assert.equal(topicLabel('agent'), 'Agent');
  assert.equal(topicLabel('research'), '研究');
  assert.equal(topicLabel('open_source'), '开源');
  assert.equal(topicLabel('product'), '产品');
  assert.equal(topicLabel('developer_tools'), '开发工具');
  assert.equal(topicLabel('hardware'), '硬件');
  assert.equal(topicLabel('business'), '商业');
  assert.equal(topicLabel('policy'), '政策');
});

test('topicLabel hides the unclassified topic', () => {
  // "other" means the classifier found nothing; showing 其他 says nothing.
  assert.equal(topicLabel('other'), '');
});

test('topicLabel returns nothing for missing or unknown values', () => {
  assert.equal(topicLabel(''), '');
  assert.equal(topicLabel(null), '');
  assert.equal(topicLabel(undefined), '');
  assert.equal(topicLabel('some_future_topic'), '');
});

test('KNOWN_TOPICS lists the full taxonomy', () => {
  assert.equal(KNOWN_TOPICS.length, 10);
  assert.ok(KNOWN_TOPICS.includes('model_release'));
  assert.ok(KNOWN_TOPICS.includes('other'));
});
