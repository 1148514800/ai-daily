import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { NewsItem } from '../types';
import { formatTime } from '../lib/format';
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
  /** Show the digest rank, for the leading stories. */
  showRank?: boolean;
};

export function NewsCard({ item, onPress, showRank = false }: NewsCardProps) {
  return (
    <Pressable
      onPress={() => onPress(item.id)}
      android_ripple={{ color: colors.overlay }}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.metaRow}>
        <Chip
          label={showRank && item.rank ? `Top ${item.rank}` : CATEGORY_LABEL[item.category]}
          tone={showRank || item.category === 'highlight' ? 'accent' : 'neutral'}
        />
        <Text style={styles.meta}>{item.source}</Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.meta}>{formatTime(item.published_at)}</Text>
      </View>
      <Text style={styles.title} numberOfLines={3}>{item.title_cn}</Text>
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
