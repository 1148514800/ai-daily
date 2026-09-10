import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, spacing } from '../theme';

type BackHeaderProps = {
  title: string;
  onBack: () => void;
};

export function BackHeader({ title, onBack }: BackHeaderProps) {
  return (
    <View style={styles.header}>
      <Pressable onPress={onBack} hitSlop={12} style={styles.backButton}>
        <Text style={styles.back}>返回</Text>
      </Pressable>
      <Text style={styles.title} numberOfLines={1}>
        {title}
      </Text>
      <View style={styles.side} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.sm,
    minHeight: 48,
  },
  backButton: {
    width: 56,
  },
  back: {
    fontSize: 16,
    color: colors.accent,
  },
  title: {
    flex: 1,
    textAlign: 'center',
    fontSize: 16,
    fontWeight: '600',
    color: colors.text,
  },
  side: {
    width: 56,
  },
});
