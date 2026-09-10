import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { GitHubProject } from '../types';
import { formatStars, formatStarsDelta } from '../lib/format';
import { colors, radius, spacing, typography } from '../theme';

type GitHubCardProps = {
  repo: GitHubProject;
  onPress?: (id: string) => void;
};

export function GitHubCard({ repo, onPress }: GitHubCardProps) {
  const content = (
    <>
      <View style={styles.topRow}>
        <Text style={styles.name}>{repo.repo}</Text>
      </View>
      <Text style={styles.description}>{repo.description}</Text>
      <View style={styles.statsRow}>
        <Text style={styles.stat}>{repo.language}</Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.stat}>{formatStars(repo.stars)} stars</Text>
        <Text style={styles.dot}>·</Text>
        <Text style={styles.delta}>{formatStarsDelta(repo.stars_delta)}</Text>
      </View>
      <Text style={styles.summary}>{repo.summary_cn}</Text>
      <View style={styles.whyBox}>
        <Text style={styles.whyLabel}>为什么值得关注</Text>
        <Text style={styles.whyText}>{repo.why_it_matters}</Text>
      </View>
    </>
  );

  if (!onPress) {
    return <View style={styles.card}>{content}</View>;
  }

  return (
    <Pressable
      onPress={() => onPress(repo.id)}
      android_ripple={{ color: colors.overlay }}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      {content}
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
    marginBottom: spacing.md,
  },
  pressed: {
    opacity: 0.92,
  },
  topRow: {
    marginBottom: 8,
  },
  name: {
    ...typography.subtitle,
    color: colors.text,
  },
  description: {
    ...typography.meta,
    color: colors.textTertiary,
    marginBottom: spacing.sm,
  },
  statsRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: spacing.sm,
  },
  stat: {
    ...typography.meta,
    color: colors.textSecondary,
  },
  delta: {
    ...typography.meta,
    color: colors.accent,
    fontWeight: '600',
  },
  dot: {
    color: colors.textTertiary,
  },
  summary: {
    fontSize: 15,
    lineHeight: 24,
    color: colors.textSecondary,
    marginBottom: spacing.sm,
  },
  whyBox: {
    backgroundColor: colors.overlay,
    borderRadius: radius.sm,
    padding: spacing.sm,
  },
  whyLabel: {
    fontSize: 12,
    lineHeight: 16,
    color: colors.textTertiary,
    marginBottom: 4,
  },
  whyText: {
    fontSize: 14,
    lineHeight: 22,
    color: colors.text,
  },
});
