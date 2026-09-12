import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  DEFAULT_API_BASE_URL,
  checkBackendHealth,
  createBackendUrlStore,
  healthUrl,
  normalizeBackendUrl,
  resolveBackendUrl,
  validateBackendUrl,
  type BackendUrlStorage,
} from './backendUrl.ts';

function memoryStorage(initial: Record<string, string> = {}): BackendUrlStorage {
  const data = new Map(Object.entries(initial));
  return {
    getItem: async (key) => data.get(key) ?? null,
    setItem: async (key, value) => {
      data.set(key, value);
    },
    removeItem: async (key) => {
      data.delete(key);
    },
  };
}

test('normalizeBackendUrl trims and drops trailing slashes', () => {
  assert.equal(normalizeBackendUrl('  http://192.168.1.100:8000/  '), 'http://192.168.1.100:8000');
  assert.equal(normalizeBackendUrl('http://a.test:8000///'), 'http://a.test:8000');
});

test('validateBackendUrl accepts http and https with a host', () => {
  assert.deepEqual(validateBackendUrl('http://192.168.1.100:8000'), {
    ok: true,
    url: 'http://192.168.1.100:8000',
  });
  assert.deepEqual(validateBackendUrl('https://daily.example.com/'), {
    ok: true,
    url: 'https://daily.example.com',
  });
});

// The local deployment phase uses plain HTTP over the LAN, so it must be valid.
test('validateBackendUrl keeps LAN HTTP usable', () => {
  const result = validateBackendUrl('http://192.168.0.107:8000');
  assert.equal(result.ok, true);
});

test('validateBackendUrl rejects missing scheme, blank, and garbage input', () => {
  assert.equal(validateBackendUrl('').ok, false);
  assert.equal(validateBackendUrl('   ').ok, false);
  assert.equal(validateBackendUrl('192.168.1.100:8000').ok, false);
  assert.equal(validateBackendUrl('ftp://192.168.1.100').ok, false);
  assert.equal(validateBackendUrl('http://').ok, false);
});

test('validateBackendUrl explains a missing scheme', () => {
  const result = validateBackendUrl('192.168.1.100:8000');
  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.match(result.reason, /http:\/\//);
  }
});

test('resolveBackendUrl prefers the stored value over the build default', () => {
  assert.equal(
    resolveBackendUrl('http://10.0.0.5:8000', 'http://192.168.1.100:8000'),
    'http://10.0.0.5:8000',
  );
});

test('resolveBackendUrl falls back to the build default and then the constant', () => {
  assert.equal(resolveBackendUrl(null, 'http://192.168.1.100:8000'), 'http://192.168.1.100:8000');
  assert.equal(resolveBackendUrl(null, null), DEFAULT_API_BASE_URL);
  assert.equal(resolveBackendUrl('not-a-url', 'also-bad'), DEFAULT_API_BASE_URL);
});

test('healthUrl appends /health without doubling slashes', () => {
  assert.equal(healthUrl('http://192.168.1.100:8000/'), 'http://192.168.1.100:8000/health');
});

test('checkBackendHealth reports success on {"status":"ok"}', async () => {
  const calls: string[] = [];
  const fetchImpl = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(JSON.stringify({ status: 'ok' }), { status: 200 });
  }) as typeof fetch;

  const result = await checkBackendHealth('http://192.168.1.100:8000', fetchImpl);

  assert.deepEqual(result, { ok: true, status: 'ok' });
  assert.deepEqual(calls, ['http://192.168.1.100:8000/health']);
});

test('checkBackendHealth fails when the server is unreachable', async () => {
  const fetchImpl = (async () => {
    throw new TypeError('Network request failed');
  }) as typeof fetch;

  const result = await checkBackendHealth('http://192.168.1.100:8000', fetchImpl);

  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.equal(result.message, '无法连接服务器');
  }
});

test('checkBackendHealth fails on a non-200 response', async () => {
  const fetchImpl = (async () => new Response('nope', { status: 502 })) as typeof fetch;

  const result = await checkBackendHealth('http://192.168.1.100:8000', fetchImpl);

  assert.equal(result.ok, false);
  if (!result.ok) {
    assert.match(result.message, /502/);
  }
});

test('store loads the saved address and falls back to the build default', async () => {
  const saved = createBackendUrlStore({
    storage: memoryStorage({ 'ai_daily.backend_url': 'http://10.0.0.9:8000' }),
    key: 'ai_daily.backend_url',
    buildDefault: 'http://192.168.1.100:8000',
  });
  assert.equal(await saved.load(), 'http://10.0.0.9:8000');

  const empty = createBackendUrlStore({
    storage: memoryStorage(),
    key: 'ai_daily.backend_url',
    buildDefault: 'http://192.168.1.100:8000',
  });
  assert.equal(await empty.load(), 'http://192.168.1.100:8000');
});

test('store save persists only valid URLs and notifies subscribers', async () => {
  const storage = memoryStorage();
  const store = createBackendUrlStore({ storage, key: 'k', buildDefault: null });
  const seen: string[] = [];
  store.subscribe((url) => seen.push(url));

  assert.equal(await store.save('http://192.168.1.100:8000/'), 'http://192.168.1.100:8000');
  assert.equal(await storage.getItem('k'), 'http://192.168.1.100:8000');
  assert.ok(seen.includes('http://192.168.1.100:8000'));

  await assert.rejects(() => store.save('nonsense'), /http:\/\//);
  assert.equal(await storage.getItem('k'), 'http://192.168.1.100:8000');
});

test('store reset drops the override and returns to the build default', async () => {
  const storage = memoryStorage({ k: 'http://10.0.0.9:8000' });
  const store = createBackendUrlStore({
    storage,
    key: 'k',
    buildDefault: 'http://192.168.1.100:8000',
  });
  await store.load();

  assert.equal(await store.reset(), 'http://192.168.1.100:8000');
  assert.equal(await storage.getItem('k'), null);
});

// A broken storage layer must degrade to the default, not strand the app.
test('store survives storage failures', async () => {
  const broken: BackendUrlStorage = {
    getItem: async () => {
      throw new Error('storage unavailable');
    },
    setItem: async () => {
      throw new Error('storage unavailable');
    },
    removeItem: async () => {
      throw new Error('storage unavailable');
    },
  };
  const store = createBackendUrlStore({ storage: broken, key: 'k', buildDefault: null });

  assert.equal(await store.load(), DEFAULT_API_BASE_URL);
});
