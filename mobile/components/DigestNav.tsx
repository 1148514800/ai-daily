import { Pressable, StyleSheet, Text, View } from 'react-native';
import { formatShortDate } from '../lib/format';
import { colors, radius, spacing } from '../theme';

type DigestNavProps = {
  /** The digest one step older, or null at the oldest stored digest. */
  previous: string | null;
  /** The digest one step newer, or null at the newest stored digest. */
  next: string | null;
  onNavigate: (date: string) => void;
};

/**
 * Step to the adjacent stored digest.
 *
 * The dates come from the backend's list, so "previous" means the day before in
 * the database, not the calendar: when a day is missing the control skips it
 * instead of opening a digest that was never generated. An edge shows its date
 * greyed out and does nothing, so the boundaries are visible rather than
 * silently dead.
 */
export function DigestNav({ previous, next, onNavigate }: DigestNavProps) {
  return (
    <View style={styles.row}>
      <NavButton
        label="← 前一天"
        caption={previous ? formatShortDate(previous) : '已是最早'}
        date={previous}
        onNavigate={onNavigate}
        align="flex-start"
      />
      <NavButton
        label="后一天 →"
        caption={next ? formatShortDate(next) : '已是最新'}
        date={next}
        onNavigate={onNavigate}
        align="flex-end"
      />
    </View>
  );
}

type NavButtonProps = {
  label: string;
  caption: string;
  date: string | null;
  onNavigate: (date: string) => void;
  align: 'flex-start' | 'flex-end';
};

function NavButton({ label, caption, date, onNavigate, align }: NavButtonProps) {
  const disabled = date === null;
  return (
    <Pressable
      onPress={() => {
        if (date) {
          onNavigate(date);
        }
      }}
      disabled={disabled}
      accessibilityRole="button"
      accessibilityLabel={`${label} ${caption}`}
      accessibilityState={{ disabled }}
      android_ripple={disabled ? undefined : { color: colors.overlay }}
      style={({ pressed }) => [
        styles.button,
        { alignItems: align },
        disabled && styles.disabled,
        pressed && !disabled && styles.pressed,
      ]}
    >
      <Text style={[styles.label, disabled && styles.disabledLabel]}>{label}</Text>
      <Text style={styles.caption}>{caption}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  button: {
    flex: 1,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  disabled: {
    opacity: 0.5,
  },
  pressed: {
    opacity: 0.9,
  },
  label: {
    fontSize: 14,
    lineHeight: 20,
    fontWeight: '500',
    color: colors.accent,
  },
  disabledLabel: {
    color: colors.textTertiary,
  },
  caption: {
    marginTop: 2,
    fontSize: 12,
    lineHeight: 16,
    color: colors.textTertiary,
  },
});
