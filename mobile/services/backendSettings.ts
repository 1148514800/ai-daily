import AsyncStorage from '@react-native-async-storage/async-storage';
import { createBackendUrlStore } from '../lib/backendUrl';

const STORAGE_KEY = 'ai_daily.backend_url';

// One shared store keeps the in-memory value and persisted value in sync, so no
// request has to await storage.
const store = createBackendUrlStore({
  storage: AsyncStorage,
  key: STORAGE_KEY,
  buildDefault: process.env.EXPO_PUBLIC_API_BASE_URL,
});

export function getApiBaseUrl(): string {
  return store.get();
}

export function loadStoredBackendUrl(): Promise<string> {
  return store.load();
}

/**
 * Persist a new backend address. Invalid input is rejected instead of saved so
 * the app can never be left pointing at something unusable.
 */
export function saveBackendUrl(raw: string): Promise<string> {
  return store.save(raw);
}

/** Drop the override and fall back to the build-time / default address. */
export function resetBackendUrl(): Promise<string> {
  return store.reset();
}
