import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  SCROLL_RESTORE_ATTEMPTS,
  SCROLL_TOP_EPSILON,
  forgetScrollOffset,
  recallScrollOffset,
  rememberScrollOffset,
  scrollMemory,
  shouldRetryRestore,
} from './scrollMemory.ts';
import type { ScrollMemory } from './scrollMemory.ts';

function memory(): ScrollMemory {
  return new Map<string, number>();
}

test('a saved offset comes back for the same list', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', 1240);

  assert.equal(recallScrollOffset(store, 'today'), 1240);
});

test('each list remembers its own position', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', 1240);
  rememberScrollOffset(store, 'digest:2026-09-12', 300);

  assert.equal(recallScrollOffset(store, 'today'), 1240);
  assert.equal(recallScrollOffset(store, 'digest:2026-09-12'), 300);
});

test('an unknown list restores to the top', () => {
  assert.equal(recallScrollOffset(memory(), 'today'), 0);
});

test('an offset at the top is stored as nothing to restore', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', 900);
  rememberScrollOffset(store, 'today', 0);

  // Returning to the top means the next visit legitimately starts at the top,
  // not that the old position should be restored.
  assert.equal(recallScrollOffset(store, 'today'), 0);
  assert.equal(store.size, 0);
});

test('sub-pixel rounding at the top counts as the top', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', SCROLL_TOP_EPSILON);

  assert.equal(recallScrollOffset(store, 'today'), 0);
});

test('a used position is kept, not the rounding noise above it', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', SCROLL_TOP_EPSILON + 0.5);

  assert.equal(recallScrollOffset(store, 'today'), SCROLL_TOP_EPSILON + 0.5);
});

test('a broken offset never overwrites a good one', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', 640);
  rememberScrollOffset(store, 'today', Number.NaN);

  assert.equal(recallScrollOffset(store, 'today'), 0);
});

test('an empty key is ignored rather than pooled under one entry', () => {
  const store = memory();
  rememberScrollOffset(store, '', 500);

  assert.equal(store.size, 0);
  assert.equal(recallScrollOffset(store, ''), 0);
});

test('forgetting one list leaves the others alone', () => {
  const store = memory();
  rememberScrollOffset(store, 'today', 100);
  rememberScrollOffset(store, 'digest:2026-09-12', 200);
  forgetScrollOffset(store, 'today');

  assert.equal(recallScrollOffset(store, 'today'), 0);
  assert.equal(recallScrollOffset(store, 'digest:2026-09-12'), 200);
});

test('restore attempts are bounded', () => {
  assert.equal(shouldRetryRestore(0), true);
  assert.equal(shouldRetryRestore(SCROLL_RESTORE_ATTEMPTS - 1), true);
  assert.equal(shouldRetryRestore(SCROLL_RESTORE_ATTEMPTS), false);
  assert.equal(shouldRetryRestore(SCROLL_RESTORE_ATTEMPTS + 10), false);
});

test('the screens share one store, so a position survives an unmount', () => {
  const first = scrollMemory();
  rememberScrollOffset(first, 'today', 777);

  // A second call stands in for the remounted screen reading the same module.
  assert.equal(recallScrollOffset(scrollMemory(), 'today'), 777);
  forgetScrollOffset(scrollMemory(), 'today');
});