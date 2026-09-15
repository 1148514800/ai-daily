import assert from 'node:assert/strict';
import { test } from 'node:test';

import { sourceBadgeLabel, sourceClass } from './sourceType.ts';

test('sourceBadgeLabel maps the three backend source types to Chinese labels', () => {
  assert.equal(sourceBadgeLabel('official'), '官方');
  assert.equal(sourceBadgeLabel('research'), '研究');
  assert.equal(sourceBadgeLabel('media'), '媒体');
});

test('sourceBadgeLabel labels the sources the backend actually serves', () => {
  // The mapping is by class, not by name: Mistral and Hugging Face are both
  // labelled from their own source_type, whatever they are called.
  for (const sourceType of ['official', 'research', 'media']) {
    assert.ok(sourceBadgeLabel(sourceType));
  }
});

test('sourceBadgeLabel ignores case and surrounding whitespace', () => {
  assert.equal(sourceBadgeLabel('  Official '), '官方');
  assert.equal(sourceBadgeLabel('MEDIA'), '媒体');
});

test('sourceBadgeLabel shows nothing for a missing or unknown type', () => {
  // A missing badge is better than a wrong one: the client cannot classify.
  assert.equal(sourceBadgeLabel(''), null);
  assert.equal(sourceBadgeLabel(null), null);
  assert.equal(sourceBadgeLabel(undefined), null);
  assert.equal(sourceBadgeLabel('blog'), null);
  assert.equal(sourceBadgeLabel('unknown'), null);
});

test('sourceClass returns the canonical value the label is built from', () => {
  assert.equal(sourceClass('official'), 'official');
  assert.equal(sourceClass('Research'), 'research');
  assert.equal(sourceClass('nope'), null);
});