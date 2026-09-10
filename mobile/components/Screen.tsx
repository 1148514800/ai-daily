import type { ReactNode } from 'react';
import { Platform, StatusBar, StyleSheet, View, type ViewStyle } from 'react-native';
import { colors } from '../theme';

type ScreenProps = {
  children: ReactNode;
  style?: ViewStyle;
};

export function Screen({ children, style }: ScreenProps) {
  return (
    <View style={[styles.root, style]}>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.background,
    paddingTop: Platform.OS === 'android' ? StatusBar.currentHeight ?? 24 : 12,
  },
});
