import { Pressable, StyleSheet, Text, View } from 'react-native';
import type { TabKey } from '../types';
import { colors, spacing } from '../theme';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'today', label: '今日' },
  { key: 'github', label: 'GitHub' },
  { key: 'favorites', label: '收藏' },
  { key: 'history', label: '历史' },
  { key: 'settings', label: '设置' },
];

type TabBarProps = {
  active: TabKey;
  onChange: (tab: TabKey) => void;
};

export function TabBar({ active, onChange }: TabBarProps) {
  return (
    <View style={styles.bar}>
      {TABS.map((tab) => {
        const selected = tab.key === active;
        return (
          <Pressable
            key={tab.key}
            onPress={() => onChange(tab.key)}
            style={styles.item}
            accessibilityRole="tab"
            accessibilityState={{ selected }}
          >
            <Text style={[styles.label, selected && styles.activeLabel]}>{tab.label}</Text>
            <View style={[styles.indicator, selected && styles.activeIndicator]} />
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    backgroundColor: colors.surface,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingHorizontal: spacing.sm,
    paddingTop: 8,
    paddingBottom: 14,
  },
  item: {
    flex: 1,
    alignItems: 'center',
    paddingVertical: 8,
  },
  label: {
    fontSize: 14,
    lineHeight: 20,
    color: colors.textTertiary,
    fontWeight: '500',
  },
  activeLabel: {
    color: colors.text,
  },
  indicator: {
    marginTop: 6,
    height: 3,
    width: 18,
    borderRadius: 99,
    backgroundColor: 'transparent',
  },
  activeIndicator: {
    backgroundColor: colors.accent,
  },
});
