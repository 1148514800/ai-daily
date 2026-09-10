import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { formatLongDate } from '../lib/format';
import { ApiError, fetchDailyByDate, fetchTodayDaily, previousDates } from '../services/api';
import { colors, radius, spacing, typography } from '../theme';
import type { DailyDigest } from '../types';

type HistoryScreenProps = {
  onOpenDigest: (date: string) => void;
};

async function fetchHistoryDigests(): Promise<DailyDigest[]> {
  const today = await fetchTodayDaily();
  const dates = previousDates(today.date, 3);
  const results = await Promise.all(
    dates.map(async (date) => {
      try {
        return await fetchDailyByDate(date);
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
          return null;
        }
        throw error;
      }
    }),
  );
  return results.filter((item): item is DailyDigest => item !== null);
}

export function HistoryScreen({ onOpenDigest }: HistoryScreenProps) {
  const { status, data, reload } = useAsyncResource(fetchHistoryDigests);

  return (
    <Screen>
      <StatusState
        loading={status === 'loading'}
        error={status === 'error'}
        empty={status === 'success' && !!data && data.length === 0}
        loadingText="正在加载历史日报..."
        emptyText="暂时没有历史日报"
        onRetry={reload}
      >
        {data ? (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            <Text style={styles.kicker}>往期回顾</Text>
            <Text style={styles.title}>历史日报</Text>
            <Text style={styles.description}>点击某一天，查看当天的日报。</Text>

            {data.map((digest) => (
              <Pressable
                key={digest.date}
                onPress={() => onOpenDigest(digest.date)}
                android_ripple={{ color: colors.overlay }}
                style={({ pressed }) => [styles.card, pressed && styles.pressed]}
              >
                <Text style={styles.date}>{formatLongDate(digest.date)}</Text>
                <Text style={styles.cardTitle}>{digest.title}</Text>
                <Text style={styles.caption}>精选 {digest.news.length} 条动态</Text>
                <Text style={styles.highlight} numberOfLines={2}>
                  {digest.description}
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
  date: {
    ...typography.meta,
    color: colors.textTertiary,
  },
  cardTitle: {
    ...typography.subtitle,
    color: colors.text,
    marginTop: 6,
  },
  caption: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: 6,
  },
  highlight: {
    fontSize: 15,
    lineHeight: 24,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
});
