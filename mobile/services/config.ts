import { getApiBaseUrl } from './backendSettings';

/**
 * Resolved on every request so a backend address saved in settings takes effect
 * immediately, without restarting the app.
 */
export function apiBaseUrl(): string {
  return getApiBaseUrl();
}
