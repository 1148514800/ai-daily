import { Alert, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { BackHeader } from '../components/BackHeader';
import { Chip } from '../components/Chip';
import { FavoriteButton } from '../components/FavoriteButton';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { SUMMARY_FALLBACK, displayKeyPoints, publishedLabel } from '../lib/readingView';
import { sourceBadgeLabel } from '../lib/sourceType';
import { topicLabel } from '../lib/topics';
import { fetchNews } from '../services/api';
import { colors, radius, spacing, typography } from '../theme';

type NewsDetailScreenProps = {
  newsId: string;
  onBack: () => void;
};

/**
 * One article as a Chinese reading page.
 *
 * Phase 10.12 removed the original-text viewer on purpose. AI Daily is a Chinese
 * briefing about what changed in AI, not an RSS reader, so this screen shows the
 * LLM's grounded Chinese interpretation — 发生了什么 / 核心信息 / 为什么重要 —
 * and links out to the source for anyone who wants the article itself. The
 * backend still stores the original body for search and re-summarising; the app
 * simply never asks for it, which is also why opening a story costs one small
 * request.
 */
export function NewsDetailScreen({ newsId, onBack }: NewsDetailScreenProps) {
  const { status, data, error, reload } = useAsyncResource(() => fetchNews(newsId), [newsId]);
  const notFound = status === 'error' && error?.status === 404;
  const keyPoints = data ? displayKeyPoints(data) : [];
  const badge = data ? sourceBadgeLabel(data.source_type) : null;
  const topic = data ? topicLabel(data.topic) : '';
  const published = data ? publishedLabel(data.published_at) : '';

  async function openSource() {
    if (!data) {
      return;
    }
    try {
      await Linking.openURL(data.url);
    } catch {
      Alert.alert('查看来源', '这是占位链接，本阶段不访问真实页面。');
    }
  }

  return (
    <Screen>
      <BackHeader title="AI 解读" onBack={onBack} />
      <StatusState
        loading={status === 'loading'}
        error={status === 'error' && !notFound}
        empty={notFound}
        loadingText="正在加载解读..."
        errorText={error?.message}
        emptyText="没有找到这条内容。"
        onRetry={notFound ? undefined : reload}
      >
        {data ? (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            <Text style={styles.title}>{data.title_cn}</Text>
            {data.title_original ? (
              <Text style={styles.original}>{data.title_original}</Text>
            ) : null}
            {/* 来源 · 发布时间 · Topic, in that order, so the line answers
                "who says this, when, and about what" before the reading starts. */}
            <View style={styles.metaRow}>
              {badge ? <Chip label={badge} /> : null}
              <Text style={styles.meta}>
                {[data.source, published, topic].filter(Boolean).join('  ·  ')}
              </Text>
            </View>

            <Text style={styles.sectionLabel}>发生了什么？</Text>
            <Text style={styles.body}>{data.summary || SUMMARY_FALLBACK}</Text>

            {/* An article summarised before key_points existed has no bullets,
                and a heading over nothing would promise information that is not
                there, so the whole section is skipped. */}
            {keyPoints.length ? (
              <>
                <Text style={styles.sectionLabel}>核心信息</Text>
                <View style={styles.pointList}>
                  {keyPoints.map((point, index) => (
                    <View key={`${index}-${point}`} style={styles.pointRow}>
                      <Text style={styles.pointBullet}>·</Text>
                      <Text style={styles.pointText}>{point}</Text>
                    </View>
                  ))}
                </View>
              </>
            ) : null}

            {data.why_it_matters ? (
              <>
                <Text style={styles.sectionLabel}>为什么重要？</Text>
                <View style={styles.whyBox}>
                  <Text style={styles.body}>{data.why_it_matters}</Text>
                </View>
              </>
            ) : null}

            <View style={styles.actions}>
              <FavoriteButton itemType="news" itemId={data.id} />
            </View>

            <Pressable
              onPress={openSource}
              android_ripple={{ color: colors.overlay }}
              style={({ pressed }) => [styles.button, pressed && styles.pressed]}
            >
              <Text style={styles.buttonText}>查看来源</Text>
            </Pressable>
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
  title: {
    ...typography.title,
    color: colors.text,
  },
  original: {
    marginTop: spacing.sm,
    fontSize: 15,
    lineHeight: 24,
    color: colors.textTertiary,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: spacing.sm,
  },
  meta: {
    ...typography.meta,
    color: colors.textSecondary,
  },
  sectionLabel: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '600',
    color: colors.textTertiary,
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
  },
  body: {
    ...typography.body,
    color: colors.text,
  },
  pointList: {
    gap: spacing.sm,
  },
  pointRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 8,
  },
  pointBullet: {
    ...typography.body,
    color: colors.accent,
    lineHeight: 26,
  },
  pointText: {
    ...typography.body,
    color: colors.text,
    flex: 1,
  },
  whyBox: {
    backgroundColor: colors.overlay,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  actions: {
    marginTop: spacing.xl,
  },
  button: {
    marginTop: spacing.md,
    backgroundColor: colors.text,
    borderRadius: radius.md,
    paddingVertical: 14,
    alignItems: 'center',
  },
  pressed: {
    opacity: 0.9,
  },
  buttonText: {
    color: colors.surface,
    fontSize: 16,
    fontWeight: '600',
  },
});
