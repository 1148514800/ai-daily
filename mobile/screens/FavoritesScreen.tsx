import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { GitHubCard } from '../components/GitHubCard';
import { NewsCard } from '../components/NewsCard';
import { Screen } from '../components/Screen';
import { SectionHeader } from '../components/SectionHeader';
import { StatusState } from '../components/StatusState';
import { useFavorites } from '../hooks/useFavorites';
import { colors, spacing, typography } from '../theme';
import type { GitHubProject, NewsItem } from '../types';

type FavoritesScreenProps = {
  onOpenNews: (id: string) => void;
};

export function FavoritesScreen({ onOpenNews }: FavoritesScreenProps) {
  const { status, error, favorites, reload } = useFavorites();

  const news = favorites
    .filter((favorite) => favorite.item_type === 'news')
    .map((favorite) => favorite.item as NewsItem);
  const repos = favorites
    .filter((favorite) => favorite.item_type === 'github')
    .map((favorite) => favorite.item as GitHubProject);

  return (
    <Screen>
      <StatusState
        loading={status === 'loading'}
        error={status === 'error'}
        empty={status === 'success' && favorites.length === 0}
        loadingText="正在加载收藏..."
        errorText={error ?? '收藏加载失败'}
        emptyText="还没有收藏。打开一条新闻或 GitHub 项目，点击收藏即可保存。"
        onRetry={reload}
      >
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <Text style={styles.kicker}>稍后阅读</Text>
          <Text style={styles.title}>收藏</Text>
          <Text style={styles.description}>收藏保存在后端数据库，重启后仍然存在。</Text>

          {news.length ? (
            <>
              <SectionHeader title="新闻" caption={`${news.length} 条`} />
              {news.map((item) => (
                <NewsCard key={item.id} item={item} onPress={onOpenNews} />
              ))}
            </>
          ) : null}

          {repos.length ? (
            <View>
              <SectionHeader title="GitHub 项目" caption={`${repos.length} 个`} />
              {repos.map((repo) => (
                <GitHubCard key={repo.id} repo={repo} />
              ))}
            </View>
          ) : null}
        </ScrollView>
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
    marginBottom: spacing.sm,
  },
});
