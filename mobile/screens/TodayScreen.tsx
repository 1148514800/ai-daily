import { Pressable, StyleSheet, Text } from 'react-native';
import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { digestHeading, resolveTodayView } from '../lib/digestHistory';
import { formatShortDate } from '../lib/format';
import { appLocalDate } from '../lib/relativeTime';
import { fetchTodayDaily } from '../services/api';
import { colors, spacing } from '../theme';

type TodayScreenProps = {
  onOpenNews: (id: string) => void;
  /** Switch to the history tab, the entry point for reading past digests. */
  onOpenHistory: () => void;
  /** Open the search screen for the whole archive. */
  onOpenSearch: () => void;
};

export function TodayScreen({ onOpenNews, onOpenHistory, onOpenSearch }: TodayScreenProps) {
  const { status, data, error, reload } = useAsyncResource(fetchTodayDaily);
  // /daily already resolves "today's digest, or the latest one when today has
  // not been generated yet". The view only decides how to label the result, so
  // the app never has to invent a digest for a day that was not generated.
  const view = data ? resolveTodayView(data.date, appLocalDate(new Date())) : null;

  return (
    <Screen>
      <StatusState
        loading={status === 'loading'}
        error={status === 'error'}
        empty={
          status === 'success' &&
          !!data &&
          data.news.length === 0 &&
          data.github_projects.length === 0
        }
        loadingText="正在加载今日资讯..."
        errorText={error?.message}
        emptyText="今天还没有生成日报。日报每天 08:00 自动更新，稍后再来看看。"
        onRetry={reload}
      >
        {data && view ? (
          <DigestView
            digest={data}
            onOpenNews={onOpenNews}
            heading={digestHeading(data.date, view.isToday)}
            /* "今日已读完" only makes sense for today's own digest; on a
               fallback day it would claim a reading session that did not
               happen. */
            showFinishedHint={view.isToday}
            headerNote={
              <>
                {view.fellBack ? (
                  <Text style={styles.fallback}>
                    今天还没有生成日报，以下是 {formatShortDate(data.date)} 的日报。
                  </Text>
                ) : null}
                <Pressable onPress={onOpenHistory} hitSlop={8} style={styles.historyLink}>
                  <Text style={styles.historyLinkText}>历史日报 →</Text>
                </Pressable>
                <Pressable onPress={onOpenSearch} hitSlop={8} style={styles.historyLink}>
                  <Text style={styles.historyLinkText}>搜索历史新闻 →</Text>
                </Pressable>
              </>
            }
          />
        ) : null}
      </StatusState>
    </Screen>
  );
}

const styles = StyleSheet.create({
  fallback: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
  historyLink: {
    marginTop: spacing.sm,
    alignSelf: 'flex-start',
  },
  historyLinkText: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '500',
    color: colors.accent,
  },
});
