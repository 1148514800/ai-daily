import { Pressable, ScrollView, StyleSheet, Text } from 'react-native';
import { Screen } from '../components/Screen';
import { getHistoryDigests } from '../data/digests';
import { formatLongDate } from '../lib/format';
import { colors, radius, spacing, typography } from '../theme';

type HistoryScreenProps = {
  onOpenDigest: (date: string) => void;
};

export function HistoryScreen({ onOpenDigest }: HistoryScreenProps) {
  const items = getHistoryDigests();

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.kicker}>往期回顾</Text>
        <Text style={styles.title}>历史日报</Text>
        <Text style={styles.description}>点击某一天，查看当天的静态日报。</Text>

        {items.map((digest) => (
          <Pressable
            key={digest.date}
            onPress={() => onOpenDigest(digest.date)}
            android_ripple={{ color: colors.overlay }}
            style={({ pressed }) => [styles.card, pressed && styles.pressed]}
          >
            <Text style={styles.date}>{formatLongDate(digest.date)}</Text>
            <Text style={styles.cardTitle}>{digest.title}</Text>
            <Text style={styles.caption}>{digest.description}</Text>
            <Text style={styles.highlight} numberOfLines={2}>
              {digest.highlight}
            </Text>
          </Pressable>
        ))}
      </ScrollView>
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
