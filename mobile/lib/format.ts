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

/** ``9月12日 周六`` — the short date plus its weekday, for the history list. */
export function formatShortDateWithWeekday(value: string): string {
  const date = parseISODate(value);
  return `${formatShortDate(value)} 周${WEEKDAYS[date.getDay()]}`;
}

export function formatTime(value: string): string {
  const isoMatch = value.match(/T(\d{2}:\d{2})/);
  if (isoMatch) {
    return isoMatch[1];
  }
  if (value.includes(' ')) {
    return value.split(' ')[1]?.slice(0, 5) ?? value;
  }
  return value;
}

export function formatStars(value: number): string {
  if (value >= 1000) {
    const compact = value / 1000;
    const digits = compact >= 100 ? 0 : 1;
    return `${compact.toFixed(digits).replace(/\.0$/, '')}k`;
  }
  return String(value);
}

export function formatStarsDelta(value: number | null | undefined): string {
  if (value == null) {
    return '';
  }
  return `今日 +${formatStars(value)}`;
}
