export function formatMs(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const pad = (n: number) => String(n).padStart(2, '0');

  if (hours > 0) {
    return `${pad(hours)}:${pad(minutes)}:${pad(seconds)}`;
  }
  return `${pad(minutes)}:${pad(seconds)}`;
}

export function formatDate(
  ms: number | null | undefined,
  calendar: 'jalali' | 'gregorian' = 'jalali',
  timeZone: string = 'Asia/Tehran'
): string {
  if (!ms || ms <= 0) return '—';
  try {
    const date = new Date(ms);
    const cal = calendar === 'jalali' ? 'persian' : 'gregory';
    return new Intl.DateTimeFormat('fa-IR', {
      calendar: cal,
      timeZone: timeZone || 'Asia/Tehran',
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  } catch {
    return new Date(ms).toLocaleString('fa-IR');
  }
}

export function formatBytes(bytes: number): string {
  if (!bytes || bytes <= 0) return '۰ بایت';
  const k = 1024;
  const sizes = ['بایت', 'کیلوبایت', 'مگابایت', 'گیگابایت'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  const val = (bytes / Math.pow(k, i)).toFixed(i === 0 ? 0 : 1);
  return `${val} ${sizes[i]}`;
}
