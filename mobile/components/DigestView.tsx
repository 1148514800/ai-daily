import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { DailyDigest, NewsCategory, NewsItem } from '../types';
import { formatLongDate } from '../lib/format';
import { colors, spacing, typography } from '../theme';
import { NewsCard } from './NewsCard';
import { SectionHeader } from './SectionHeader';

const SECTIONS: { category: NewsCategory; title: string }[] = [
  { category: 'highlight', title: '今日重点' },
  { category: 'model', title: 'AI / 模型' },
  { category: 'opensource', title: '开源项目' },
  { category: 'tool', title: 'AI 工具' },
];

type DigestViewProps = {
  digest: DailyDigest;
  onOpenNews: (id: string) => void;
  showFinishedHint?: boolean;
};

export function DigestView({ digest, onOpenNews, showFinishedHint = true }: DigestViewProps) {
  return (
    <ScrollView
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <Text style={styles.date}>{formatLongDate(digest.date)}</Text>
      <Text style={styles.title}>{digest.title}</Text>
      <Text style={styles.count}>今日精选 {digest.news.length} 条 AI 动态</Text>
      <Text style={styles.description}>{digest.description}</Text>

      {SECTIONS.map((section) => {
        const items = digest.news.filter((item) => item.category === section.category);
        if (items.length === 0) {
          return null;
        }
        return (
          <View key={section.category}>
            <SectionHeader title={section.title} caption={`${items.length} 条`} />
            {items.map((item: NewsItem) => (
              <NewsCard key={item.id} item={item} onPress={onOpenNews} />
            ))}
          </View>
        );
      })}

      {showFinishedHint ? (
        <View style={styles.finished}>
          <Text style={styles.finishedText}>今日已读完</Text>
        </View>
      ) : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  date: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
  title: {
    ...typography.display,
    color: colors.text,
    marginTop: 8,
  },
  count: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
  description: {
    ...typography.body,
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.sm,
  },
  finished: {
    alignItems: 'center',
    paddingVertical: spacing.xl,
  },
  finishedText: {
    fontSize: 14,
    color: colors.textTertiary,
  },
});
