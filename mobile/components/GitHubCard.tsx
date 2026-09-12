import { Alert, Linking, Pressable, StyleSheet, Text, View } from 'react-native';
import type { GitHubProject } from '../types';
import { FavoriteButton } from './FavoriteButton';
import { formatStars, formatStarsDelta } from '../lib/format';
import { colors, radius, spacing, typography } from '../theme';

type GitHubCardProps = {
  repo: GitHubProject;
  onPress?: (id: string) => void;
};

export function GitHubCard({ repo, onPress }: GitHubCardProps) {
  async function openGithub() {
    try {
      await Linking.openURL(repo.url);
    } catch {
      Alert.alert('GitHub', '无法打开该仓库链接。');
    }
  }

  const delta = formatStarsDelta(repo.stars_delta);
  const summary = repo.summary_cn || repo.description;

  const content = (
    <>
      <View style={styles.topRow}>
        <Text style={styles.name}>{repo.repo}</Text>
      </View>
      <View style={styles.statsRow}>
        {repo.language ? <Text style={styles.stat}>{repo.language}</Text> : null}
        {repo.language ? <Text style={styles.dot}>·</Text> : null}
        <Text style={styles.stat}>⭐ {formatStars(repo.stars)}</Text>
        {delta ? (
          <>
            <Text style={styles.dot}>·</Text>
            <Text style={styles.delta}>{delta}</Text>
          </>
        ) : null}
      </View>
      {summary ? <Text style={styles.summary}>{summary}</Text> : null}
      {repo.why_it_matters ? (
        <View style={styles.whyBox}>
          <Text style={styles.whyLabel}>为什么值得关注</Text>
          <Text style={styles.whyText}>{repo.why_it_matters}</Text>
        </View>
      ) : null}
      <View style={styles.actions}>
        <FavoriteButton itemType="github" itemId={repo.id} />
      </View>
      <Pressable
        onPress={openGithub}
        android_ripple={{ color: colors.overlay }}
        style={({ pressed }) => [styles.button, pressed && styles.pressed]}
      >
        <Text style={styles.buttonText}>查看 GitHub</Text>
      </Pressable>
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
    marginBottom: spacing.sm,
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
  actions: {
    marginBottom: spacing.sm,
  },
  button: {
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 10,
    alignItems: 'center',
  },
  buttonText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
});
