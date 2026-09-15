import { useEffect, useReducer } from 'react';
import { ActivityIndicator, Alert, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { BackHeader } from '../components/BackHeader';
import { Chip } from '../components/Chip';
import { FavoriteButton } from '../components/FavoriteButton';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { languageLabel, parseArticleBody } from '../lib/articleBody';
import {
  INITIAL_CONTENT_STATE,
  contentButtonLabel,
  contentEmptyMessage,
  contentRequestNeeded,
  contentSectionTitle,
  newsContentReducer,
} from '../lib/newsContent';
import { formatTime } from '../lib/format';
import { sourceBadgeLabel } from '../lib/sourceType';
import { fetchNews, fetchNewsContent } from '../services/api';
import { colors, radius, spacing, typography } from '../theme';

type NewsDetailScreenProps = {
  newsId: string;
  onBack: () => void;
};

/**
 * One article, with its original text behind a button.
 *
 * The layout is the summary first — title, source, time, 中文摘要, Why it
 * matters — and the article body only after 查看原文内容 is tapped. Phase 10.11
 * moved the body to its own request, so opening a story no longer downloads a
 * whole article: the metadata response arrives, the reader decides whether they
 * want the original, and only then is the text fetched. The body is fetched at
 * most once per visit; collapsing and re-expanding re-uses the copy in hand.
 */
export function NewsDetailScreen({ newsId, onBack }: NewsDetailScreenProps) {
  const { status, data, error, reload } = useAsyncResource(() => fetchNews(newsId), [newsId]);
  const notFound = status === 'error' && error?.status === 404;
  const [content, dispatch] = useReducer(newsContentReducer, INITIAL_CONTENT_STATE);

  // The reducer decides that a request is needed; the screen issues it. Keeping
  // the decision in the reducer is what makes "never request the same body
  // twice" a property of the state rather than of an effect's dependency list.
  useEffect(() => {
    if (!contentRequestNeeded(content)) {
      return;
    }
    let cancelled = false;
    dispatch({ type: 'loadStarted' });
    fetchNewsContent(newsId)
      .then((payload) => {
        if (!cancelled) {
          dispatch({ type: 'loadSucceeded', content: payload });
        }
      })
      .catch((thrown: unknown) => {
        if (!cancelled) {
          const message =
            thrown instanceof Error && thrown.message ? thrown.message : '原文加载失败，请稍后重试';
          dispatch({ type: 'loadFailed', message });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [newsId, content]);

  const badge = data ? sourceBadgeLabel(data.source_type) : null;
  const body = parseArticleBody(content.body);
  const emptyMessage = contentEmptyMessage(content);

  async function openOriginal() {
    if (!data) {
      return;
    }
    try {
      await Linking.openURL(data.url);
    } catch {
      Alert.alert('查看原文', '这是占位链接，本阶段不访问真实页面。');
    }
  }

  return (
    <Screen>
      <BackHeader title="新闻详情" onBack={onBack} />
      <StatusState
        loading={status === 'loading'}
        error={status === 'error' && !notFound}
        empty={notFound}
        loadingText="正在加载新闻详情..."
        errorText={error?.message}
        emptyText="没有找到这条内容。"
        onRetry={notFound ? undefined : reload}
      >
        {data ? (
          <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
            <Text style={styles.title}>{data.title_cn}</Text>
            <Text style={styles.original}>{data.title_original}</Text>
            <View style={styles.metaRow}>
              {badge ? <Chip label={badge} /> : null}
              <Text style={styles.meta}>
                {data.source}  ·  {data.published_at.slice(0, 10)} {formatTime(data.published_at)}
              </Text>
            </View>

            <Text style={styles.sectionLabel}>中文摘要</Text>
            <Text style={styles.body}>{data.summary || '原文暂无摘要。'}</Text>

            {data.why_it_matters ? (
              <View style={styles.whyBox}>
                <Text style={styles.sectionLabel}>为什么值得关注</Text>
                <Text style={styles.body}>{data.why_it_matters}</Text>
              </View>
            ) : null}

            {data.tags.length ? (
              <View style={styles.tags}>
                {data.tags.map((tag) => (
                  <Chip key={tag} label={tag} />
                ))}
              </View>
            ) : null}

            {/*
              The original text is opt-in. The button always exists so the reader
              knows whether there is anything to read: 查看原文内容 before the
              first load, 收起原文 while it is open.
            */}
            <Pressable
              onPress={() => dispatch({ type: content.expanded ? 'collapse' : 'expand' })}
              android_ripple={{ color: colors.overlay }}
              disabled={content.status === 'loading'}
              style={({ pressed }) => [
                styles.originalButton,
                pressed && styles.pressed,
                content.status === 'loading' && styles.disabled,
              ]}
            >
              {content.status === 'loading' ? (
                <ActivityIndicator color={colors.text} size="small" />
              ) : null}
              <Text style={styles.originalButtonText}>{contentButtonLabel(content)}</Text>
            </Pressable>

            {content.expanded ? (
              <View style={styles.originalSection}>
                <View style={styles.divider} />
                <Text style={styles.sectionLabel}>
                  {contentSectionTitle(languageLabel(content.language))}
                </Text>

                {content.status === 'error' ? (
                  <View style={styles.errorBox}>
                    <Text style={styles.errorText}>{content.error}</Text>
                    <Pressable
                      onPress={() => dispatch({ type: 'retry' })}
                      style={({ pressed }) => [styles.retry, pressed && styles.pressed]}
                    >
                      <Text style={styles.retryText}>重新加载原文</Text>
                    </Pressable>
                  </View>
                ) : null}

                {content.status === 'empty' && emptyMessage ? (
                  <Text style={styles.notice}>{emptyMessage}</Text>
                ) : null}

                {body.length ? (
                  <>
                    <Text style={styles.originalTitle}>{data.title_original}</Text>
                    {body.map((block, index) => {
                      const key = `${block.kind}-${index}`;
                      if (block.kind === 'heading') {
                        return (
                          <Text
                            key={key}
                            style={[styles.originalHeading, block.level <= 2 && styles.originalHeadingTop]}
                          >
                            {block.text}
                          </Text>
                        );
                      }
                      if (block.kind === 'list') {
                        return (
                          <Text key={key} style={styles.originalListItem}>
                            · {block.text}
                          </Text>
                        );
                      }
                      if (block.kind === 'quote') {
                        return (
                          <Text key={key} style={styles.originalQuote}>
                            {block.text}
                          </Text>
                        );
                      }
                      return (
                        <Text key={key} style={styles.originalParagraph}>
                          {block.text}
                        </Text>
                      );
                    })}
                    {emptyMessage ? <Text style={styles.notice}>{emptyMessage}</Text> : null}
                  </>
                ) : null}
              </View>
            ) : null}

            <View style={styles.actions}>
              <FavoriteButton itemType="news" itemId={data.id} />
            </View>

            <Pressable
              onPress={openOriginal}
              android_ripple={{ color: colors.overlay }}
              style={({ pressed }) => [styles.button, pressed && styles.pressed]}
            >
              <Text style={styles.buttonText}>打开原始网页</Text>
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
    marginBottom: spacing.lg,
  },
  meta: {
    ...typography.meta,
    color: colors.textSecondary,
  },
  sectionLabel: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.textTertiary,
    marginBottom: spacing.sm,
  },
  body: {
    ...typography.body,
    color: colors.text,
  },
  whyBox: {
    marginTop: spacing.lg,
    backgroundColor: colors.overlay,
    borderRadius: radius.md,
    padding: spacing.md,
  },
  originalButton: {
    marginTop: spacing.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    paddingVertical: 14,
  },
  disabled: {
    opacity: 0.7,
  },
  originalButtonText: {
    color: colors.text,
    fontSize: 15,
    fontWeight: '600',
  },
  originalSection: {
    marginTop: spacing.lg,
  },
  divider: {
    height: 1,
    backgroundColor: colors.border,
    marginBottom: spacing.lg,
  },
  originalTitle: {
    ...typography.subtitle,
    color: colors.text,
    marginBottom: spacing.md,
  },
  originalHeading: {
    fontSize: 17,
    lineHeight: 26,
    fontWeight: '600',
    color: colors.text,
    marginTop: spacing.md,
    marginBottom: spacing.xs,
  },
  originalHeadingTop: {
    fontSize: 19,
    lineHeight: 28,
  },
  originalParagraph: {
    ...typography.body,
    color: colors.text,
    marginBottom: spacing.sm,
  },
  originalListItem: {
    ...typography.body,
    color: colors.text,
    marginBottom: spacing.xs,
    paddingLeft: spacing.xs,
  },
  originalQuote: {
    ...typography.body,
    color: colors.textSecondary,
    borderLeftWidth: 3,
    borderLeftColor: colors.border,
    paddingLeft: spacing.sm,
    marginBottom: spacing.sm,
  },
  notice: {
    ...typography.meta,
    color: colors.textTertiary,
    marginTop: spacing.sm,
  },
  errorBox: {
    backgroundColor: colors.overlay,
    borderRadius: radius.md,
    padding: spacing.md,
    alignItems: 'flex-start',
  },
  errorText: {
    ...typography.meta,
    color: colors.textSecondary,
  },
  retry: {
    marginTop: spacing.sm,
  },
  retryText: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.accent,
  },
  tags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: spacing.lg,
  },
  actions: {
    marginTop: spacing.lg,
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
