import { StyleSheet, Text, View } from 'react-native';
import { colors, spacing, typography } from '../theme';

type SectionHeaderProps = {
  title: string;
  caption?: string;
};

export function SectionHeader({ title, caption }: SectionHeaderProps) {
  return (
    <View style={styles.wrap}>
      <Text style={styles.title}>{title}</Text>
      {caption ? <Text style={styles.caption}>{caption}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: {
    marginBottom: spacing.sm,
    marginTop: spacing.lg,
  },
  title: {
    ...typography.subtitle,
    color: colors.text,
  },
  caption: {
    marginTop: 4,
    fontSize: 13,
    lineHeight: 18,
    color: colors.textSecondary,
  },
});
