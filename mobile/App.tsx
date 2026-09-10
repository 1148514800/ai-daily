import { StatusBar } from 'expo-status-bar';
import { RootNavigator } from './navigation/RootNavigator';

export default function App() {
  return (
    <>
      <StatusBar style="dark" />
      <RootNavigator />
    </>
  );
}
