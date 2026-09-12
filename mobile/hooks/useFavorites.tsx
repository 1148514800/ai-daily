import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import {
  ApiError,
  addFavorite as addFavoriteRequest,
  deleteFavorite as deleteFavoriteRequest,
  fetchFavorites,
} from '../services/api';
import type { Favorite, FavoriteItemType } from '../types';

type FavoritesStatus = 'loading' | 'error' | 'success';

type FavoritesContextValue = {
  status: FavoritesStatus;
  error: string | null;
  favorites: Favorite[];
  pendingKey: string | null;
  reload: () => void;
  isFavorite: (itemType: FavoriteItemType, itemId: string) => boolean;
  toggleFavorite: (itemType: FavoriteItemType, itemId: string) => Promise<void>;
};

const FavoritesContext = createContext<FavoritesContextValue | null>(null);

function keyOf(itemType: FavoriteItemType, itemId: string): string {
  return `${itemType}:${itemId}`;
}

function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ApiError && error.message) {
    return error.message;
  }
  return fallback;
}

export function FavoritesProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<FavoritesStatus>('loading');
  const [error, setError] = useState<string | null>(null);
  const [favorites, setFavorites] = useState<Favorite[]>([]);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(0);

  const reload = useCallback(() => {
    setRequestId((value) => value + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    setError(null);

    fetchFavorites()
      .then((data) => {
        if (cancelled) {
          return;
        }
        setFavorites(data);
        setStatus('success');
      })
      .catch((requestError: unknown) => {
        if (cancelled) {
          return;
        }
        setError(messageOf(requestError, '收藏加载失败'));
        setStatus('error');
      });

    return () => {
      cancelled = true;
    };
  }, [requestId]);

  const isFavorite = useCallback(
    (itemType: FavoriteItemType, itemId: string) =>
      favorites.some((entry) => entry.item_type === itemType && entry.item.id === itemId),
    [favorites],
  );

  const toggleFavorite = useCallback(
    async (itemType: FavoriteItemType, itemId: string) => {
      const key = keyOf(itemType, itemId);
      setPendingKey(key);
      setError(null);
      try {
        const existing = favorites.find(
          (entry) => entry.item_type === itemType && entry.item.id === itemId,
        );
        if (existing) {
          await deleteFavoriteRequest(existing.id);
          setFavorites((current) => current.filter((entry) => entry.id !== existing.id));
        } else {
          const created = await addFavoriteRequest(itemType, itemId);
          setFavorites((current) =>
            current.some((entry) => entry.id === created.id)
              ? current
              : [created, ...current],
          );
        }
      } catch (requestError: unknown) {
        setError(messageOf(requestError, '收藏操作失败'));
        throw requestError;
      } finally {
        setPendingKey(null);
      }
    },
    [favorites],
  );

  const value = useMemo<FavoritesContextValue>(
    () => ({ status, error, favorites, pendingKey, reload, isFavorite, toggleFavorite }),
    [status, error, favorites, pendingKey, reload, isFavorite, toggleFavorite],
  );

  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>;
}

export function useFavorites(): FavoritesContextValue {
  const value = useContext(FavoritesContext);
  if (!value) {
    throw new Error('useFavorites must be used inside FavoritesProvider');
  }
  return value;
}
