import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { DailyDigest, NewsItem } from '../types';
import { formatLongDate } from '../lib/format';
import { buildDigestSections } from '../lib/digestSections';
import { colors, spacing, typography } from '../theme';
import { NewsCard } from './NewsCard';
import { SectionHeader } from './SectionHeader';
import { UpdateHint } from './UpdateHint';

type DigestViewProps = {
  digest: DailyDigest;
  onOpenNews: (id: string) => void;
  showFinishedHint?: boolean;
};

export function DigestView({ digest, onOpenNews, showFinishedHint = true }: DigestViewProps) {
  // The server ranks the digest and marks the leading stories, so the split
  // into 重点新闻 / 更多新闻 is a read of `is_top_story` rather than a second
  // opinion. Every story is rendered: the lower-ranked ones are not dropped,
  // they just sit under 更多新闻.
  const sections = buildDigestSections(digest.news);

  return (
    <ScrollView
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
    >
      <Text style={styles.date}>{formatLongDate(digest.date)}</Text>
      <Text style={styles.title}>{digest.title}</Text>
      <Text style={styles.count}>今日精选 {digest.news.length} 条 AI 动态</Text>
      <Text style={styles.description}>{digest.description}</Text>
      <UpdateHint />

      {sections.map((section) => (
        <View key={section.key}>
          <SectionHeader title={section.title} caption={section.caption} />
          {section.items.map((item: NewsItem) => (
            <NewsCard
              key={item.id}
              item={item}
              onPress={onOpenNews}
              showRank={section.key === 'top'}
            />
          ))}
        </View>
      ))}

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
