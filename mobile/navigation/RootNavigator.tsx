import { useEffect, useState } from 'react';
import { BackHandler, StyleSheet, View } from 'react-native';
import { TabBar } from '../components/TabBar';
import { FavoritesScreen } from '../screens/FavoritesScreen';
import { DigestScreen } from '../screens/DigestScreen';
import { GitHubScreen } from '../screens/GitHubScreen';
import { HistoryScreen } from '../screens/HistoryScreen';
import { NewsDetailScreen } from '../screens/NewsDetailScreen';
import { SettingsScreen } from '../screens/SettingsScreen';
import { TodayScreen } from '../screens/TodayScreen';
import { colors } from '../theme';
import type { TabKey } from '../types';

type Route =
  | { name: 'tabs' }
  | { name: 'news'; id: string }
  | { name: 'digest'; date: string };

export function RootNavigator() {
  const [tab, setTab] = useState<TabKey>('today');
  const [stack, setStack] = useState<Route[]>([{ name: 'tabs' }]);
  const current = stack[stack.length - 1];

  function push(route: Route) {
    setStack((routes) => [...routes, route]);
  }

  function pop() {
    setStack((routes) => (routes.length > 1 ? routes.slice(0, -1) : routes));
  }

  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (stack.length > 1) {
        pop();
        return true;
      }
      return false;
    });
    return () => subscription.remove();
  }, [stack.length]);

  let screen = null;
  if (current.name === 'news') {
    screen = <NewsDetailScreen newsId={current.id} onBack={pop} />;
  } else if (current.name === 'digest') {
    screen = (
      <DigestScreen
        date={current.date}
        onBack={pop}
        onOpenNews={(id) => push({ name: 'news', id })}
      />
    );
  } else if (tab === 'github') {
    screen = <GitHubScreen />;
  } else if (tab === 'favorites') {
    screen = <FavoritesScreen onOpenNews={(id) => push({ name: 'news', id })} />;
  } else if (tab === 'history') {
    screen = <HistoryScreen onOpenDigest={(date) => push({ name: 'digest', date })} />;
  } else if (tab === 'settings') {
    screen = <SettingsScreen />;
  } else {
    screen = <TodayScreen onOpenNews={(id) => push({ name: 'news', id })} />;
  }

  return (
    <View style={styles.root}>
      <View style={styles.screen}>{screen}</View>
      {current.name === 'tabs' ? <TabBar active={tab} onChange={setTab} /> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
  },
  screen: {
    flex: 1,
  },
});
