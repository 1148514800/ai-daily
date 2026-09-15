import { useCallback, useEffect, useMemo, useRef } from 'react';
import type { NativeScrollEvent, NativeSyntheticEvent, ScrollView } from 'react-native';
import {
  recallScrollOffset,
  rememberScrollOffset,
  scrollMemory,
  shouldRetryRestore,
} from '../lib/scrollMemory';

/** How often scroll offsets are read, in milliseconds (roughly one frame). */
export const SCROLL_EVENT_THROTTLE_MS = 16;

/**
 * Keep a ScrollView's position across a push/pop navigation.
 *
 * The digest list unmounts when a story is opened and mounts again on the way
 * back, so "return to where I was" has to be done explicitly:
 *
 * * the offset to restore is read once, at mount, from the shared memory;
 * * it is applied with a non-animated scrollTo, because content arrives
 *   asynchronously and an animated scroll from the top would be a visible jump;
 * * the first `contentSizeChange` often fires while the list is still shorter
 *   than the target, in which case scrollTo clamps, so a bounded number of
 *   further attempts runs until the position is reached;
 * * the running offset starts at the target rather than at zero, so a reader who
 *   restores and never scrolls again hands the same position back on the way
 *   out instead of forgetting it;
 * * every real scroll overwrites that, and unmounting saves the last one seen.
 *
 * The hook returns props to spread onto the ScrollView. Nothing is stored in
 * component state: a scroll handler that set state would re-render the whole
 * list on every frame.
 */
export function useScrollRestoration(key: string) {
  const ref = useRef<ScrollView>(null);
  const memory = useMemo(() => scrollMemory(), []);
  // Resolved once, so a later save can never change where we restore to.
  const target = useMemo(() => recallScrollOffset(memory, key), [memory, key]);
  // Starts at the target: if nothing ever scrolls, this is what gets saved back.
  const latest = useRef(target);
  const attempts = useRef(0);

  const onScroll = useCallback((event: NativeSyntheticEvent<NativeScrollEvent>) => {
    latest.current = event.nativeEvent.contentOffset.y;
  }, []);

  const onContentSizeChange = useCallback(() => {
    if (target <= 0 || !shouldRetryRestore(attempts.current)) {
      // Nothing to restore, or the list never grew enough to hold the position.
      // Either way the last offset seen is the truth, so nothing is overwritten.
      return;
    }
    attempts.current += 1;
    ref.current?.scrollTo({ y: target, animated: false });
  }, [target]);

  useEffect(() => {
    return () => {
      // Hand the position back on the way out. Saving here rather than inside
      // the scroll handler keeps scrolling stateless, so a flick cannot trigger
      // a re-render of the whole list per frame.
      rememberScrollOffset(memory, key, latest.current);
    };
  }, [memory, key]);

  return {
    ref,
    onScroll,
    onContentSizeChange,
    scrollEventThrottle: SCROLL_EVENT_THROTTLE_MS,
  };
}