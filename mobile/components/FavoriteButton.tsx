import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, Text } from 'react-native';
import { useFavorites } from '../hooks/useFavorites';
import type { FavoriteItemType } from '../types';
import { colors, radius, spacing } from '../theme';

type FavoriteButtonProps = {
  itemType: FavoriteItemType;
  itemId: string;
};

export function FavoriteButton({ itemType, itemId }: FavoriteButtonProps) {
  const { isFavorite, pendingKey, toggleFavorite } = useFavorites();
  const [failed, setFailed] = useState(false);
  const active = isFavorite(itemType, itemId);
  const pending = pendingKey === `${itemType}:${itemId}`;

  async function onPress() {
    setFailed(false);
    try {
      await toggleFavorite(itemType, itemId);
    } catch {
      setFailed(true);
    }
  }

  return (
    <Pressable
      onPress={onPress}
      disabled={pending}
      android_ripple={{ color: colors.overlay }}
      accessibilityRole="button"
      accessibilityState={{ selected: active, busy: pending }}
      style={({ pressed }) => [
        styles.button,
        active && styles.activeButton,
        pressed && styles.pressed,
      ]}
    >
      {pending ? (
        <ActivityIndicator size="small" color={active ? colors.accent : colors.textSecondary} />
      ) : (
        <Text style={[styles.label, active && styles.activeLabel]}>
          {active ? '★ 已收藏' : '☆ 收藏'}
        </Text>
      )}
      {failed ? <Text style={styles.error}>操作失败，请重试</Text> : null}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  button: {
    borderRadius: radius.sm,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 10,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
    justifyContent: 'center',
    minHeight: 40,
  },
  activeButton: {
    borderColor: colors.accent,
    backgroundColor: colors.accentSoft,
  },
  pressed: {
    opacity: 0.9,
  },
  label: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  activeLabel: {
    color: colors.accent,
  },
  error: {
    marginTop: 4,
    fontSize: 12,
    color: '#B3261E',
  },
});
