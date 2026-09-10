import { Alert, Linking, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { BackHeader } from '../components/BackHeader';
import { Chip } from '../components/Chip';
import { Screen } from '../components/Screen';
import { getNewsById } from '../data/news';
import { colors, radius, spacing, typography } from '../theme';

type NewsDetailScreenProps = {
  newsId: string;
  onBack: () => void;
};

export function NewsDetailScreen({ newsId, onBack }: NewsDetailScreenProps) {
  const item = getNewsById(newsId);

  if (!item) {
    return (
      <Screen>
        <BackHeader title="详情" onBack={onBack} />
        <View style={styles.missing}>
          <Text style={styles.missingText}>没有找到这条内容。</Text>
        </View>
      </Screen>
    );
  }

  async function openOriginal() {
    if (!item) {
      return;
    }
    try {
      await Linking.openURL(item.url);
    } catch {
      Alert.alert('查看原文', '这是占位链接，本阶段不访问真实页面。');
    }
  }

  return (
    <Screen>
      <BackHeader title="新闻详情" onBack={onBack} />
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.title}>{item.title}</Text>
        <Text style={styles.original}>{item.originalTitle}</Text>
        <Text style={styles.meta}>
          {item.source}  ·  {item.publishedAt}
        </Text>

        <Text style={styles.sectionLabel}>中文摘要</Text>
        <Text style={styles.body}>{item.summary}</Text>

        <View style={styles.whyBox}>
          <Text style={styles.sectionLabel}>Why it matters</Text>
          <Text style={styles.body}>{item.whyItMatters}</Text>
        </View>

        <View style={styles.tags}>
          {item.tags.map((tag) => (
            <Chip key={tag} label={tag} />
          ))}
        </View>

        <Pressable
          onPress={openOriginal}
          android_ripple={{ color: colors.overlay }}
          style={({ pressed }) => [styles.button, pressed && styles.pressed]}
        >
          <Text style={styles.buttonText}>查看原文</Text>
        </Pressable>
      </ScrollView>
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
  tags: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: spacing.lg,
  },
  button: {
    marginTop: spacing.xl,
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
  missing: {
    padding: spacing.lg,
  },
  missingText: {
    ...typography.body,
    color: colors.textSecondary,
  },
});
