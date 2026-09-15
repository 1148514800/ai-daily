import type { NewsItem } from '../types';

/**
 * The source class a story came from, as the backend reports it.
 *
 * These strings are the backend's `source_type` values verbatim: the client
 * never infers a type from a source's name, because the name is a display label
 * ("Hugging Face", "Ars Technica") and the class is a ranking input the server
 * owns. Anything unrecognised returns null so the card renders no badge rather
 * than a wrong one.
 */
export type SourceClass = 'official' | 'research' | 'media';

const LABELS: Record<SourceClass, string> = {
  official: '官方',
  research: '研究',
  media: '媒体',
};

const KNOWN: readonly SourceClass[] = ['official', 'research', 'media'];

export function sourceClass(sourceType: string | null | undefined): SourceClass | null {
  const value = (sourceType || '').trim().toLowerCase();
  return (KNOWN as readonly string[]).includes(value) ? (value as SourceClass) : null;
}

/** The badge text for a source type, or null when there is nothing to show. */
export function sourceBadgeLabel(sourceType: string | null | undefined): string | null {
  const value = sourceClass(sourceType);
  return value ? LABELS[value] : null;
}