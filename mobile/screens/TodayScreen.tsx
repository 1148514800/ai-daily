import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { StatusState } from '../components/StatusState';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { fetchTodayDaily } from '../services/api';

type TodayScreenProps = {
  onOpenNews: (id: string) => void;
};

export function TodayScreen({ onOpenNews }: TodayScreenProps) {
  const { status, data, error, reload } = useAsyncResource(fetchTodayDaily);

  return (
    <Screen>
      <StatusState
        loading={status === 'loading'}
        error={status === 'error'}
        empty={status === 'success' && !!data && data.news.length === 0}
        loadingText="正在加载今日资讯..."
        errorText={error?.message}
        emptyText="今天还没有生成日报。日报每天 08:00 自动更新，稍后再来看看。"
        onRetry={reload}
      >
        {data ? <DigestView digest={data} onOpenNews={onOpenNews} /> : null}
      </StatusState>
    </Screen>
  );
}
