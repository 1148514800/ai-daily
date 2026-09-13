import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Chip } from '../components/Chip';
import { BackHeader } from '../components/BackHeader';
import { Screen } from '../components/Screen';
import { useDebouncedValue } from '../hooks/useDebouncedValue';
import { formatShortDate } from '../lib/format';
import {
  resultDate,
  resultExcerpt,
  searchPhase,
  SEARCH_DEBOUNCE_MS,
  SEARCH_PAGE_SIZE,
} from '../lib/search';
import { topicLabel } from '../lib/topics';
import { ApiError, searchNews } from '../services/api';
import type { SearchResultItem } from '../types';
import { colors, radius, spacing, typography } from '../theme';

type SearchScreenProps = {
  onBack: () => void;
  onOpenNews: (id: string) => void;
};

type Results = {
  query: string;
  total: number;
  items: SearchResultItem[];
};

export function SearchScreen({ onBack, onOpenNews }: SearchScreenProps) {
  const [query, setQuery] = useState('');
  const debounced = useDebouncedValue(query, SEARCH_DEBOUNCE_MS);
  const [results, setResults] = useState<Results | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Every request carries the query it belongs to. When a response arrives it is
  // only applied if it is still the query on screen, so a slow response for an
  // older query can never replace the results of a newer one.
  const latest = useRef('');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const trimmed = debounced.trim();
    latest.current = trimmed;

    if (!trimmed) {
      setResults(null);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    setLoading(true);
    searchNews(trimmed, { limit: SEARCH_PAGE_SIZE })
      .then((response) => {
        if (cancelled || latest.current !== trimmed) {
          return;
        }
        setResults({ query: response.query, total: response.total, items: response.items });
        setError(null);
      })
      .catch((caught: unknown) => {
        if (cancelled || latest.current !== trimmed) {
          return;
        }
        setResults(null);
        setError(
          caught instanceof ApiError
            ? caught.message
            : '无法连接 AI Daily 服务，请检查后端地址与网络',
        );
      })
      .finally(() => {
        if (!cancelled && latest.current === trimmed) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [debounced, attempt]);

  const phase = searchPhase(debounced, {
    loading,
    hasResults: !!results && results.items.length > 0,
  });

  return (
    <Screen>
      <BackHeader title="搜索" onBack={onBack} />
      <View style={styles.header}>
        <Text style={styles.title}>搜索 AI 新闻</Text>
        <TextInput
          value={query}
          onChangeText={setQuery}
          placeholder="搜索 DeepSeek / Agent / GPT-6…"
          placeholderTextColor={colors.textTertiary}
          style={styles.input}
          autoCorrect={false}
          autoCapitalize="none"
          returnKeyType="search"
          accessibilityLabel="搜索 AI 新闻"
        />
      </View>

      {phase === 'idle' ? (
        <View style={styles.center}>
          <Text style={styles.message}>搜索历史 AI 新闻</Text>
          <Text style={styles.hint}>输入关键词，在全部已收录新闻中查找。</Text>
        </View>
      ) : null}

      {error ? (
        <View style={styles.center}>
          <Text style={styles.message}>{error}</Text>
          <Pressable
            onPress={() => setAttempt((value) => value + 1)}
            style={({ pressed }) => [styles.button, pressed && styles.pressed]}
          >
            <Text style={styles.buttonText}>重新尝试</Text>
          </Pressable>
        </View>
      ) : null}

      {!error && phase === 'searching' ? (
        <View style={styles.center}>
          <ActivityIndicator color={colors.accent} />
        </View>
      ) : null}

      {!error && phase === 'empty' ? (
        <View style={styles.center}>
          <Text style={styles.message}>没有找到相关内容</Text>
          <Text style={styles.hint}>换个关键词，或试试来源名与公司名。</Text>
        </View>
      ) : null}

      {!error && phase === 'results' && results ? (
        <ScrollView
          contentContainerStyle={styles.list}
          keyboardShouldPersistTaps="handled"
          showsVerticalScrollIndicator={false}
        >
          <Text style={styles.count}>搜索结果 {results.total} 条</Text>
          {results.items.map((item) => (
            <ResultRow key={item.news_id} item={item} onPress={onOpenNews} />
          ))}
        </ScrollView>
      ) : null}
    </Screen>
  );
}

type ResultRowProps = {
  item: SearchResultItem;
  onPress: (id: string) => void;
};

function ResultRow({ item, onPress }: ResultRowProps) {
  const date = resultDate(item);
  const topic = topicLabel(item.topic);
  const excerpt = resultExcerpt(item);

  return (
    <Pressable
      onPress={() => onPress(item.news_id)}
      android_ripple={{ color: colors.overlay }}
      style={({ pressed }) => [styles.card, pressed && styles.pressed]}
    >
      <View style={styles.metaRow}>
        {topic ? <Chip label={topic} tone="accent" /> : null}
        <Text style={styles.meta}>{item.source}</Text>
        {date ? (
          <>
            <Text style={styles.dot}>·</Text>
            <Text style={styles.meta}>{formatShortDate(date)}</Text>
          </>
        ) : null}
      </View>
      <Text style={styles.cardTitle} numberOfLines={2}>
        {item.title_cn || item.original_title}
      </Text>
      {excerpt ? (
        <Text style={styles.excerpt} numberOfLines={3}>
          {excerpt}
        </Text>
      ) : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  header: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
  },
  title: {
    ...typography.display,
    color: colors.text,
  },
  input: {
    marginTop: spacing.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.text,
  },
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
  },
  message: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  hint: {
    ...typography.meta,
    color: colors.textTertiary,
    textAlign: 'center',
    marginTop: spacing.sm,
  },
  button: {
    marginTop: spacing.md,
    backgroundColor: colors.text,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: 12,
  },
  pressed: {
    opacity: 0.92,
  },
  buttonText: {
    color: colors.surface,
    fontSize: 15,
    fontWeight: '600',
  },
  list: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  count: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    marginBottom: spacing.sm,
  },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    padding: spacing.md,
    marginBottom: spacing.sm,
  },
  metaRow: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: spacing.sm,
  },
  meta: {
    ...typography.meta,
    color: colors.textTertiary,
  },
  dot: {
    color: colors.textTertiary,
  },
  cardTitle: {
    ...typography.subtitle,
    color: colors.text,
    marginBottom: 6,
  },
  excerpt: {
    ...typography.body,
    fontSize: 15,
    lineHeight: 23,
    color: colors.textSecondary,
  },
});
