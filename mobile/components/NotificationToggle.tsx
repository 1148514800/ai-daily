import { useEffect, useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from 'react-native';
import {
  getCurrentPushToken,
  registerForDailyDigest,
  unregisterForDailyDigest,
} from '../services/notifications';
import { colors, radius, spacing, typography } from '../theme';

type Status = 'idle' | 'working';

/**
 * Lightweight daily-notification switch. Denied permission is a normal state,
 * not an error: the digest stays fully readable.
 */
export function NotificationToggle() {
  const [enabled, setEnabled] = useState(false);
  const [status, setStatus] = useState<Status>('idle');
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    setEnabled(Boolean(getCurrentPushToken()));
  }, []);

  async function onToggle() {
    setStatus('working');
    setMessage(null);
    try {
      if (enabled) {
        const token = getCurrentPushToken();
        if (token) {
          await unregisterForDailyDigest(token);
        }
        setEnabled(false);
        setMessage('已关闭每日通知');
        return;
      }

      const result = await registerForDailyDigest();
      if (result.status === 'registered') {
        setEnabled(true);
        setMessage('已开启每日通知');
      } else if (result.status === 'denied') {
        setMessage('系统未授权通知，日报仍可正常阅读');
      } else {
        setMessage('当前环境无法开启通知（需要 Development Build）');
      }
    } catch {
      setMessage('操作失败，请稍后重试');
    } finally {
      setStatus('idle');
    }
  }

  const working = status === 'working';

  return (
    <View style={styles.row}>
      <Text style={styles.label}>每日通知</Text>
      <Pressable
        onPress={onToggle}
        disabled={working}
        accessibilityRole="switch"
        accessibilityState={{ checked: enabled, busy: working }}
        style={({ pressed }) => [
          styles.button,
          enabled && styles.buttonOn,
          pressed && styles.pressed,
        ]}
      >
        {working ? (
          <ActivityIndicator size="small" color={colors.textSecondary} />
        ) : (
          <Text style={[styles.buttonText, enabled && styles.buttonTextOn]}>
            {enabled ? '已开启' : '开启'}
          </Text>
        )}
      </Pressable>
      {message ? <Text style={styles.message}>{message}</Text> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  label: {
    ...typography.meta,
    color: colors.textSecondary,
    flex: 1,
  },
  button: {
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingHorizontal: spacing.md,
    paddingVertical: 8,
    minWidth: 84,
    alignItems: 'center',
  },
  buttonOn: {
    borderColor: colors.accent,
    backgroundColor: colors.accentSoft,
  },
  pressed: {
    opacity: 0.9,
  },
  buttonText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text,
  },
  buttonTextOn: {
    color: colors.accent,
  },
  message: {
    ...typography.meta,
    color: colors.textTertiary,
    width: '100%',
  },
});
