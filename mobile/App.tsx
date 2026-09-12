import { useEffect, useState } from 'react';
import { ActivityIndicator, StyleSheet, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { FavoritesProvider } from './hooks/useFavorites';
import { RootNavigator } from './navigation/RootNavigator';
import { loadStoredBackendUrl } from './services/backendSettings';
import { colors } from './theme';

export default function App() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // Read the saved backend address once, before the first request goes out,
    // so the app never queries the wrong host on launch.
    let cancelled = false;
    loadStoredBackendUrl().finally(() => {
      if (!cancelled) {
        setReady(true);
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <View style={styles.splash}>
        <StatusBar style="dark" />
        <ActivityIndicator color={colors.accent} />
      </View>
    );
  }

  return (
    <FavoritesProvider>
      <StatusBar style="dark" />
      <RootNavigator />
    </FavoritesProvider>
  );
}

const styles = StyleSheet.create({
  splash: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.background,
  },
});
