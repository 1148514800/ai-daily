import { StyleSheet, Text } from 'react-native';
import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useTodayDigest } from '../hooks/useTodayDigest';
import { digestHeading, resolveTodayView } from '../lib/digestHistory';
import { formatShortDate } from '../lib/format';
import { appLocalDate } from '../lib/relativeTime';
import { colors, spacing } from '../theme';

type TodayScreenProps = {
  onOpenNews: (id: string) => void;
};

/**
 * Today's digest: one ranked list, then GitHub Trending.
 *
 * Phase 10.11 removed the 历史日报 / 搜索历史新闻 shortcuts from this screen. Both
 * capabilities still exist on the backend and still have their own places in the
 * app (the 历史 tab and its search entry), but the daily read is no longer
 * interrupted by two links out.
 *
 * The digest is read through the in-memory cache rather than fetched flat, so
 * coming back from a story re-renders the list the reader left instead of
 * waiting for it again.
 */
export function TodayScreen({ onOpenNews }: TodayScreenProps) {
  const { status, data, error, reload } = useTodayDigest();
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
        /* The home screen stays about reading: the refresh schedule now lives in
           设置, so an empty day does not explain the scheduler here. */
        emptyText="今天还没有生成日报，稍后再来看看。"
        onRetry={reload}
      >
        {data && view ? (
          <DigestView
            digest={data}
            onOpenNews={onOpenNews}
            heading={digestHeading(data.date, view.isToday)}
            // Coming back from a story restores the position in this list.
            scrollKey="today"
            /* "今日已读完" only makes sense for today's own digest; on a
               fallback day it would claim a reading session that did not
               happen. */
            showFinishedHint={view.isToday}
            headerNote={
              view.fellBack ? (
                <Text style={styles.fallback}>
                  今天还没有生成日报，以下是 {formatShortDate(data.date)} 的日报。
                </Text>
              ) : null
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
});
