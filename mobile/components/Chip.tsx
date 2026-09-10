import { StyleSheet, Text, View } from 'react-native';
import { colors, radius, spacing } from '../theme';

type ChipProps = {
  label: string;
  tone?: 'accent' | 'neutral';
};

export function Chip({ label, tone = 'neutral' }: ChipProps) {
  return (
    <View style={[styles.chip, tone === 'accent' ? styles.accent : styles.neutral]}>
      <Text style={[styles.label, tone === 'accent' ? styles.accentLabel : styles.neutralLabel]}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  chip: {
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 4,
    alignSelf: 'flex-start',
  },
  accent: {
    backgroundColor: colors.accentSoft,
  },
  neutral: {
    backgroundColor: colors.chip,
  },
  label: {
    fontSize: 12,
    lineHeight: 16,
    fontWeight: '500',
  },
  accentLabel: {
    color: colors.accent,
  },
  neutralLabel: {
    color: colors.textSecondary,
  },
});
