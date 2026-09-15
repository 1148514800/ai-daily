import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { NewsItem } from '../types';
import { formatRelativeTime } from '../lib/relativeTime';
import { sourceBadgeLabel } from '../lib/sourceType';
import { topicLabel } from '../lib/topics';
import { colors, radius, spacing, typography } from '../theme';
import { Chip } from './Chip';

const CATEGORY_LABEL: Record<NewsItem['category'], string> = {
  highlight: '今日重点',
  model: 'AI / 模型',
  opensource: '开源项目',
  tool: 'AI 工具',
};

type NewsCardProps = {
  item: NewsItem;
  onPress: (id: string) => void;
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
  digestDate,
  now,
}: NewsCardProps) {
  const topic = topicLabel(item.topic);
  const time = formatRelativeTime(item.published_at, { digestDate, now });
  // The badge is the backend's `source_type`, never a guess from the source's
  // name: the server owns the classification the ranking is built on.
  const badge = sourceBadgeLabel(item.source_type);

  return (
    <Pressable
      onPress={() => onPress(item.id)}
      android_ripple={{ color: colors.overlay }}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.metaRow}>
        {/* At most one topic tag: a card that shows three labels shows none. */}
        {topic ? (
          <Chip label={topic} tone="accent" />
        ) : (
          <Chip
            label={CATEGORY_LABEL[item.category]}
            tone={item.category === 'highlight' ? 'accent' : 'neutral'}
          />
        )}
        {badge ? <Chip label={badge} /> : null}
        <Text style={styles.meta}>{item.source}</Text>
        {time ? (
          <>
            <Text style={styles.dot}>·</Text>
            <Text style={styles.meta}>{time}</Text>
          </>
        ) : null}
      </View>
      <Text style={styles.title} numberOfLines={3}>
        {item.title_cn}
      </Text>
      {item.summary ? (
        <Text style={styles.summary} numberOfLines={2}>
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
  title: {
    ...typography.subtitle,
    color: colors.text,
    marginBottom: 8,
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
