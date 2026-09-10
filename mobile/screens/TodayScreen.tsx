import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { getTodayDigest } from '../data/digests';

type TodayScreenProps = {
  onOpenNews: (id: string) => void;
};

export function TodayScreen({ onOpenNews }: TodayScreenProps) {
  const digest = getTodayDigest();

  return (
    <Screen>
      <DigestView digest={digest} onOpenNews={onOpenNews} />
    </Screen>
  );
}
