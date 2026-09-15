import type { NewsContent } from '../types';

/**
 * The detail screen's original-text viewer.
 *
 * Phase 10.11 stopped shipping the article body with the metadata, so opening a
 * story costs one small request and the body is a second one, fetched only when
 * the reader asks for it. The rules that make that pleasant rather than
 * fiddly -- load once per screen, keep the copy when collapsing, offer a retry
 * after a failure -- are a state machine rather than three booleans, so they can
 * be unit tested without rendering anything.
 */
export type ContentStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

export type NewsContentState = {
  /** Where the body is in its lifecycle. */
  status: ContentStatus;
  /** Whether the section is open. Collapsing does not discard the body. */
  expanded: boolean;
  /** The original-language text, empty until a load succeeds. */
  body: string;
  /** BCP-47-ish code for the body, e.g. "en". Empty when unknown. */
  language: string;
  extractionMethod: string;
  quality: string;
  /** The message to show when the load failed. */
  error: string;
  /** True while a request is in flight, so one is never started twice. */
  requesting: boolean;
};

export type NewsContentAction =
  | { type: 'expand' }
  | { type: 'collapse' }
  | { type: 'retry' }
  | { type: 'loadStarted' }
  | { type: 'loadSucceeded'; content: NewsContent }
  | { type: 'loadFailed'; message: string };

export const INITIAL_CONTENT_STATE: NewsContentState = {
  status: 'idle',
  expanded: false,
  body: '',
  language: '',
  extractionMethod: '',
  quality: '',
  error: '',
  requesting: false,
};

export function newsContentReducer(
  state: NewsContentState,
  action: NewsContentAction,
): NewsContentState {
  switch (action.type) {
    case 'expand':
      // Already open: expanding again must not re-request anything.
      if (state.expanded) {
        return state;
      }
      // A body already in hand is re-shown from the local copy, which is what
      // makes collapse -> expand free.
      if (state.status === 'ready' || state.status === 'empty' || state.status === 'error') {
        return { ...state, expanded: true };
      }
      // Nothing loaded yet: open the section and ask for the body.
      return { ...state, expanded: true, status: 'loading', error: '' };

    case 'collapse':
      if (!state.expanded) {
        return state;
      }
      // The text is deliberately kept: re-expanding shows it immediately.
      return { ...state, expanded: false };

    case 'retry':
      // A retry is always an explicit user action on a failed load.
      if (state.status !== 'error') {
        return state;
      }
      return { ...state, expanded: true, status: 'loading', error: '', requesting: false };

    case 'loadStarted':
      if (state.requesting) {
        return state;
      }
      return { ...state, requesting: true, status: 'loading', error: '' };

    case 'loadSucceeded':
      return {
        ...state,
        status: action.content.content_original ? 'ready' : 'empty',
        body: action.content.content_original,
        language: action.content.content_language,
        extractionMethod: action.content.content_extraction_method,
        quality: action.content.content_quality,
        error: '',
        requesting: false,
      };

    case 'loadFailed':
      return {
        ...state,
        status: 'error',
        error: action.message,
        requesting: false,
      };

    default:
      return state;
  }
}

/**
 * Whether the reducer is now waiting for a request nobody has sent.
 *
 * The screen watches this and issues the fetch, which keeps the reducer pure and
 * makes "never request twice" a property of the state rather than of an effect's
 * dependency list.
 */
export function contentRequestNeeded(state: NewsContentState): boolean {
  return state.status === 'loading' && !state.requesting;
}

/** The button's label: what tapping it will do next. */
export function contentButtonLabel(state: NewsContentState): string {
  // Loading wins over "expanded": the section is open with nothing in it yet, so
  // promising "收起原文" would be a lie. The screen disables the button in this
  // state, so the label is a status rather than an action.
  if (state.status === 'loading') {
    return '正在加载原文…';
  }
  if (state.expanded) {
    return '收起原文';
  }
  return '查看原文内容';
}

/**
 * The section heading, from the language label the caller already resolved.
 *
 * The body is shown in the language it was published in and is never
 * translated, so saying which language it is prevents the surprise. The label
 * is passed in rather than looked up here because `lib/articleBody.ts` already
 * owns the language-to-name mapping and this module stays dependency-free.
 */
export function contentSectionTitle(languageName: string): string {
  const label = (languageName || '').trim();
  return !label || label === '原文' ? '原文内容' : `原文内容 · ${label}`;
}

/** The message shown in place of a body that could not be fetched. */
export function contentEmptyMessage(state: NewsContentState): string {
  if (state.status === 'empty') {
    return '这篇内容暂时没有可显示的原文。';
  }
  if (state.status === 'ready' && state.extractionMethod === 'rss_summary') {
    return '未能抓取正文，这里显示的是该来源提供的摘要。';
  }
  return '';
}
