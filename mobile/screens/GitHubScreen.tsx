import { ScrollView, StyleSheet, Text } from 'react-native';
import { GitHubCard } from '../components/GitHubCard';
import { Screen } from '../components/Screen';
import { githubRepos } from '../data/github';
import { colors, spacing, typography } from '../theme';

export function GitHubScreen() {
  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.kicker}>今日热门</Text>
        <Text style={styles.title}>GitHub</Text>
        <Text style={styles.description}>这些项目值得放进本周的观察名单，数据为本地 mock。</Text>
        {githubRepos.map((repo) => (
          <GitHubCard key={repo.id} repo={repo} />
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
});
