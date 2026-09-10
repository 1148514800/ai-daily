import { useCallback, useEffect, useState } from 'react';
import { ApiError } from '../services/api';

type ResourceState<T> =
  | { status: 'loading'; data: null; error: null }
  | { status: 'error'; data: null; error: ApiError }
  | { status: 'success'; data: T; error: null };

const EMPTY_DEPS: readonly unknown[] = [];

export function useAsyncResource<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[] = EMPTY_DEPS,
) {
  const [state, setState] = useState<ResourceState<T>>({
    status: 'loading',
    data: null,
    error: null,
  });
  const [requestId, setRequestId] = useState(0);

  const reload = useCallback(() => {
    setRequestId((value) => value + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading', data: null, error: null });

    loader()
      .then((data) => {
        if (!cancelled) {
          setState({ status: 'success', data, error: null });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const apiError =
            error instanceof ApiError ? error : new ApiError('内容加载失败', 0);
          setState({ status: 'error', data: null, error: apiError });
        }
      });

    return () => {
      cancelled = true;
    };
    // loader is invoked from the latest render when deps/requestId change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestId, ...deps]);

  return { ...state, reload };
}
