import { StatusBar } from 'expo-status-bar';
import { FavoritesProvider } from './hooks/useFavorites';
import { RootNavigator } from './navigation/RootNavigator';

export default function App() {
  return (
    <FavoritesProvider>
      <StatusBar style="dark" />
      <RootNavigator />
    </FavoritesProvider>
  );
}
