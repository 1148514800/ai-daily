import type { ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { colors, radius, spacing, typography } from '../theme';

type StatusStateProps = {
  loading: boolean;
  error: boolean;
  empty: boolean;
  loadingText: string;
  errorText?: string;
  emptyText: string;
  onRetry?: () => void;
  children: ReactNode;
};

export function StatusState({
  loading,
  error,
  empty,
  loadingText,
  errorText = '内容加载失败',
  emptyText,
  onRetry,
  children,
}: StatusStateProps) {
  if (loading) {
    return (
      <View style={styles.center}>
        <Text style={styles.message}>{loadingText}</Text>
      </View>
    );
  }

  if (error) {
    return (
      <View style={styles.center}>
        <Text style={styles.message}>{errorText}</Text>
        {onRetry ? (
          <Pressable onPress={onRetry} style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
            <Text style={styles.buttonText}>重新加载</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  if (empty) {
    return (
      <View style={styles.center}>
        <Text style={styles.message}>{emptyText}</Text>
        {onRetry ? (
          <Pressable onPress={onRetry} style={({ pressed }) => [styles.button, pressed && styles.pressed]}>
            <Text style={styles.buttonText}>重新加载</Text>
          </Pressable>
        ) : null}
      </View>
    );
  }

  return <>{children}</>;
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: spacing.xl,
  },
  message: {
    ...typography.body,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  button: {
    marginTop: spacing.md,
    backgroundColor: colors.text,
    borderRadius: radius.md,
    paddingHorizontal: spacing.lg,
    paddingVertical: 12,
  },
  pressed: {
    opacity: 0.9,
  },
  buttonText: {
    color: colors.surface,
    fontSize: 15,
    fontWeight: '600',
  },
});
