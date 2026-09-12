/**
 * Pure helpers for the configurable backend address.
 *
 * Kept free of React Native imports so it can be unit tested with plain Node.
 * The stored URL always wins over the build-time EXPO_PUBLIC_API_BASE_URL, so a
 * changed LAN IP or a future server never requires a new APK.
 */

export const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';

export type UrlValidation =
  | { ok: true; url: string }
  | { ok: false; reason: string };

export type HealthCheckResult =
  | { ok: true; status: string }
  | { ok: false; message: string };

/** Trim and drop trailing slashes so path concatenation stays predictable. */
export function normalizeBackendUrl(raw: string): string {
  return raw.trim().replace(/\/+$/, '');
}

/**
 * Accept only well-formed http(s) URLs with a host.
 *
 * The app talks plain HTTP during the local deployment phase, so rejecting
 * cleartext here would break the supported setup. HTTPS is accepted as well.
 */
export function validateBackendUrl(raw: string): UrlValidation {
  const url = normalizeBackendUrl(raw);
  if (!url) {
    return { ok: false, reason: '请输入后端地址' };
  }
  if (!/^https?:\/\//i.test(url)) {
    return { ok: false, reason: '地址需要以 http:// 或 https:// 开头' };
  }
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, reason: '地址格式不正确' };
  }
  if (!parsed.hostname) {
    return { ok: false, reason: '地址缺少主机名' };
  }
  return { ok: true, url };
}

/** Stored value first, then the build-time default, then a safe fallback. */
export function resolveBackendUrl(
  stored: string | null | undefined,
  buildDefault: string | null | undefined,
): string {
  const candidates = [stored, buildDefault, DEFAULT_API_BASE_URL];
  for (const candidate of candidates) {
    if (!candidate) {
      continue;
    }
    const result = validateBackendUrl(candidate);
    if (result.ok) {
      return result.url;
    }
  }
  return DEFAULT_API_BASE_URL;
}

export function healthUrl(baseUrl: string): string {
  return `${normalizeBackendUrl(baseUrl)}/health`;
}

/**
 * Ask the backend for its health payload.
 *
 * Never throws: an unreachable server is a normal state that the settings
 * screen turns into "无法连接服务器".
 */
export async function checkBackendHealth(
  baseUrl: string,
  fetchImpl: typeof fetch = fetch,
  timeoutMs = 8000,
): Promise<HealthCheckResult> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(healthUrl(baseUrl), { signal: controller.signal });
    if (!response.ok) {
      return { ok: false, message: `服务返回 HTTP ${response.status}` };
    }
    const payload = (await response.json()) as { status?: unknown };
    if (payload?.status !== 'ok') {
      return { ok: false, message: '服务响应异常' };
    }
    return { ok: true, status: 'ok' };
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      return { ok: false, message: '连接超时，请检查地址与网络' };
    }
    return { ok: false, message: '无法连接服务器' };
  } finally {
    clearTimeout(timer);
  }
}

/** Minimal async key/value surface, matching what AsyncStorage provides. */
export type BackendUrlStorage = {
  getItem: (key: string) => Promise<string | null>;
  setItem: (key: string, value: string) => Promise<void>;
  removeItem: (key: string) => Promise<void>;
};

export type BackendUrlStore = {
  get: () => string;
  load: () => Promise<string>;
  save: (raw: string) => Promise<string>;
  reset: () => Promise<string>;
  subscribe: (listener: (url: string) => void) => () => void;
};

/**
 * Precedence: saved URL, then the build-time default, then the hardcoded
 * fallback. Storage failures degrade to the default instead of throwing, so a
 * broken storage layer can never block reading the digest.
 */
export function createBackendUrlStore(options: {
  storage: BackendUrlStorage;
  key: string;
  buildDefault?: string | null;
}): BackendUrlStore {
  const { storage, key, buildDefault } = options;
  const listeners = new Set<(url: string) => void>();
  let current = resolveBackendUrl(null, buildDefault);

  function set(url: string): string {
    current = url;
    for (const listener of listeners) {
      listener(url);
    }
    return url;
  }

  return {
    get: () => current,
    async load() {
      try {
        const stored = await storage.getItem(key);
        return set(resolveBackendUrl(stored, buildDefault));
      } catch {
        return set(resolveBackendUrl(null, buildDefault));
      }
    },
    async save(raw: string) {
      const result = validateBackendUrl(raw);
      if (!result.ok) {
        throw new Error(result.reason);
      }
      await storage.setItem(key, result.url);
      return set(result.url);
    },
    async reset() {
      await storage.removeItem(key);
      return set(resolveBackendUrl(null, buildDefault));
    },
    subscribe(listener: (url: string) => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
