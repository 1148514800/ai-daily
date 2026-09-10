import { Text, View } from 'react-native';
import { BackHeader } from '../components/BackHeader';
import { DigestView } from '../components/DigestView';
import { Screen } from '../components/Screen';
import { getDigestByDate } from '../data/digests';
import { formatShortDate } from '../lib/format';
import { colors, spacing, typography } from '../theme';

type DigestScreenProps = {
  date: string;
  onBack: () => void;
  onOpenNews: (id: string) => void;
};

export function DigestScreen({ date, onBack, onOpenNews }: DigestScreenProps) {
  const digest = getDigestByDate(date);

  if (!digest) {
    return (
      <Screen>
        <BackHeader title="日报" onBack={onBack} />
        <View style={{ paddingHorizontal: spacing.lg }}>
          <Text style={{ ...typography.body, color: colors.textSecondary }}>没有找到这一天的日报。</Text>
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <BackHeader title={formatShortDate(digest.date)} onBack={onBack} />
      <DigestView digest={digest} onOpenNews={onOpenNews} showFinishedHint={false} />
    </Screen>
  );
}
