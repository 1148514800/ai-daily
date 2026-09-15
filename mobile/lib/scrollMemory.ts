/**
 * Where each list was left, so returning to it lands where the reader stopped.
 *
 * Opening a story unmounts the digest list and coming back mounts a fresh one,
 * which would otherwise drop the reader at the top of a list they had scrolled
 * halfway through. A scroll offset is a property of the *list*, not of the
 * component instance, so it is remembered per list key outside React.
 *
 * The store is in-memory on purpose. A scroll offset is a within-session
 * convenience: after an app restart, starting at the top of today's digest is
 * the right default, and nothing here can go stale the way cached content can.
 */

export type ScrollMemory = Map<string, number>;

/** The shared store: one offset per list key. */
const offsets: ScrollMemory = new Map<string, number>();

/**
 * An offset below this is the top of the list.
 *
 * Scroll views round their offsets and report sub-pixel values during a bounce,
 * so "was the reader at the top?" has to tolerate a pixel of noise rather than
 * treating 0.7 as a position worth restoring.
 */
export const SCROLL_TOP_EPSILON = 2;

/**
 * How many times a restore may be re-applied.
 *
 * ``contentSizeChange`` fires as a list grows, and a scroll to an offset beyond
 * the current content is clamped to the end. On the way back the list is briefly
 * short — one screen of cards — so the first attempt can land short of the mark.
 * A handful of retries converges once the real content is laid out; an unbounded
 * loop would fight the reader if they scrolled while it was still trying.
 */
export const SCROLL_RESTORE_ATTEMPTS = 5;

/** Whether another restore attempt is still allowed at this attempt count. */
export function shouldRetryRestore(attempts: number): boolean {
  return attempts < SCROLL_RESTORE_ATTEMPTS;
}

/** Save where a list was left. Offsets at the top are recorded as "no offset". */
export function rememberScrollOffset(memory: ScrollMemory, key: string, offset: number): void {
  if (!key) {
    return;
  }
  if (!Number.isFinite(offset) || offset <= SCROLL_TOP_EPSILON) {
    memory.delete(key);
    return;
  }
  memory.set(key, offset);
}

/** Where a list was left, or 0 when it is at the top. */
export function recallScrollOffset(memory: ScrollMemory, key: string): number {
  const stored = memory.get(key);
  return typeof stored === 'number' && Number.isFinite(stored) && stored > 0 ? stored : 0;
}

/** Drop one key, e.g. for a list whose content changed underneath it. */
export function forgetScrollOffset(memory: ScrollMemory, key: string): void {
  memory.delete(key);
}

/** The shared store, for the screens that remember a position. */
export function scrollMemory(): ScrollMemory {
  return offsets;
}
