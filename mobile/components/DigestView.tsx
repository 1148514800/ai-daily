import { ScrollView, StyleSheet, Text, View } from 'react-native';
import type { ReactNode } from 'react';
import type { DailyDigest, NewsItem } from '../types';
import { useScrollRestoration } from '../hooks/useScrollRestoration';
import { formatLongDate } from '../lib/format';
import { buildDigestSections, summarizeDigest } from '../lib/digestSections';
import { colors, spacing, typography } from '../theme';
import { GitHubCard } from './GitHubCard';
import { NewsCard } from './NewsCard';
import { SectionHeader } from './SectionHeader';

type DigestViewProps = {
  digest: DailyDigest;
  onOpenNews: (id: string) => void;
  showFinishedHint?: boolean;
  /**
   * The heading to show. Falls back to the digest's stored title so a caller
   * that does not care about today/历史 wording still renders something sane.
   */
  heading?: string;
  /** Rendered under the overview: the date navigation for an open digest. */
  footerNav?: ReactNode;
  /** Rendered just after the heading, e.g. a hint that this is not today. */
  headerNote?: ReactNode;
  /**
   * Identifies this list for scroll restoration. Opening a story unmounts the
   * list, so the position is remembered per key and restored on the way back —
   * today's digest, a specific day's digest and the favourites list each keep
   * their own.
   */
  scrollKey?: string;
};

export function DigestView({
  digest,
  onOpenNews,
  showFinishedHint = true,
  heading,
  footerNav,
  headerNote,
  scrollKey,
}: DigestViewProps) {
  // The server ranks the digest and marks the leading stories, so the split
  // into 重点新闻 / 更多动态 is a read of the payload rather than a second
  // opinion. Every story is rendered in the server's order: the lower-ranked
  // ones are not dropped, they just sit further down, and each card carries its
  // own source-class badge instead of being regrouped by source.
  const sections = buildDigestSections(digest.news);
  const overview = summarizeDigest(digest.news);
  const github = digest.github_projects ?? [];
  // The hook still runs without a key, but never remembers anything: a caller
  // that does not opt in gets a plain ScrollView.
  const scroll = useScrollRestoration(scrollKey ?? '');

  return (
    <ScrollView
      contentContainerStyle={styles.content}
      showsVerticalScrollIndicator={false}
      {...scroll}
    >
      <Text style={styles.date}>{formatLongDate(digest.date)}</Text>
      <Text style={styles.title}>{heading ?? digest.title}</Text>
      {headerNote}
      {/* The overview is computed from the payload, so it cannot disagree with
          the list below it and costs no extra request. */}
      <Text style={styles.count}>今日收录 {overview.total} 条 AI 动态</Text>
      <Text style={styles.overview}>
        精选 {overview.topStories} 条重点新闻
        {overview.sources ? ` · ${overview.sources} 个来源` : ''}
        {overview.topics ? ` · ${overview.topics} 个话题` : ''}
      </Text>

      {sections.map((section) => (
        <View key={section.key}>
          <SectionHeader title={section.title} caption={section.caption} />
          {section.items.map((item: NewsItem) => (
            <NewsCard
              key={item.id}
              item={item}
              onPress={onOpenNews}
              digestDate={digest.date}
            />
          ))}
        </View>
      ))}

      {/* A day with no GitHub projects simply omits the section rather than
          showing an empty heading. */}
      {github.length ? (
        <View>
          <SectionHeader title="GitHub Trending" caption={`${github.length} 个`} />
          {github.map((repo) => (
            <GitHubCard key={repo.id} repo={repo} />
          ))}
        </View>
      ) : null}

      {showFinishedHint && overview.total > 0 ? (
        <View style={styles.finished}>
          <Text style={styles.finishedText}>今日已读完</Text>
        </View>
      ) : null}

      {footerNav}
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
  overview: {
    ...typography.meta,
    color: colors.textTertiary,
    marginTop: 6,
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
