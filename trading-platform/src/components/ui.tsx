import React, { useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, AlertTriangle, CheckCircle2, Info, Inbox, ChevronRight } from 'lucide-react';
import { useStore } from '../state/store';
import { money, formatDate } from '../lib/format';
import type { TradeResult } from '../types';

export function Card({ children, className = '', ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={`card ${className}`} {...rest}>{children}</div>;
}

export function CardHead({ title, sub, right }: { title: string; sub?: string; right?: React.ReactNode }) {
  return (
    <div className="card-head">
      <div><h3>{title}</h3>{sub && <div className="sub">{sub}</div>}</div>
      {right && <div className="right">{right}</div>}
    </div>
  );
}

export function Field({ label, hint, children, full = false }: { label: string; hint?: string; children: React.ReactNode; full?: boolean }) {
  return (
    <div className={`field ${full ? 'field-full' : ''}`}>
      <label className="field-label">{label}</label>
      {children}
      {hint && <span className="field-hint">{hint}</span>}
    </div>
  );
}

export function NumberField({ label, value, onChange, step = 1, min, max, hint, prefix, suffix, full, disabled }: {
  label: string; value: number | string; onChange: (n: number) => void; step?: number; min?: number; max?: number;
  hint?: string; prefix?: string; suffix?: string; full?: boolean; disabled?: boolean;
}) {
  return (
    <Field label={label} hint={hint} full={full}>
      <div className="inline-value">
        {prefix && <span className="btn" style={{ pointerEvents: 'none', padding: '9px 10px' }}>{prefix}</span>}
        <input className="input mono" type="number" value={value} step={step} min={min} max={max} disabled={disabled}
          onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))} />
        {suffix && <span className="btn" style={{ pointerEvents: 'none', padding: '9px 10px' }}>{suffix}</span>}
      </div>
    </Field>
  );
}

/** Campo com alternância R$ / % para metas e limites. */
export function ModeValueField({ label, value, onChange, hint }: {
  label: string; value: { mode: 'currency' | 'percent'; value: number };
  onChange: (v: { mode: 'currency' | 'percent'; value: number }) => void; hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <div className="inline-value">
        <input className="input mono" type="number" step="0.1" value={value.value}
          onChange={(e) => onChange({ ...value, value: Number(e.target.value) })} />
        <div className="mode-toggle">
          <button type="button" className={value.mode === 'currency' ? 'on' : ''} onClick={() => onChange({ ...value, mode: 'currency' })}>R$</button>
          <button type="button" className={value.mode === 'percent' ? 'on' : ''} onClick={() => onChange({ ...value, mode: 'percent' })}>%</button>
        </div>
      </div>
    </Field>
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label?: string }) {
  return (
    <label className="check-row">
      <span className="switch">
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        <span />
      </span>
      {label}
    </label>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void;
}) {
  return (
    <div className="mode-toggle">
      {options.map((o) => (
        <button type="button" key={o.value} className={value === o.value ? 'on' : ''} onClick={() => onChange(o.value)}>{o.label}</button>
      ))}
    </div>
  );
}

export function ResultBadge({ result }: { result: TradeResult }) {
  return <span className={`badge badge-${result.toLowerCase()}`}>{result}</span>;
}

export function StatCard({ label, value, foot, tone, icon, className = '' }: {
  label: string; value: React.ReactNode; foot?: React.ReactNode;
  tone?: 'pos' | 'neg' | 'accent'; icon?: React.ReactNode; className?: string;
}) {
  return (
    <div className={`card stat-card ${tone || ''} ${className}`}>
      <div className="stat-top">{icon}{label}</div>
      <div>
        <div className={`stat-value ${tone ? `value-${tone}` : ''} ${String(value).length > 16 ? 'sm' : ''}`}>{value}</div>
        {foot && <div className="stat-foot">{foot}</div>}
      </div>
    </div>
  );
}

export function EmptyState({ title, text, action, icon }: { title: string; text: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="empty-state">
      {icon || <Inbox size={34} />}
      <h4>{title}</h4>
      <p>{text}</p>
      {action}
    </div>
  );
}

export function Modal({ title, sub, children, footer, onClose, wide, narrow }: {
  title: string; sub?: string; children: React.ReactNode; footer?: React.ReactNode;
  onClose: () => void; wide?: boolean; narrow?: boolean;
}) {
  useEffect(() => {
    const fn = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', fn);
    return () => window.removeEventListener('keydown', fn);
  }, [onClose]);
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className={`modal ${wide ? 'wide' : ''} ${narrow ? 'narrow' : ''}`}>
        <div className="modal-head">
          <div><h3>{title}</h3>{sub && <div className="sub">{sub}</div>}</div>
          <button className="icon-btn" style={{ marginLeft: 'auto' }} onClick={onClose} aria-label="Fechar"><X size={16} /></button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}

export function ConfirmDialog({ title, text, confirmLabel = 'Confirmar', danger, onConfirm, onClose }: {
  title: string; text: React.ReactNode; confirmLabel?: string; danger?: boolean;
  onConfirm: () => void; onClose: () => void;
}) {
  return (
    <Modal title={title} onClose={onClose} narrow footer={<>
      <button className="btn" onClick={onClose}>Cancelar</button>
      <button className={`btn ${danger ? 'danger' : 'primary'}`} onClick={() => { onConfirm(); onClose(); }}>{confirmLabel}</button>
    </>}>
      <div className="confirm-text">{text}</div>
    </Modal>
  );
}

export function Notice({ children, kind = 'info' }: { children: React.ReactNode; kind?: 'info' | 'warn' | 'danger' }) {
  const Icon = kind === 'warn' || kind === 'danger' ? AlertTriangle : Info;
  return <div className={`notice ${kind}`}><Icon size={15} /><div>{children}</div></div>;
}

export function Toasts() {
  const { toasts, dismissToast } = useStore();
  return createPortal(
    <div className="toast-stack">
      {toasts.map((t) => {
        const Icon = t.kind === 'success' ? CheckCircle2 : t.kind === 'error' ? AlertTriangle : Info;
        return (
          <div key={t.id} className={`toast ${t.kind}`} onClick={() => dismissToast(t.id)}>
            <Icon size={16} color={t.kind === 'success' ? 'var(--pos)' : t.kind === 'error' ? 'var(--neg)' : 'var(--accent)'} />
            <span>{t.text}</span>
          </div>
        );
      })}
    </div>,
    document.body,
  );
}

export function ChartTooltip({ active, payload, label, formatter }: {
  active?: boolean; payload?: Array<{ name?: string; value?: number | string; color?: string; dataKey?: string; payload?: Record<string, unknown> }>;
  label?: string | number; formatter?: (v: number, name: string) => string;
}) {
  const { data, refDate } = useStore();
  if (!active || !payload?.length) return null;
  const isoCandidate = String(label || payload[0]?.payload?.date || '');
  const displayLabel = /^\d{4}-\d{2}-\d{2}$/.test(isoCandidate) ? formatDate(isoCandidate, data.settings) : isoCandidate || String(refDate);
  return (
    <div className="chart-tooltip">
      <div className="tt-title">{displayLabel}</div>
      {payload.map((p, i) => (
        <div className="tt-row" key={i}>
          <span><i className="legend-dot" style={{ background: p.color }} />{p.name || p.dataKey}</span>
          <b>{formatter ? formatter(Number(p.value), String(p.name || p.dataKey || '')) : (typeof p.value === 'number' ? money(p.value, data.settings) : String(p.value))}</b>
        </div>
      ))}
    </div>
  );
}

export function DateRangeBar({ from, to, onChange, extra }: {
  from: string; to: string; onChange: (r: { from: string; to: string }) => void; extra?: React.ReactNode;
}) {
  const presets = [
    { label: '7 dias', days: 7 }, { label: '30 dias', days: 30 },
    { label: '90 dias', days: 90 }, { label: 'Todo período', days: 0 },
  ];
  return (
    <div className="card pad-0 mb-14">
      <div className="filter-bar" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
        <Field label="De"><input type="date" className="input" value={from} onChange={(e) => onChange({ from: e.target.value, to })} /></Field>
        <Field label="Até"><input type="date" className="input" value={to} onChange={(e) => onChange({ from, to: e.target.value })} /></Field>
        <div className="field">
          <label className="field-label">Atalhos</label>
          <div className="btn-row">
            {presets.map((p) => (
              <button key={p.label} className="btn sm" onClick={() => {
                if (p.days === 0) onChange({ from: '', to: '' });
                else {
                  const end = new Date(); const start = new Date();
                  start.setDate(start.getDate() - p.days);
                  onChange({ from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) });
                }
              }}>{p.label}</button>
            ))}
          </div>
        </div>
        {extra}
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: React.ReactNode }) {
  return (
    <div className="page-header">
      <div><h2>{title}</h2><p>{description}</p></div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export function Breadcrumb({ text }: { text: string }) {
  return <div className="row tiny muted mb-14"><ChevronRight size={11} />{text}</div>;
}
