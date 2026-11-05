/* ==========================================================================
   Motor de cálculo — todas as métricas derivam exclusivamente dos registros.
   Nenhum valor é "inventado": quando não há dados, os indicadores são zerados.
   ========================================================================== */
import type {
  AppData, Operation, TradeResult, Settings, Strategy, ManagementMode,
} from '../types';
import { calcProfit, round2, todayISO } from './defaults';
import { addDays, weekKey, monthKey } from './format';

export const sortOps = (ops: Operation[]): Operation[] =>
  [...ops].sort((a, b) =>
    (a.date + a.time + String(a.createdAt).padStart(16, '0')).localeCompare(
      b.date + b.time + String(b.createdAt).padStart(16, '0')));

export interface Stats {
  count: number;
  wins: number;
  losses: number;
  draws: number;
  winRate: number;              // % sobre WIN+LOSS (DRAW não conta)
  winRateAll: number;           // % sobre todas
  net: number;
  grossProfit: number;
  grossLoss: number;
  totalEntry: number;
  avgEntry: number;
  avgPayout: number;
  avgWin: number;
  avgLoss: number;
  maxWinStreak: number;
  maxLossStreak: number;
  currentStreak: { result: TradeResult; length: number };
  profitFactor: number;
  expectancy: number;
  bestTrade: number;
  worstTrade: number;
  sequence: TradeResult[];
}

export function stats(ops: Operation[]): Stats {
  const ordered = sortOps(ops);
  const wins = ordered.filter((o) => o.result === 'WIN');
  const losses = ordered.filter((o) => o.result === 'LOSS');
  const draws = ordered.filter((o) => o.result === 'DRAW');
  const grossProfit = sum(wins.map((o) => o.profit));
  const grossLoss = Math.abs(sum(losses.map((o) => o.profit)));
  const net = sum(ordered.map((o) => o.profit));
  const totalEntry = sum(ordered.map((o) => o.entry));
  const decided = wins.length + losses.length;

  let maxWinStreak = 0, maxLossStreak = 0, cw = 0, cl = 0;
  let current: Stats['currentStreak'] = { result: 'DRAW', length: 0 };
  for (const o of ordered) {
    if (o.result === 'WIN') { cw++; cl = 0; maxWinStreak = Math.max(maxWinStreak, cw); }
    else if (o.result === 'LOSS') { cl++; cw = 0; maxLossStreak = Math.max(maxLossStreak, cl); }
    else { cw = 0; cl = 0; }
    current = { result: o.result, length: o.result === 'WIN' ? cw : o.result === 'LOSS' ? cl : 1 };
  }
  if (ordered.length === 0) current = { result: 'DRAW', length: 0 };

  return {
    count: ordered.length,
    wins: wins.length,
    losses: losses.length,
    draws: draws.length,
    winRate: decided ? (wins.length / decided) * 100 : 0,
    winRateAll: ordered.length ? (wins.length / ordered.length) * 100 : 0,
    net: round2(net),
    grossProfit: round2(grossProfit),
    grossLoss: round2(grossLoss),
    totalEntry: round2(totalEntry),
    avgEntry: ordered.length ? round2(totalEntry / ordered.length) : 0,
    avgPayout: ordered.length ? round2(sum(ordered.map((o) => o.payout)) / ordered.length) : 0,
    avgWin: wins.length ? round2(grossProfit / wins.length) : 0,
    avgLoss: losses.length ? round2(grossLoss / losses.length) : 0,
    maxWinStreak,
    maxLossStreak,
    currentStreak: current,
    profitFactor: grossLoss ? round2(grossProfit / grossLoss) : grossProfit ? Infinity : 0,
    expectancy: decided ? round2(net / decided) : 0,
    bestTrade: ordered.length ? Math.max(...ordered.map((o) => o.profit)) : 0,
    worstTrade: ordered.length ? Math.min(...ordered.map((o) => o.profit)) : 0,
    sequence: ordered.map((o) => o.result),
  };
}

export const sum = (arr: number[]) => arr.reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
export const netOf = (ops: Operation[]) => round2(sum(ops.map((o) => o.profit)));

/** Converte uma meta/limite em valor absoluto. */
export function resolveValue(v: { mode: 'currency' | 'percent'; value: number }, base: number): number {
  return v.mode === 'percent' ? (base * (v.value || 0)) / 100 : (v.value || 0);
}

/** Saldo em uma data (inclusive): banca inicial + movimentações + resultados. */
export function balanceAt(data: AppData, date?: string, ops: Operation[] = data.operations): number {
  const upto = (d: string) => !date || d <= date;
  const base = Number(data.settings.initialBalance) || 0;
  const ledger = sum(data.ledger.filter((l) => upto(l.date)).map((l) => l.amount));
  const pnl = sum(sortOps(ops).filter((o) => upto(o.date)).map((o) => o.profit));
  return round2(base + ledger + pnl);
}

export function currentBalance(data: AppData, ops: Operation[] = data.operations): number {
  return balanceAt(data, undefined, ops);
}

export function dayGroups(ops: Operation[]): Map<string, Operation[]> {
  const map = new Map<string, Operation[]>();
  for (const o of sortOps(ops)) {
    if (!map.has(o.date)) map.set(o.date, []);
    map.get(o.date)!.push(o);
  }
  return map;
}

export interface DayInfo {
  date: string;
  ops: Operation[];
  net: number;
  s: Stats;
  balance: number;
  goal: number;
  goalHit: boolean;
  stopLoss: number;
  stopGain: number;
  stopLossHit: boolean;
  stopGainHit: boolean;
}

export function dayInfos(data: AppData, ops: Operation[]): DayInfo[] {
  const orderedDates = [...dayGroups(ops).keys()].sort();
  return orderedDates.map((date) => {
    const dayOps = dayGroups(ops).get(date)!;
    const opening = balanceAt(data, addDays(date, -1), ops);
    const goal = resolveValue(data.settings.dailyGoal, opening);
    const stopLoss = resolveValue(data.settings.stopLoss, opening);
    const stopGain = resolveValue(data.settings.stopGain, opening);
    const net = netOf(dayOps);
    return {
      date, ops: dayOps, net, s: stats(dayOps),
      balance: round2(opening + net),
      goal, goalHit: goal > 0 && net >= goal,
      stopLoss, stopGain,
      stopLossHit: stopLoss > 0 && net <= -stopLoss,
      stopGainHit: stopGain > 0 && net >= stopGain,
    };
  });
}

export function bestWorstDay(data: AppData, ops: Operation[]) {
  const infos = dayInfos(data, ops);
  if (!infos.length) return { best: null as DayInfo | null, worst: null as DayInfo | null };
  let best = infos[0], worst = infos[0];
  for (const d of infos) {
    if (d.net > best.net) best = d;
    if (d.net < worst.net) worst = d;
  }
  return { best, worst };
}

export interface DashboardMetrics {
  initialBalance: number;
  balance: number;
  dayNet: number;
  dayOps: number;
  totalNet: number;
  profitability: number;
  s: Stats;
  maxWinStreak: number;
  maxLossStreak: number;
  bestDay: DayInfo | null;
  worstDay: DayInfo | null;
  goalValue: number;
  goalProgress: number;
  stopLossValue: number;
  remainingLoss: number;
  stopGainValue: number;
  exposureToday: number;
  opsToday: number;
  consecutiveLoss: number;
  consecutiveWin: number;
  dayBalanceStart: number;
}

export function dashboardMetrics(data: AppData, ops: Operation[], refDate = todayISO()): DashboardMetrics {
  const todayOps = sortOps(ops.filter((o) => o.date === refDate));
  const dayBalanceStart = balanceAt(data, addDays(refDate, -1), ops);
  const s = stats(ops);
  const dayS = stats(todayOps);
  const { best, worst } = bestWorstDay(data, ops);
  const balance = currentBalance(data, ops);
  const goalValue = resolveValue(data.settings.dailyGoal, dayBalanceStart);
  const stopLossValue = resolveValue(data.settings.stopLoss, dayBalanceStart);
  const stopGainValue = resolveValue(data.settings.stopGain, dayBalanceStart);
  const consecutive = (result: TradeResult) => {
    let n = 0;
    for (let i = todayOps.length - 1; i >= 0; i--) {
      if (todayOps[i].result === result) n++; else break;
    }
    return n;
  };
  return {
    initialBalance: Number(data.settings.initialBalance) || 0,
    balance,
    dayNet: dayS.net,
    dayOps: dayS.count,
    totalNet: s.net,
    profitability: dayBalanceStart ? ((balance - dayBalanceStart) / dayBalanceStart) * 100 : 0,
    s,
    maxWinStreak: s.maxWinStreak,
    maxLossStreak: s.maxLossStreak,
    bestDay: best,
    worstDay: worst,
    goalValue,
    goalProgress: goalValue > 0 ? Math.max(0, Math.min(100, (dayS.net / goalValue) * 100)) : 0,
    stopLossValue,
    remainingLoss: Math.max(0, stopLossValue + dayS.net),
    stopGainValue,
    exposureToday: round2(sum(todayOps.map((o) => o.entry))),
    opsToday: todayOps.length,
    consecutiveLoss: consecutive('LOSS'),
    consecutiveWin: consecutive('WIN'),
    dayBalanceStart,
  };
}

/** Rentabilidade acumulada sobre a banca inicial + aportes. */
export function totalProfitability(data: AppData, ops: Operation[]): number {
  const invested = (Number(data.settings.initialBalance) || 0) + sum(data.ledger.filter((l) => l.type === 'deposit').map((l) => l.amount));
  return invested ? (netOf(ops) / invested) * 100 : 0;
}

/* --------------------------------- Séries --------------------------------- */

export interface EquityPoint {
  label: string;
  date: string;
  balance: number;
  net: number;
  cumulative: number;
  winRate: number;
  ops: number;
}

export function equityCurve(data: AppData, ops: Operation[]): EquityPoint[] {
  const groups = dayGroups(ops);
  const dates = [...groups.keys()].sort();
  let cumulative = 0;
  const all = sortOps(ops);
  let idx = 0;
  const running: Operation[] = [];
  return dates.map((date) => {
    const dayOps = groups.get(date)!;
    while (idx < all.length && all[idx].date <= date) { running.push(all[idx]); idx++; }
    cumulative += netOf(dayOps);
    return {
      label: date,
      date,
      balance: balanceAt(data, date, ops),
      net: netOf(dayOps),
      cumulative: round2(cumulative),
      winRate: round2(stats(running).winRate),
      ops: dayOps.length,
    };
  });
}

export interface GroupStat {
  key: string;
  label: string;
  count: number;
  wins: number;
  losses: number;
  draws: number;
  net: number;
  winRate: number;
  avgEntry: number;
  avgPayout: number;
}

export function groupStats(ops: Operation[], keyFn: (o: Operation) => string, labelFn?: (k: string) => string): GroupStat[] {
  const map = new Map<string, Operation[]>();
  for (const o of ops) {
    const k = keyFn(o) || '—';
    if (!map.has(k)) map.set(k, []);
    map.get(k)!.push(o);
  }
  return [...map.entries()].map(([k, list]) => {
    const s = stats(list);
    return {
      key: k, label: labelFn ? labelFn(k) : k, count: s.count, wins: s.wins,
      losses: s.losses, draws: s.draws, net: s.net, winRate: s.winRate,
      avgEntry: s.avgEntry, avgPayout: s.avgPayout,
    };
  }).sort((a, b) => b.net - a.net);
}

export const byAsset = (ops: Operation[]) => groupStats(ops, (o) => o.asset || '—');
export const byHour = (ops: Operation[]) => groupStats(ops, (o) => o.time.slice(0, 2), (k) => `${k}h`);
export const byTimeframe = (ops: Operation[]) => groupStats(ops, (o) => o.timeframe || '—');
export const byPayout = (ops: Operation[]) => groupStats(ops, (o) => `${Math.round(o.payout)}%`);
export const byMarket = (ops: Operation[]) => groupStats(ops, (o) => o.market);
export const byDirection = (ops: Operation[]) => groupStats(ops, (o) => o.direction);
export const byWeek = (ops: Operation[]) => groupStats(ops, (o) => weekKey(o.date), (k) => k);
export const byMonth = (ops: Operation[]) => groupStats(ops, (o) => monthKey(o.date), (k) => k);

export function byStrategy(ops: Operation[], strategies: Strategy[]): GroupStat[] {
  const name = (id: string) => strategies.find((s) => s.id === id)?.name || 'Sem estratégia';
  return groupStats(ops, (o) => o.strategyId || 'none', (k) => (k === 'none' ? 'Sem estratégia' : name(k)));
}

/* ------------------------- Gerenciamento de entradas ------------------------- */

export interface LimitCheck {
  ok: boolean;
  warnings: { code: string; label: string; level: 'warn' | 'block' }[];
}

export interface EntrySuggestion {
  value: number;
  rawValue: number;
  mode: ManagementMode;
  explanation: string;
  cycleLength: number;
  limits: LimitCheck;
}

/** Sequência lógica de resultados consecutivos desde o último reset do ciclo. */
function currentCycle(ops: Operation[], mode: ManagementMode): Operation[] {
  const ordered = sortOps(ops);
  const result: Operation[] = [];
  for (let i = ordered.length - 1; i >= 0; i--) {
    const o = ordered[i];
    const isSoros = mode.startsWith('soros');
    const isMartingale = mode === 'martingale';
    const resets = (isSoros || mode === 'custom') ? o.result === 'LOSS' : isMartingale ? (o.result === 'WIN' || o.result === 'DRAW') : false;
    if (resets) break;
    result.unshift(o);
  }
  return result;
}

export function suggestEntry(data: AppData, ops: Operation[], refDate = todayISO()): EntrySuggestion {
  const s = data.settings;
  const m = s.management[s.activeManagement] || s.management.fixed;
  const mode = s.activeManagement;
  const balance = balanceAt(data, addDays(refDate, -1), ops);
  let raw = Number(s.baseEntry) || 0;
  let explanation = '';

  const ordered = sortOps(ops);
  const last = ordered[ordered.length - 1];
  const cycle = currentCycle(ordered, mode);
  const cycleLength = cycle.length;

  switch (mode) {
    case 'fixed':
      raw = Number(m.fixedValue) || s.baseEntry;
      explanation = `Valor fixo definido nas configurações de gerenciamento.`;
      break;
    case 'percent':
      raw = (balance * (Number(m.percentValue) || 0)) / 100;
      explanation = `${m.percentValue}% do saldo de abertura do dia.`;
      break;
    case 'sorosN1':
    case 'sorosN2':
    case 'sorosCustom': {
      const levels = mode === 'sorosN1' ? 1 : mode === 'sorosN2' ? 2 : Math.max(1, Number(m.sorosLevels) || 1);
      if (!last || last.result === 'LOSS' || last.result === 'DRAW') {
        raw = s.baseEntry;
        explanation = 'Ciclo reiniciado: após LOSS/DRAW volta-se ao valor base.';
      } else if (cycleLength >= levels) {
        raw = s.baseEntry;
        explanation = `Ciclo Soros de ${levels} nível(is) concluído — retorno ao valor base.`;
      } else {
        // Soma o lucro das vitórias do ciclo ao valor base
        const profit = sum(cycle.map((o) => o.profit)) * (Number(m.sorosUsePercent) || 100) / 100;
        raw = (Number(s.baseEntry) || 0) + Math.max(0, profit);
        explanation = `Soros nível ${cycleLength + 1}: valor base + ${(Number(m.sorosUsePercent) || 100)}% do lucro acumulado no ciclo.`;
      }
      break;
    }
    case 'martingale': {
      const losses = cycle.filter((o) => o.result === 'LOSS').length;
      const maxLevels = Math.max(1, Number(m.martingaleMaxLevels) || 1);
      if (losses === 0) {
        raw = s.baseEntry;
        explanation = 'Sem LOSS consecutivos: valor base.';
      } else if (losses >= maxLevels) {
        raw = s.baseEntry;
        explanation = `Limite de ${maxLevels} níveis de Martingale atingido — ciclo reiniciado.`;
      } else {
        raw = (Number(s.baseEntry) || 0) * Math.pow(Number(m.martingaleMultiplier) || 2, losses);
        explanation = `Martingale nível ${losses + 1}: base × ${m.martingaleMultiplier}^${losses}.`;
      }
      break;
    }
    case 'custom': {
      const parts = m.customSteps.split(/[,;\s]+/).map((p) => Number(p.replace(',', '.'))).filter((n) => Number.isFinite(n) && n > 0);
      const steps = parts.length ? parts : [1];
      const step = steps[Math.min(cycleLength, steps.length - 1)];
      raw = m.customStepsAreValues ? step : (Number(s.baseEntry) || 0) * step;
      explanation = `Sequência personalizada, passo ${Math.min(cycleLength + 1, steps.length)} de ${steps.length}: ${m.customStepsAreValues ? 'valor absoluto' : `multiplicador ${step}×`}.`;
      break;
    }
  }

  const capped = Math.max(0, Math.min(raw, s.maxEntry > 0 ? s.maxEntry : Infinity));
  const minApplied = capped > 0 && capped < s.minEntry ? s.minEntry : capped;
  const riskCap = (balance * (Number(s.riskPercent) || 100)) / 100;
  let value = round2(Math.min(minApplied, riskCap > 0 ? riskCap : Infinity));
  if (s.maxEntry > 0) value = Math.min(value, s.maxEntry);
  value = round2(Math.max(0, value));

  const warnings: LimitCheck['warnings'] = [];
  const todayOps = ops.filter((o) => o.date === refDate);
  const todayNet = netOf(todayOps);
  const dayOpen = balanceAt(data, addDays(refDate, -1), ops);
  const stopLoss = resolveValue(s.stopLoss, dayOpen);
  const stopGain = resolveValue(s.stopGain, dayOpen);
  const exposure = sum(todayOps.map((o) => o.entry)) + value;
  const exposureCap = (dayOpen * (Number(s.maxExposurePercent) || 100)) / 100;

  if (raw > s.maxEntry && s.maxEntry > 0) warnings.push({ code: 'maxEntry', label: `Valor calculado limitado ao teto por operação (${s.maxEntry}).`, level: 'warn' });
  if (raw > riskCap && riskCap > 0) warnings.push({ code: 'risk', label: `Valor ajustado ao risco máximo de ${s.riskPercent}% da banca.`, level: 'warn' });
  if (s.maxOpsPerDay > 0 && todayOps.length >= s.maxOpsPerDay) warnings.push({ code: 'maxOps', label: `Limite de ${s.maxOpsPerDay} operações/dia atingido.`, level: 'block' });
  if (stopLoss > 0 && todayNet <= -stopLoss) warnings.push({ code: 'stopLoss', label: 'Stop Loss diário atingido.', level: 'block' });
  if (stopGain > 0 && todayNet >= stopGain) warnings.push({ code: 'stopGain', label: 'Stop Gain diário atingido.', level: 'block' });
  if (s.maxConsecutiveLoss > 0 && currentStreakOf(todayOps, 'LOSS') >= s.maxConsecutiveLoss) warnings.push({ code: 'lossStreak', label: `Limite de ${s.maxConsecutiveLoss} LOSS consecutivos atingido.`, level: 'block' });
  if (s.maxConsecutiveWin > 0 && currentStreakOf(todayOps, 'WIN') >= s.maxConsecutiveWin) warnings.push({ code: 'winStreak', label: `Limite de ${s.maxConsecutiveWin} WIN consecutivos atingido.`, level: 'block' });
  if (exposureCap > 0 && exposure > exposureCap) warnings.push({ code: 'exposure', label: `Exposição máxima de ${s.maxExposurePercent}% da banca seria excedida.`, level: 'warn' });
  if (value > balance) warnings.push({ code: 'balance', label: 'Valor sugerido superior ao saldo disponível.', level: 'block' });

  return {
    value, rawValue: round2(raw), mode, explanation, cycleLength,
    limits: { ok: !warnings.some((w) => w.level === 'block'), warnings },
  };
}

function currentStreakOf(ops: Operation[], r: TradeResult) {
  const ordered = sortOps(ops);
  let n = 0;
  for (let i = ordered.length - 1; i >= 0; i--) {
    if (ordered[i].result === r) n++; else break;
  }
  return n;
}

/** Valida uma entrada que está sendo registrada (usada no formulário). */
export function validateEntry(data: AppData, ops: Operation[], entry: number, date: string): LimitCheck {
  const s = data.settings;
  const warnings: LimitCheck['warnings'] = [];
  const dayOpen = balanceAt(data, addDays(date, -1), ops);
  const todayOps = ops.filter((o) => o.date === date);
  const todayNet = netOf(todayOps);
  const stopLoss = resolveValue(s.stopLoss, dayOpen);
  const stopGain = resolveValue(s.stopGain, dayOpen);
  const exposure = sum(todayOps.map((o) => o.entry)) + entry;
  const exposureCap = (dayOpen * (Number(s.maxExposurePercent) || 100)) / 100;
  const riskCap = (dayOpen * (Number(s.riskPercent) || 100)) / 100;

  if (s.minEntry > 0 && entry < s.minEntry) warnings.push({ code: 'min', label: `Abaixo do mínimo por operação (${s.minEntry}).`, level: 'warn' });
  if (s.maxEntry > 0 && entry > s.maxEntry) warnings.push({ code: 'max', label: `Acima do máximo por operação (${s.maxEntry}).`, level: 'warn' });
  if (riskCap > 0 && entry > riskCap) warnings.push({ code: 'risk', label: `Acima do risco de ${s.riskPercent}% por operação.`, level: 'warn' });
  if (exposureCap > 0 && exposure > exposureCap) warnings.push({ code: 'exposure', label: `Exposição máxima da banca (${s.maxExposurePercent}%) excedida.`, level: 'warn' });
  if (s.maxOpsPerDay > 0 && todayOps.length >= s.maxOpsPerDay) warnings.push({ code: 'ops', label: `Limite de ${s.maxOpsPerDay} operações por dia excedido.`, level: 'warn' });
  if (stopLoss > 0 && todayNet <= -stopLoss) warnings.push({ code: 'stopLoss', label: 'Stop Loss diário já atingido.', level: 'warn' });
  if (stopGain > 0 && todayNet >= stopGain) warnings.push({ code: 'stopGain', label: 'Stop Gain diário já atingido.', level: 'warn' });
  if (s.maxConsecutiveLoss > 0 && currentStreakOf(todayOps, 'LOSS') >= s.maxConsecutiveLoss) warnings.push({ code: 'lossStreak', label: `Limite de ${s.maxConsecutiveLoss} LOSS consecutivos atingido.`, level: 'warn' });
  if (entry > balanceAt(data, addDays(date, -1), ops)) warnings.push({ code: 'balance', label: 'Entrada maior que o saldo disponível.', level: 'warn' });

  return { ok: warnings.length === 0, warnings };
}

/* ------------------------------- Metas / planos ------------------------------ */

export interface GoalProgress {
  id: string;
  label: string;
  current: number;
  target: number;
  unit: 'money' | 'ops' | 'percent';
  progress: number;
  detail: string;
}

export function goalProgress(data: AppData, ops: Operation[], refDate = todayISO()): GoalProgress[] {
  const g = data.goals;
  const balance = currentBalance(data, ops);
  const infos = dayInfos(data, ops);
  const today = infos.find((d) => d.date === refDate);
  const week = weekKey(refDate);
  const month = monthKey(refDate);
  const weekNet = netOf(ops.filter((o) => weekKey(o.date) === week));
  const monthNet = netOf(ops.filter((o) => monthKey(o.date) === month));
  const dayOpen = balanceAt(data, addDays(refDate, -1), ops);
  const weekOpen = balanceAt(data, addDays(week, -1), ops);
  const monthOpen = balanceAt(data, `${month}-00`, ops);
  const base = Number(data.settings.initialBalance) || 0;
  const mk = (id: string, label: string, current: number, target: number, unit: GoalProgress['unit'], detail: string): GoalProgress => ({
    id, label, current: round2(current), target: round2(target), unit,
    progress: target > 0 ? Math.max(0, Math.min(100, (current / target) * 100)) : 0, detail,
  });
  return [
    mk('daily', 'Meta diária', today?.net || 0, resolveValue(g.daily, dayOpen), 'money', formatPeriod(refDate)),
    mk('weekly', 'Meta semanal', weekNet, resolveValue(g.weekly, weekOpen), 'money', `Semana iniciada em ${week}`),
    mk('monthly', 'Meta mensal', monthNet, resolveValue(g.monthly, monthOpen || base), 'money', `Mês ${month}`),
    mk('growth', 'Crescimento da banca', balance - base, resolveValue(g.growth, base), 'money', `Banca inicial ${base}`),
    mk('financial', 'Objetivo financeiro', balance, g.financialTarget, 'money', 'Saldo atual × objetivo'),
    mk('lossLimit', 'Limite de perda (consumo)', Math.max(0, -netOf(ops.filter((o) => o.date === refDate))), resolveValue(g.lossLimit, dayOpen), 'money', 'Perda do dia × limite'),
    mk('desiredOps', 'Operações desejadas / dia', today?.s.count || 0, g.desiredOps, 'ops', 'Operações registradas hoje'),
  ];
}

const formatPeriod = (d: string) => `Dia ${d}`;

export function projectPlan(plan: { initial: number; dailyRate: number; days: number; compound: boolean }) {
  const points: { day: number; value: number; linear: number }[] = [];
  for (let d = 0; d <= plan.days; d++) {
    const value = plan.compound
      ? plan.initial * Math.pow(1 + plan.dailyRate / 100, d)
      : plan.initial + (plan.initial * (plan.dailyRate / 100)) * d;
    points.push({
      day: d,
      value: round2(value),
      linear: round2(plan.initial + (plan.initial * (plan.dailyRate / 100)) * d),
    });
  }
  return points;
}

/** Cenários derivados do histórico real, em % ao dia sobre a banca inicial. */
export function historicScenarios(data: AppData, ops: Operation[]): {
  conservative: number; realistic: number; aggressive: number; hasData: boolean; expectancy: number;
} {
  const s = stats(ops);
  const base = Math.max(1, Number(data.settings.initialBalance) || 1000);
  const p = s.winRate / 100;
  const expectancy = round2(p * s.avgWin - (1 - p) * s.avgLoss);
  const realistic = round2((expectancy / base) * 100);
  return {
    conservative: round2(realistic * 0.5),
    realistic,
    aggressive: round2(realistic * 1.5),
    expectancy,
    hasData: s.count > 0,
  };
}

/* ------------------------------ Micro séries ------------------------------- */

export interface SeriesBlock {
  id: string;
  label: string;
  ops: Operation[];
  s: Stats;
  totalEntry: number;
  totalReturn: number;
  endCapital: number;
  profitPct: number;
  capitalPct: number;
  startCapital: number;
}

export function seriesBlocks(data: AppData, ops: Operation[]): SeriesBlock[] {
  const ordered = sortOps(ops);
  const groups = new Map<string, Operation[]>();
  for (const o of ordered) {
    const key = o.seriesId || `auto-${o.date}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(o);
  }
  return [...groups.entries()].map(([id, list], i) => {
    const s = stats(list);
    const totalEntry = s.totalEntry;
    const totalReturn = s.net;
    const startCapital = balanceAt(data, addDays(list[0].date, -1), ops);
    const endCapital = round2(startCapital + totalReturn);
    return {
      id, label: id.startsWith('auto-') ? `Série ${i + 1}` : `Série ${i + 1}`,
      ops: list, s, totalEntry: round2(totalEntry), totalReturn: round2(totalReturn),
      endCapital, startCapital,
      profitPct: totalEntry ? (totalReturn / totalEntry) * 100 : 0,
      capitalPct: startCapital ? (totalReturn / startCapital) * 100 : 0,
    };
  });
}

export function recalcProfit(o: Operation): Operation {
  return { ...o, profit: calcProfit(o.entry, o.payout, o.result), profitEdited: false };
}

export function inRange(o: Operation, from: string, to: string) {
  return (!from || o.date >= from) && (!to || o.date <= to);
}

export type { Settings };
