import type { Settings } from '../types';
import { todayISO } from './defaults';

export function money(value: number, s: Settings, opts: { signed?: boolean; decimals?: number } = {}): string {
  const decimals = opts.decimals ?? 2;
  const n = Number.isFinite(value) ? value : 0;
  const abs = Math.abs(n);
  const formatted = abs.toLocaleString(s.locale || 'pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  const sign = n < 0 ? '-' : opts.signed && n > 0 ? '+' : '';
  return `${sign}${s.currencySymbol} ${formatted}`;
}

export function number(value: number, s: Settings, decimals = 0): string {
  return (Number.isFinite(value) ? value : 0).toLocaleString(s.locale || 'pt-BR', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function pct(value: number, decimals = 2, signed = false): string {
  const n = Number.isFinite(value) ? value : 0;
  return `${signed && n > 0 ? '+' : ''}${n.toFixed(decimals).replace('.', ',')}%`;
}

/** Formatação usada em eixos de gráficos (respeita "números compactos"). */
export function axisMoney(value: number, s: Settings): string {
  return s.compactNumbers ? shortMoney(value, s) : money(value, s, { decimals: 0 });
}

export function shortMoney(value: number, s: Settings): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${sign}${s.currencySymbol} ${(abs / 1_000_000).toFixed(1).replace('.', ',')}M`;
  if (abs >= 10_000) return `${sign}${s.currencySymbol} ${(abs / 1000).toFixed(1).replace('.', ',')}k`;
  return money(value, s);
}

/** dd/MM/yyyy | MM/dd/yyyy | yyyy-MM-dd */
export function formatDate(iso: string, s: Settings, withYear = true): string {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-');
  if (!y || !m || !d) return iso;
  const isUS = s.dateFormat.startsWith('MM');
  const isISO = s.dateFormat.startsWith('yyyy');
  if (!withYear) return isUS ? `${m}/${d}` : `${d}/${m}`;
  if (isUS) return `${m}/${d}/${y}`;
  if (isISO) return `${y}-${m}-${d}`;
  return `${d}/${m}/${y}`;
}

export function parseISO(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function isoOf(d: Date): string {
  return todayISO(d);
}

export function monthLabel(iso: string): string {
  const [y, m] = iso.split('-');
  const names = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
  return `${names[Number(m) - 1] || ''} ${y}`;
}

export function weekKey(iso: string): string {
  const d = parseISO(iso);
  const day = (d.getDay() + 6) % 7; // segunda = 0
  d.setDate(d.getDate() - day);
  return isoOf(d);
}

export function weekLabel(iso: string, s: Settings): string {
  return `Semana de ${formatDate(weekKey(iso), s, false)}`;
}

export function monthKey(iso: string): string {
  return iso.slice(0, 7);
}

export function addDays(iso: string, days: number): string {
  const d = parseISO(iso);
  d.setDate(d.getDate() + days);
  return isoOf(d);
}

export function daysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate();
}

export function hourLabel(time: string): string {
  return time ? time.slice(0, 2) + 'h' : '—';
}

export function downloadCsv(filename: string, rows: (string | number)[][]) {
  const esc = (v: string | number) => {
    const str = String(v ?? '');
    return /[";\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  const csv = '\uFEFF' + rows.map((r) => r.map(esc).join(';')).join('\r\n');
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}
