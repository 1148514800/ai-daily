import { StyleSheet, Text } from 'react-native';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { fetchRefreshStatus } from '../services/api';
import { colors, spacing, typography } from '../theme';

/**
 * Lightweight "last updated" line. It fails silently on purpose: a missing
 * scheduler should never break reading the digest.
 */
export function UpdateHint() {
  const { status, data } = useAsyncResource(fetchRefreshStatus);

  if (status !== 'success' || !data) {
    return null;
  }

  const lastRun = data.last_run;
  const label = lastRun?.local_time
    ? `最后更新：${lastRun.local_time}`
    : lastRun
      ? '最近一次刷新未成功'
      : '尚未自动刷新';
  const schedule = data.scheduler_enabled ? `每天 ${data.scheduled_time} 自动刷新` : '自动刷新已关闭';

  return (
    <Text style={styles.hint}>
      {label} · {schedule}
    </Text>
  );
}

const styles = StyleSheet.create({
  hint: {
    ...typography.meta,
    color: colors.textTertiary,
    marginTop: spacing.sm,
  },
});
