const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

export function parseISODate(value: string): Date {
  const [year, month, day] = value.split('-').map(Number);
  return new Date(year, month - 1, day);
}

export function formatLongDate(value: string): string {
  const date = parseISODate(value);
  const weekday = WEEKDAYS[date.getDay()];
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 星期${weekday}`;
}

export function formatShortDate(value: string): string {
  const date = parseISODate(value);
  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function formatStars(value: number): string {
  if (value >= 1000) {
    const compact = value / 1000;
    return `${compact >= 10 ? compact.toFixed(0) : compact.toFixed(1).replace(/\.0$/, '')}k`;
  }
  return String(value);
}

export function formatStarsDelta(value: number): string {
  return `+${formatStars(value)}`;
}
