import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { FavoritesProvider } from './hooks/useFavorites';
import { RootNavigator } from './navigation/RootNavigator';
import { registerForDailyDigest } from './services/notifications';

export default function App() {
  useEffect(() => {
    // Fire-and-forget: a denied permission must never block reading the digest.
    void registerForDailyDigest();
  }, []);

  return (
    <FavoritesProvider>
      <StatusBar style="dark" />
      <RootNavigator />
    </FavoritesProvider>
  );
}
