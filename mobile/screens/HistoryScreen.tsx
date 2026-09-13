import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useDigestHistory } from '../hooks/useDigestHistory';
import { formatShortDateWithWeekday } from '../lib/format';
import { isTodayInAppTimezone } from '../lib/relativeTime';
import { colors, radius, spacing, typography } from '../theme';

type HistoryScreenProps = {
  onOpenDigest: (date: string) => void;
};

export function HistoryScreen({ onOpenDigest }: HistoryScreenProps) {
  const { status, summaries, error, reload } = useDigestHistory();

  return (
    <Screen>
      <StatusState
        loading={status === 'loading'}
        error={status === 'error'}
        empty={status === 'success' && summaries.length === 0}
        loadingText="正在加载历史日报..."
        errorText={error?.message}
        emptyText="暂无历史日报"
        onRetry={reload}
      >
        {summaries.length ? (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            <Text style={styles.kicker}>往期回顾</Text>
            <Text style={styles.title}>历史日报</Text>
            <Text style={styles.description}>点击某一天，查看当天的日报内容。</Text>

            {summaries.map((digest) => (
              <Pressable
                key={digest.date}
                onPress={() => onOpenDigest(digest.date)}
                android_ripple={{ color: colors.overlay }}
                style={({ pressed }) => [styles.card, pressed && styles.pressed]}
              >
                <Text style={styles.cardTitle}>
                  {formatShortDateWithWeekday(digest.date)}
                  {isTodayInAppTimezone(digest.date) ? ' · 今天' : ''}
                </Text>
                <Text style={styles.caption}>
                  {digest.news_count} 条新闻
                  {digest.top_story_count ? ` · ${digest.top_story_count} 条重点` : ''}
                  {digest.github_count ? ` · GitHub ${digest.github_count} 个` : ''}
                </Text>
              </Pressable>
            ))}
          </ScrollView>
        ) : null}
      </StatusState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  kicker: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
  title: {
    ...typography.display,
    color: colors.text,
    marginTop: 8,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  pressed: {
    opacity: 0.92,
  },
  cardTitle: {
    ...typography.subtitle,
    fontSize: 17,
    color: colors.text,
  },
  caption: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: 4,
  },
});
