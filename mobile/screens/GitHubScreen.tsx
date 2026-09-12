import { ScrollView, StyleSheet, Text } from 'react-native';
import { GitHubCard } from '../components/GitHubCard';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { fetchGithubProjects } from '../services/api';
import { colors, spacing, typography } from '../theme';

export function GitHubScreen() {
  const { status, data, error, reload } = useAsyncResource(fetchGithubProjects);

  return (
    <Screen>
      <StatusState
        loading={status === 'loading'}
        error={status === 'error'}
        empty={status === 'success' && !!data && data.length === 0}
        loadingText="正在加载 GitHub 项目..."
        errorText={error?.message}
        emptyText="暂时没有 GitHub 项目"
        onRetry={reload}
      >
        {data ? (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            <Text style={styles.kicker}>今日热门</Text>
            <Text style={styles.title}>GitHub</Text>
            <Text style={styles.description}>这些项目值得放进本周的观察名单。</Text>
            {data.map((repo) => (
              <GitHubCard key={repo.id} repo={repo} />
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
});
