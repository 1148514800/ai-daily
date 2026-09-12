import { BackHeader } from '../components/BackHeader';
import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { formatShortDate } from '../lib/format';
import { fetchDailyByDate } from '../services/api';

type DigestScreenProps = {
  date: string;
  onBack: () => void;
  onOpenNews: (id: string) => void;
};

export function DigestScreen({ date, onBack, onOpenNews }: DigestScreenProps) {
  const { status, data, error, reload } = useAsyncResource(
    () => fetchDailyByDate(date),
    [date],
  );
  const notFound = status === 'error' && error?.status === 404;

  return (
    <Screen>
      <BackHeader title={formatShortDate(date)} onBack={onBack} />
      <StatusState
        loading={status === 'loading'}
        error={status === 'error' && !notFound}
        empty={notFound || (status === 'success' && !!data && data.news.length === 0)}
        loadingText="正在加载日报..."
        errorText={error?.message}
        emptyText="没有找到这一天的日报。"
        onRetry={notFound ? undefined : reload}
      >
        {data ? <DigestView digest={data} onOpenNews={onOpenNews} showFinishedHint={false} /> : null}
      </StatusState>
    </Screen>
  );
}
