import { BackHeader } from '../components/BackHeader';
import { DigestNav } from '../components/DigestNav';
import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useDigest } from '../hooks/useDigest';
import { useDigestHistory } from '../hooks/useDigestHistory';
import { digestHeading } from '../lib/digestHistory';
import { formatShortDate } from '../lib/format';
import { isTodayInAppTimezone } from '../lib/relativeTime';

type DigestScreenProps = {
  date: string;
  onBack: () => void;
  onOpenNews: (id: string) => void;
  /** Open another stored digest in place, re-using this screen. */
  onOpenDigest: (date: string) => void;
};

export function DigestScreen({ date, onBack, onOpenNews, onOpenDigest }: DigestScreenProps) {
  const { status, data, error, reload } = useDigest(date);
  // The list only supplies the neighbouring dates; a failed list load leaves the
  // digest readable, it just disables the step controls.
  const { neighbours } = useDigestHistory(date);
  const notFound = status === 'error' && error?.status === 404;
  const today = isTodayInAppTimezone(date);
  // A digest can legitimately be stored with nothing in it (a refresh that found
  // no news). That is a normal state, not an error, but a completely blank page
  // would look broken, so the message only replaces a digest that is empty in
  // both of its sections.
  const trulyEmpty =
    status === 'success' && !!data && data.news.length === 0 && data.github_projects.length === 0;

  return (
    <Screen>
      <BackHeader title={formatShortDate(date)} onBack={onBack} />
      <StatusState
        loading={status === 'loading'}
        error={status === 'error' && !notFound}
        empty={notFound || trulyEmpty}
        loadingText="正在加载日报..."
        errorText={error?.message}
        emptyText={notFound ? '该日期没有日报。' : '这一天的日报还没有内容。'}
        onRetry={notFound ? undefined : reload}
      >
        {data ? (
          <DigestView
            digest={data}
            onOpenNews={onOpenNews}
            showFinishedHint={false}
            heading={digestHeading(date, today)}
            // Each day is its own list, so a position saved on 09-12 cannot be
            // restored onto 09-13.
            scrollKey={`digest:${date}`}
            footerNav={
              <DigestNav
                previous={neighbours?.previous ?? null}
                next={neighbours?.next ?? null}
                onNavigate={onOpenDigest}
              />
            }
          />
        ) : null}
      </StatusState>
    </Screen>
  );
}
