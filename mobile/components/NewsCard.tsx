import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { NewsItem } from '../types';
import { formatRelativeTime } from '../lib/relativeTime';
import { topicLabel } from '../lib/topics';
import { colors, radius, spacing, typography } from '../theme';
import { Chip } from './Chip';

const CATEGORY_LABEL: Record<NewsItem['category'], string> = {
  highlight: '今日重点',
  model: 'AI / 模型',
  opensource: '开源项目',
  tool: 'AI 工具',
};

/**
 * ``must_read`` is the landing-page treatment for the first few stories: a
 * larger title, a longer summary and a rank marker, so the top of the digest is
 * scannable in a few seconds without becoming a different kind of card.
 */
export type NewsCardVariant = 'default' | 'must_read';

type NewsCardProps = {
  item: NewsItem;
  onPress: (id: string) => void;
  variant?: NewsCardVariant;
  /**
   * The digest's date, used to decide whether relative wording ("2小时前") is
   * honest. A past digest is labelled absolutely so it never says "刚刚".
   */
  digestDate?: string | null;
  /** The instant to measure against. Defaults to now; fixed in tests. */
  now?: Date;
};

export function NewsCard({
  item,
  onPress,
  variant = 'default',
  digestDate,
  now,
}: NewsCardProps) {
  const mustRead = variant === 'must_read';
  const topic = topicLabel(item.topic);
  const time = formatRelativeTime(item.published_at, { digestDate, now });

  return (
    <Pressable
      onPress={() => onPress(item.id)}
      android_ripple={{ color: colors.overlay }}
      style={({ pressed }) => [
        styles.card,
        mustRead && styles.mustReadCard,
        pressed && styles.pressed,
      ]}
    >
      <View style={styles.metaRow}>
        {mustRead && item.rank ? (
          <Text style={styles.rankMark}>#{item.rank}</Text>
        ) : null}
        {/* At most one topic tag: a card that shows three labels shows none. */}
        {topic ? (
          <Chip label={topic} tone="accent" />
        ) : (
          <Chip
            label={CATEGORY_LABEL[item.category]}
            tone={item.category === 'highlight' ? 'accent' : 'neutral'}
          />
        )}
        <Text style={styles.meta}>{item.source}</Text>
        {time ? (
          <>
            <Text style={styles.dot}>·</Text>
            <Text style={styles.meta}>{time}</Text>
          </>
        ) : null}
      </View>
      <Text style={[styles.title, mustRead && styles.mustReadTitle]} numberOfLines={mustRead ? 4 : 3}>
        {item.title_cn}
      </Text>
      {item.summary ? (
        <Text style={styles.summary} numberOfLines={mustRead ? 3 : 2}>
          {item.summary}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.border,
    marginBottom: spacing.sm,
  },
  mustReadCard: {
    padding: spacing.md + 2,
    borderColor: colors.accentSoft,
    borderLeftWidth: 3,
    borderLeftColor: colors.accent,
    marginBottom: spacing.md,
  },
  pressed: {
    opacity: 0.92,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: spacing.sm,
  },
  rankMark: {
    ...typography.subtitle,
    fontSize: 15,
    color: colors.accent,
  },
  title: {
    ...typography.subtitle,
    color: colors.text,
    marginBottom: 8,
  },
  mustReadTitle: {
    ...typography.title,
    fontSize: 19,
    lineHeight: 27,
  },
  summary: {
    ...typography.body,
    fontSize: 15,
    lineHeight: 24,
    color: colors.textSecondary,
  },
  meta: {
    ...typography.meta,
    color: colors.textTertiary,
  },
  dot: {
    color: colors.textTertiary,
  },
});
