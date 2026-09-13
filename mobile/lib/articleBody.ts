/**
 * Presentation helpers for the original article body.
 *
 * The backend stores the body as plain text with blank lines between
 * paragraphs, a leading "#" for headings, "-" for list items and ">" for
 * quotes. Everything here is pure and lives in `lib/` so it can be unit tested;
 * it never rewrites, translates or truncates the article itself.
 */

export type ArticleBlock =
  | { kind: 'heading'; level: number; text: string }
  | { kind: 'list'; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'paragraph'; text: string };

const HEADING_RE = /^(#{1,6})\s+(.*)$/;
const LIST_RE = /^[-*]\s+(.*)$/;
const QUOTE_RE = /^>\s*(.*)$/;

/**
 * Split a stored body into blocks for rendering.
 *
 * Returns an empty array for an empty body so the caller can hide the whole
 * section instead of showing an empty heading.
 */
export function parseArticleBody(body: string | null | undefined): ArticleBlock[] {
  if (!body) {
    return [];
  }

  const blocks: ArticleBlock[] = [];
  for (const raw of body.split(/\n\s*\n+/)) {
    const text = raw.replace(/\s+/g, ' ').trim();
    if (!text) {
      continue;
    }

    const heading = HEADING_RE.exec(text);
    if (heading) {
      blocks.push({ kind: 'heading', level: heading[1].length, text: heading[2].trim() });
      continue;
    }

    const list = LIST_RE.exec(text);
    if (list) {
      blocks.push({ kind: 'list', text: list[1].trim() });
      continue;
    }

    const quote = QUOTE_RE.exec(text);
    if (quote) {
      blocks.push({ kind: 'quote', text: quote[1].trim() });
      continue;
    }

    blocks.push({ kind: 'paragraph', text });
  }
  return blocks;
}

/** Human label for the body's language, shown so the reader is not surprised. */
export function languageLabel(code: string | null | undefined): string {
  switch ((code || '').toLowerCase()) {
    case 'en':
      return '英文原文';
    case 'zh':
      return '中文原文';
    case 'ja':
      return '日文原文';
    case 'ko':
      return '韩文原文';
    case 'ru':
      return '俄文原文';
    default:
      return '原文';
  }
}

/** True when the stored body is the feed's own line or two, not the article. */
export function isSummaryOnly(method: string | null | undefined): boolean {
  return method === 'rss_summary' || method === '' || method == null;
}
