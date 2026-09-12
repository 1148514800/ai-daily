import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';
import { registerPushDevice, unregisterPushDevice } from './api';

export const DAILY_DIGEST_CHANNEL_ID = 'daily-digest';
export const DAILY_DIGEST_TYPE = 'daily_digest';

export type NotificationSetupResult =
  | { status: 'registered'; token: string }
  | { status: 'denied' }
  | { status: 'unsupported'; reason: string }
  | { status: 'failed'; reason: string };

// In-memory only: the token is re-confirmed on every launch and the backend is
// the source of truth, so no local persistence layer is needed.
let currentPushToken: string | null = null;

export function getCurrentPushToken(): string | null {
  return currentPushToken;
}

/**
 * Foreground presentation. Kept minimal so a push arriving while the app is open
 * shows one banner instead of duplicating system behaviour.
 */
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
  }),
});

async function ensureAndroidChannel(): Promise<void> {
  if (Platform.OS !== 'android') {
    return;
  }
  await Notifications.setNotificationChannelAsync(DAILY_DIGEST_CHANNEL_ID, {
    name: 'AI Daily',
    importance: Notifications.AndroidImportance.DEFAULT,
  });
}

export async function ensurePermission(): Promise<boolean> {
  const current = await Notifications.getPermissionsAsync();
  if (current.granted) {
    return true;
  }
  if (!current.canAskAgain) {
    return false;
  }
  const requested = await Notifications.requestPermissionsAsync();
  return requested.granted;
}

export async function getExpoPushToken(): Promise<string | null> {
  // eas init writes extra.eas.projectId; the env var keeps CI and local
  // development working before EAS is configured.
  const projectId =
    Constants?.expoConfig?.extra?.eas?.projectId ??
    Constants?.easConfig?.projectId ??
    process.env.EXPO_PUBLIC_EAS_PROJECT_ID;
  if (!projectId) {
    return null;
  }
  const result = await Notifications.getExpoPushTokenAsync({ projectId });
  return result.data ?? null;
}

/**
 * Full registration flow. Never throws and never blocks reading the digest:
 * a denied permission or a missing build simply returns a status.
 */
export async function registerForDailyDigest(): Promise<NotificationSetupResult> {
  if (Platform.OS === 'web') {
    return { status: 'unsupported', reason: 'web' };
  }
  if (!Device.isDevice) {
    return { status: 'unsupported', reason: 'emulator' };
  }

  try {
    await ensureAndroidChannel();
    if (!(await ensurePermission())) {
      return { status: 'denied' };
    }
    const token = await getExpoPushToken();
    if (!token) {
      return { status: 'failed', reason: 'missing projectId' };
    }
    await registerPushDevice(token, Platform.OS === 'ios' ? 'ios' : 'android');
    currentPushToken = token;
    return { status: 'registered', token };
  } catch (error) {
    return {
      status: 'failed',
      reason: error instanceof Error ? error.message : 'unknown error',
    };
  }
}

export async function unregisterForDailyDigest(token: string): Promise<void> {
  await unregisterPushDevice(token);
  if (currentPushToken === token) {
    currentPushToken = null;
  }
}

export function addNotificationResponseListener(
  handler: (data: Record<string, unknown>) => void,
): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content.data;
    handler((data ?? {}) as Record<string, unknown>);
  });
  return () => subscription.remove();
}

export async function getLastNotificationResponseData(): Promise<Record<string, unknown> | null> {
  const response = await Notifications.getLastNotificationResponseAsync();
  if (!response) {
    return null;
  }
  return (response.notification.request.content.data ?? {}) as Record<string, unknown>;
}
