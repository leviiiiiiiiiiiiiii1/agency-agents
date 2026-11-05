import React from 'react';
import {
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, Cell, PieChart, Pie,
  XAxis, YAxis, CartesianGrid, Tooltip, LineChart, Line, ReferenceLine, Legend,
} from 'recharts';
import { ChartTooltip } from './ui';
import { useStore } from '../state/store';
import { money, axisMoney, formatDate } from '../lib/format';
import { equityCurve, type EquityPoint, type GroupStat } from '../lib/calc';

const axis = { stroke: 'var(--text-3)', fontSize: 10, tickLine: false, axisLine: false };
const gridStroke = 'var(--grid-line)';

const TT = (formatter?: (v: number, name: string) => string) =>
  (props: unknown) => <ChartTooltip {...(props as Record<string, unknown>)} formatter={formatter} />;

export function EquityChart({ points, height = 260, showNet = false }: { points: EquityPoint[]; height?: number; showNet?: boolean }) {
  const { data } = useStore();
  const prefs = data.settings.charts;
  const s = data.settings;
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
              <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={prefs.grid ? gridStroke : 'transparent'} vertical={false} />
          <XAxis dataKey="date" {...axis} tickFormatter={(v) => formatDate(String(v), s, false)} minTickGap={24} />
          <YAxis {...axis} width={62} tickFormatter={(v) => axisMoney(Number(v), s)} />
          <Tooltip content={TT((v, n) => money(v, s) + (n.includes('Assert') ? '%' : ''))} cursor={{ stroke: 'var(--accent)', strokeDasharray: '3 3' }} />
          <ReferenceLine y={s.initialBalance} stroke="var(--text-3)" strokeDasharray="4 4" />
          {showNet && <Area type="monotone" dataKey="cumulative" name="Lucro acumulado" stroke="var(--accent)" strokeWidth={2} fill="url(#equityGrad)" dot={false} activeDot={{ r: 5 }} isAnimationActive={prefs.animations} />}
          {!showNet && <Area type="monotone" dataKey="balance" name="Saldo" stroke="var(--accent)" strokeWidth={2.2} fill="url(#equityGrad)" dot={false} activeDot={{ r: 5, fill: 'var(--accent)' }} isAnimationActive={prefs.animations} />}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function DayBars({ points, height = 240 }: { points: EquityPoint[]; height?: number }) {
  const { data } = useStore();
  const prefs = data.settings.charts;
  const s = data.settings;
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={prefs.grid ? gridStroke : 'transparent'} vertical={false} />
          <XAxis dataKey="date" {...axis} tickFormatter={(v) => formatDate(String(v), s, false)} minTickGap={22} />
          <YAxis {...axis} width={62} tickFormatter={(v) => axisMoney(Number(v), s)} />
          <Tooltip content={TT((v) => money(v, s, { signed: true }))} cursor={{ fill: 'var(--accent-soft)' }} />
          <ReferenceLine y={0} stroke="var(--text-3)" />
          <Bar dataKey="net" name="Resultado do dia" radius={[3, 3, 0, 0]} maxBarSize={26} isAnimationActive={prefs.animations}>
            {points.map((p, i) => <Cell key={i} fill={p.net >= 0 ? 'var(--pos)' : 'var(--neg)'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function ResultPie({ wins, losses, draws, height = 220 }: { wins: number; losses: number; draws: number; height?: number }) {
  const pieData = [
    { name: 'WIN', value: wins, color: 'var(--pos)' },
    { name: 'LOSS', value: losses, color: 'var(--neg)' },
    { name: 'DRAW', value: draws, color: 'var(--text-3)' },
  ].filter((d) => d.value > 0);
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={pieData} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="82%" paddingAngle={3} stroke="none">
            {pieData.map((d) => <Cell key={d.name} fill={d.color} />)}
          </Pie>
          <Tooltip content={TT((v) => `${v} operações`)} />
          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: 'var(--text-2)' }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}

export function WinRateLine({ points, height = 230 }: { points: EquityPoint[]; height?: number }) {
  const { data } = useStore();
  const prefs = data.settings.charts;
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={prefs.grid ? gridStroke : 'transparent'} vertical={false} />
          <XAxis dataKey="date" {...axis} tickFormatter={(v) => formatDate(String(v), data.settings, false)} minTickGap={24} />
          <YAxis {...axis} width={36} domain={[0, 100]} tickFormatter={(v) => `${v}%`} />
          <Tooltip content={TT((v) => `${Number(v).toFixed(1).replace('.', ',')}%`)} cursor={{ stroke: 'var(--accent)', strokeDasharray: '3 3' }} />
          <ReferenceLine y={50} stroke="var(--text-3)" strokeDasharray="4 4" />
          <Line type="monotone" dataKey="winRate" name="Assertividade acumulada" stroke="var(--accent)" strokeWidth={2.2} dot={false} activeDot={{ r: 5 }} isAnimationActive={prefs.animations} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Gráfico horizontal de barras para rankings por dimensão. */
export function GroupBars({ groups, height, colorByValue = true }: { groups: GroupStat[]; height?: number; colorByValue?: boolean }) {
  const { data } = useStore();
  const prefs = data.settings.charts;
  const s = data.settings;
  const items = groups.slice(0, 12);
  const h = height || Math.max(200, items.length * 34 + 40);
  return (
    <div style={{ width: '100%', height: h }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={items} layout="vertical" margin={{ top: 4, right: 18, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={prefs.grid ? gridStroke : 'transparent'} horizontal={false} />
          <XAxis type="number" {...axis} tickFormatter={(v) => axisMoney(Number(v), s)} />
          <YAxis type="category" dataKey="label" {...axis} width={104} />
          <Tooltip content={TT((v) => money(v, s, { signed: true }))} cursor={{ fill: 'var(--accent-soft)' }} />
          <ReferenceLine x={0} stroke="var(--text-3)" />
          <Bar dataKey="net" name="Resultado" radius={[0, 3, 3, 0]} maxBarSize={18} isAnimationActive={prefs.animations}>
            {items.map((g) => <Cell key={g.key} fill={!colorByValue ? 'var(--accent)' : g.net >= 0 ? 'var(--pos)' : 'var(--neg)'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function GroupTable({ groups, title }: { groups: GroupStat[]; title?: string }) {
  const { data } = useStore();
  const s = data.settings;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead><tr>
          <th>{title || 'Grupo'}</th><th className="num">Ops</th><th className="num">W / L / D</th>
          <th className="num">Assertividade</th><th className="num">Payout médio</th><th className="num">Resultado</th>
        </tr></thead>
        <tbody>
          {groups.length === 0 && <tr><td colSpan={6} className="center muted" style={{ padding: 24 }}>Sem dados no período selecionado</td></tr>}
          {groups.map((g) => (
            <tr key={g.key}>
              <td className="strong">{g.label}</td>
              <td className="num">{g.count}</td>
              <td className="num"><span className="value-pos">{g.wins}</span> / <span className="value-neg">{g.losses}</span> / {g.draws}</td>
              <td className="num">{g.winRate.toFixed(1).replace('.', ',')}%</td>
              <td className="num">{g.avgPayout.toFixed(1).replace('.', ',')}%</td>
              <td className={`num ${g.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(g.net, s, { signed: true })}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MultiSeriesChart({ data: chartData, series, height = 250 }: {
  data: Record<string, string | number>[];
  series: { key: string; label: string; color: string }[];
  height?: number;
}) {
  const { data } = useStore();
  const prefs = data.settings.charts;
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={prefs.grid ? gridStroke : 'transparent'} vertical={false} />
          <XAxis dataKey="label" {...axis} minTickGap={20} />
          <YAxis {...axis} width={62} tickFormatter={(v) => axisMoney(Number(v), data.settings)} />
          <Tooltip content={TT((v) => money(v, data.settings))} />
          <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11, color: 'var(--text-2)' }} />
          <ReferenceLine y={0} stroke="var(--text-3)" />
          {series.map((s) => <Line key={s.key} type="monotone" dataKey={s.key} name={s.label} stroke={s.color} strokeWidth={2} dot={false} activeDot={{ r: 4 }} isAnimationActive={prefs.animations} />)}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function SimpleBars({ data, height = 250, name = 'Resultado' }: {
  data: { label: string; value: number }[]; height?: number; name?: string;
}) {
  const { data: store } = useStore();
  const prefs = store.settings.charts;
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, left: 4, bottom: 0 }}>
          <CartesianGrid stroke={prefs.grid ? gridStroke : 'transparent'} vertical={false} />
          <XAxis dataKey="label" {...axis} minTickGap={12} />
          <YAxis {...axis} width={62} tickFormatter={(v) => axisMoney(Number(v), store.settings)} />
          <Tooltip content={TT((v) => money(v, store.settings, { signed: true }))} cursor={{ fill: 'var(--accent-soft)' }} />
          <ReferenceLine y={0} stroke="var(--text-3)" />
          <Bar dataKey="value" name={name} radius={[3, 3, 0, 0]} maxBarSize={42} isAnimationActive={prefs.animations}>
            {data.map((d, i) => <Cell key={i} fill={d.value >= 0 ? 'var(--pos)' : 'var(--neg)'} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Sparkline({ points, height = 46 }: { points: EquityPoint[]; height?: number }) {
  const prefs = useStore().data.settings.charts;
  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={points.slice(-20)} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs><linearGradient id="spark" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--accent)" stopOpacity={.3} /><stop offset="100%" stopColor="var(--accent)" stopOpacity={0} /></linearGradient></defs>
          <Area type="monotone" dataKey="balance" stroke="var(--accent)" strokeWidth={1.8} fill="url(#spark)" dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export { equityCurve };
