import { useEffect, useState } from 'react';
import {
  ActivityIndicator,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Screen } from '../components/Screen';
import { useAsyncResource } from '../hooks/useAsyncResource';
import { checkBackendHealth, validateBackendUrl } from '../lib/backendUrl';
import { systemStatusRows } from '../lib/systemStatus';
import {
  getApiBaseUrl,
  resetBackendUrl,
  saveBackendUrl,
} from '../services/backendSettings';
import { fetchRefreshStatus } from '../services/api';
import { colors, radius, spacing, typography } from '../theme';

type Feedback = { kind: 'ok' | 'error' | 'info'; text: string } | null;

export function SettingsScreen() {
  const [url, setUrl] = useState(getApiBaseUrl());
  const [feedback, setFeedback] = useState<Feedback>(null);
  const [busy, setBusy] = useState<'idle' | 'testing' | 'saving'>('idle');
  // The refresh status used to sit under the digest headline, where it competed
  // with the news for attention. It moved here in Phase 10.12: the reading page
  // shows the digest, and "is the background job healthy" is a settings question.
  // A failed load is not an error state: the rows simply say 暂无状态信息.
  const { data: refreshStatus } = useAsyncResource(fetchRefreshStatus);
  const statusRows = systemStatusRows(refreshStatus);

  useEffect(() => {
    setUrl(getApiBaseUrl());
  }, []);

  async function onTest() {
    const validation = validateBackendUrl(url);
    if (!validation.ok) {
      setFeedback({ kind: 'error', text: validation.reason });
      return;
    }
    setBusy('testing');
    setFeedback(null);
    const result = await checkBackendHealth(validation.url);
    setBusy('idle');
    setFeedback(
      result.ok
        ? { kind: 'ok', text: `连接成功：${validation.url}` }
        : { kind: 'error', text: result.message },
    );
  }

  async function onSave() {
    setBusy('saving');
    setFeedback(null);
    try {
      const saved = await saveBackendUrl(url);
      setUrl(saved);
      setFeedback({ kind: 'ok', text: `已保存：${saved}` });
    } catch (error) {
      setFeedback({
        kind: 'error',
        text: error instanceof Error ? error.message : '保存失败',
      });
    } finally {
      setBusy('idle');
    }
  }

  async function onReset() {
    setBusy('saving');
    setFeedback(null);
    try {
      const restored = await resetBackendUrl();
      setUrl(restored);
      setFeedback({ kind: 'info', text: `已恢复默认：${restored}` });
    } finally {
      setBusy('idle');
    }
  }

  const working = busy !== 'idle';

  return (
    <Screen>
      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        <Text style={styles.kicker}>本地部署</Text>
        <Text style={styles.title}>设置</Text>
        <Text style={styles.description}>
          填写电脑上运行的后端地址。同一 Wi-Fi 下请使用电脑的局域网 IP，例如
          http://192.168.1.100:8000
        </Text>

        <Text style={styles.label}>Backend 地址</Text>
        <TextInput
          value={url}
          onChangeText={setUrl}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://192.168.1.100:8000"
          placeholderTextColor={colors.textTertiary}
          style={styles.input}
        />

        <View style={styles.actions}>
          <Pressable
            onPress={onTest}
            disabled={working}
            style={({ pressed }) => [styles.button, styles.secondary, pressed && styles.pressed]}
          >
            {busy === 'testing' ? (
              <ActivityIndicator size="small" color={colors.text} />
            ) : (
              <Text style={styles.secondaryText}>测试连接</Text>
            )}
          </Pressable>
          <Pressable
            onPress={onSave}
            disabled={working}
            style={({ pressed }) => [styles.button, styles.primary, pressed && styles.pressed]}
          >
            {busy === 'saving' ? (
              <ActivityIndicator size="small" color={colors.surface} />
            ) : (
              <Text style={styles.primaryText}>保存</Text>
            )}
          </Pressable>
        </View>

        {feedback ? (
          <Text
            style={[
              styles.feedback,
              feedback.kind === 'ok' && styles.feedbackOk,
              feedback.kind === 'error' && styles.feedbackError,
            ]}
          >
            {feedback.text}
          </Text>
        ) : null}

        <Pressable onPress={onReset} disabled={working} style={styles.resetButton}>
          <Text style={styles.resetText}>恢复默认地址</Text>
        </Pressable>

        <View style={styles.note}>
          <Text style={styles.noteTitle}>当前生效地址</Text>
          <Text style={styles.noteBody}>{getApiBaseUrl()}</Text>
          <Text style={styles.noteBody}>
            本地部署阶段使用 HTTP；未来迁移到云服务器时改为 HTTPS。
          </Text>
        </View>

        <Text style={styles.sectionTitle}>系统状态</Text>
        <View style={styles.note}>
          {statusRows.map((row) => (
            <View key={row.key} style={styles.statusRow}>
              <Text style={styles.statusLabel}>{row.label}</Text>
              <Text style={styles.statusValue}>{row.value}</Text>
            </View>
          ))}
        </View>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: {
    paddingHorizontal: spacing.lg,
    paddingBottom: spacing.xxl,
  },
  kicker: {
    ...typography.meta,
    color: colors.textSecondary,
    marginTop: spacing.sm,
  },
  title: {
    ...typography.display,
    color: colors.text,
    marginTop: 8,
  },
  description: {
    ...typography.body,
    color: colors.textSecondary,
    marginTop: spacing.sm,
    marginBottom: spacing.lg,
  },
  label: {
    ...typography.meta,
    color: colors.textTertiary,
    marginBottom: spacing.xs,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 12,
    fontSize: 16,
    color: colors.text,
  },
  actions: {
    flexDirection: 'row',
    gap: spacing.sm,
    marginTop: spacing.md,
  },
  button: {
    flex: 1,
    borderRadius: radius.md,
    paddingVertical: 14,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 50,
  },
  primary: {
    backgroundColor: colors.text,
  },
  secondary: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  pressed: {
    opacity: 0.9,
  },
  primaryText: {
    color: colors.surface,
    fontSize: 16,
    fontWeight: '600',
  },
  secondaryText: {
    color: colors.text,
    fontSize: 16,
    fontWeight: '600',
  },
  feedback: {
    ...typography.meta,
    marginTop: spacing.md,
    color: colors.textSecondary,
  },
  feedbackOk: {
    color: colors.accent,
  },
  feedbackError: {
    color: '#B3261E',
  },
  resetButton: {
    marginTop: spacing.lg,
    alignSelf: 'flex-start',
  },
  resetText: {
    fontSize: 14,
    color: colors.accent,
  },
  note: {
    marginTop: spacing.xl,
    backgroundColor: colors.overlay,
    borderRadius: radius.md,
    padding: spacing.md,
    gap: 6,
  },
  noteTitle: {
    ...typography.meta,
    color: colors.textTertiary,
  },
  noteBody: {
    ...typography.meta,
    color: colors.textSecondary,
  },
  sectionTitle: {
    ...typography.subtitle,
    color: colors.text,
    marginTop: spacing.xl,
    marginBottom: spacing.sm,
  },
  statusRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    gap: spacing.md,
  },
  statusLabel: {
    ...typography.meta,
    color: colors.textTertiary,
  },
  statusValue: {
    ...typography.meta,
    color: colors.textSecondary,
    flexShrink: 1,
    textAlign: 'right',
  },
});
