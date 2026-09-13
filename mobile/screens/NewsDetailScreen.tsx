import { Alert, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { BackHeader } from '../components/BackHeader';
import { Chip } from '../components/Chip';
import { FavoriteButton } from '../components/FavoriteButton';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { isSummaryOnly, languageLabel, parseArticleBody } from '../lib/articleBody';
import { formatTime } from '../lib/format';
import { fetchNews } from '../services/api';
import { colors, radius, spacing, typography } from '../theme';

type NewsDetailScreenProps = {
  newsId: string;
  onBack: () => void;
};

export function NewsDetailScreen({ newsId, onBack }: NewsDetailScreenProps) {
  const { status, data, error, reload } = useAsyncResource(() => fetchNews(newsId), [newsId]);
  const notFound = status === 'error' && error?.status === 404;
  // The body is shown in the language it was published in. Nothing here
  // translates it; the Chinese summary above is a separate field.
  const body = parseArticleBody(data?.content_original);

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
            <Text style={styles.meta}>
              {data.source}  ·  {data.published_at.slice(0, 10)} {formatTime(data.published_at)}
            </Text>

            <Text style={styles.sectionLabel}>中文摘要</Text>
            <Text style={styles.body}>{data.summary || "原文暂无摘要。"}</Text>

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

            {body.length ? (
              <View style={styles.originalSection}>
                <View style={styles.divider} />
                <Text style={styles.sectionLabel}>
                  原文内容 · {languageLabel(data.content_language)}
                </Text>
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
                {isSummaryOnly(data.content_extraction_method) ? (
                  <Text style={styles.notice}>
                    未能抓取正文，这里显示的是该来源提供的摘要，可点击下方按钮查看原文。
                  </Text>
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
              <Text style={styles.buttonText}>查看原文</Text>
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
  meta: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
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
