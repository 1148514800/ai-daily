import { ScrollView, StyleSheet, Text, View } from 'react-native';
import { GitHubCard } from '../components/GitHubCard';
import { NewsCard } from '../components/NewsCard';
import { Screen } from '../components/Screen';
import { SectionHeader } from '../components/SectionHeader';
import { favoriteNews, favoriteRepos } from '../data/favorites';
import { colors, spacing, typography } from '../theme';

type FavoritesScreenProps = {
  onOpenNews: (id: string) => void;
};

export function FavoritesScreen({ onOpenNews }: FavoritesScreenProps) {
  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.kicker}>稍后阅读</Text>
        <Text style={styles.title}>收藏</Text>
        <Text style={styles.description}>本阶段使用静态 mock 数据，不会写入本地存储。</Text>

        <SectionHeader title="新闻" caption={`${favoriteNews.length} 条`} />
        {favoriteNews.map((item) => (
          <NewsCard key={item.id} item={item} onPress={onOpenNews} />
        ))}

        <View>
          <SectionHeader title="GitHub 项目" caption={`${favoriteRepos.length} 个`} />
          {favoriteRepos.map((repo) => (
            <GitHubCard key={repo.id} repo={repo} />
          ))}
        </View>
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
  },
});
