import type { AppData, DashboardCardDef, Settings, GoalSettings, Operation, ManagementConfig, ManagementMode } from '../types';

export const DATA_VERSION = 1;
export const STORAGE_KEY = 'tcc:data:v1';

export const OP_COLUMNS = [
  { id: 'date', label: 'Data / hora' }, { id: 'asset', label: 'Ativo' },
  { id: 'market', label: 'Mercado' }, { id: 'direction', label: 'Direção' },
  { id: 'strategy', label: 'Estratégia' }, { id: 'timeframe', label: 'Timeframe' },
  { id: 'expiry', label: 'Expiração' }, { id: 'entry', label: 'Entrada' },
  { id: 'payout', label: 'Payout' }, { id: 'result', label: 'Resultado' },
  { id: 'profit', label: 'Lucro / prejuízo' }, { id: 'notes', label: 'Observações' },
  { id: 'screenshot', label: 'Screenshot' }, { id: 'series', label: 'Série' },
  { id: 'actions', label: 'Ações' },
];
export const OP_FIELD_KEYS = ['market', 'direction', 'strategy', 'timeframe', 'expiry', 'notes', 'screenshot', 'series'];

export const DASHBOARD_CARDS: { id: string; label: string; group: string; defaultSpan: 1 | 2 | 3 | 4 }[] = [
  { id: 'balance', label: 'Saldo atual', group: 'Financeiro', defaultSpan: 1 },
  { id: 'initialBalance', label: 'Banca inicial', group: 'Financeiro', defaultSpan: 1 },
  { id: 'dayResult', label: 'Resultado do dia', group: 'Financeiro', defaultSpan: 1 },
  { id: 'totalResult', label: 'Lucro / prejuízo acumulado', group: 'Financeiro', defaultSpan: 1 },
  { id: 'profitability', label: 'Rentabilidade', group: 'Financeiro', defaultSpan: 1 },
  { id: 'totalOps', label: 'Total de operações', group: 'Operacional', defaultSpan: 1 },
  { id: 'wins', label: 'WIN', group: 'Operacional', defaultSpan: 1 },
  { id: 'losses', label: 'LOSS', group: 'Operacional', defaultSpan: 1 },
  { id: 'draws', label: 'DRAW', group: 'Operacional', defaultSpan: 1 },
  { id: 'winRate', label: 'Assertividade', group: 'Operacional', defaultSpan: 1 },
  { id: 'avgPayout', label: 'Payout médio', group: 'Operacional', defaultSpan: 1 },
  { id: 'avgEntry', label: 'Valor médio por operação', group: 'Operacional', defaultSpan: 1 },
  { id: 'maxWinStreak', label: 'Maior sequência de WIN', group: 'Sequências', defaultSpan: 1 },
  { id: 'maxLossStreak', label: 'Maior sequência de LOSS', group: 'Sequências', defaultSpan: 1 },
  { id: 'bestDay', label: 'Melhor dia', group: 'Sequências', defaultSpan: 1 },
  { id: 'worstDay', label: 'Pior dia', group: 'Sequências', defaultSpan: 1 },
  { id: 'dailyGoal', label: 'Meta diária e progresso', group: 'Risco & Metas', defaultSpan: 2 },
  { id: 'stopLoss', label: 'Limite de perda diária', group: 'Risco & Metas', defaultSpan: 2 },
  { id: 'nextEntry', label: 'Próxima entrada sugerida', group: 'Risco & Metas', defaultSpan: 2 },
  { id: 'equity', label: 'Curva de evolução da banca', group: 'Gráficos', defaultSpan: 2 },
  { id: 'dayBars', label: 'Resultado por dia', group: 'Gráficos', defaultSpan: 2 },
  { id: 'resultPie', label: 'Distribuição WIN / LOSS / DRAW', group: 'Gráficos', defaultSpan: 2 },
  { id: 'recent', label: 'Últimas operações', group: 'Gráficos', defaultSpan: 2 },
];

export const MANAGEMENT_MODES: ManagementMode[] = ['fixed', 'percent', 'sorosN1', 'sorosN2', 'sorosCustom', 'martingale', 'custom'];

export const defaultManagement = (): ManagementConfig => ({
  fixedValue: 20,
  percentValue: 2,
  sorosLevels: 2,
  sorosResetOnLoss: true,
  sorosUsePercent: 100,
  martingaleMultiplier: 2,
  martingaleMaxLevels: 3,
  martingaleResetOnWin: true,
  customSteps: '1,1.5,2,3',
  customStepsAreValues: false,
});

/** Cada modalidade tem sua própria configuração, independente das demais. */
export const defaultManagementPresets = (): Record<ManagementMode, ManagementConfig> => {
  const base = defaultManagement();
  return {
    fixed: { ...base, fixedValue: 20 },
    percent: { ...base, percentValue: 2 },
    sorosN1: { ...base, sorosUsePercent: 100 },
    sorosN2: { ...base, sorosUsePercent: 100 },
    sorosCustom: { ...base, sorosLevels: 3, sorosUsePercent: 80 },
    martingale: { ...base, martingaleMultiplier: 2, martingaleMaxLevels: 3 },
    custom: { ...base, customSteps: '1,1.5,2,3' },
  };
};

export const defaultCards = (): DashboardCardDef[] =>
  DASHBOARD_CARDS.map((c) => ({ id: c.id, visible: true, span: c.defaultSpan }));

export const defaultSettings = (): Settings => ({
  platformName: 'Trading Control Center',
  platformSubtitle: 'Gestão de banca & performance',
  theme: 'dark',
  accent: '#21d4a8',
  positive: '#22c55e',
  negative: '#f43f5e',
  currency: 'BRL',
  currencySymbol: 'R$',
  locale: 'pt-BR',
  dateFormat: 'dd/MM/yyyy',
  compactNumbers: false,

  initialBalance: 1000,
  baseEntry: 20,
  minEntry: 2,
  maxEntry: 100,
  riskPercent: 2,
  dailyGoal: { mode: 'percent', value: 5 },
  stopLoss: { mode: 'percent', value: 10 },
  stopGain: { mode: 'percent', value: 15 },
  maxOpsPerDay: 20,
  maxConsecutiveLoss: 3,
  maxConsecutiveWin: 0,
  maxExposurePercent: 20,
  profitReservePercent: 0,
  requireLimitConfirmation: true,

  activeManagement: 'fixed',
  management: defaultManagementPresets(),

  dashboardCards: defaultCards(),
  showDemoBanner: true,
  visibleColumns: OP_COLUMNS.map((c) => c.id),
  opFields: Object.fromEntries(OP_FIELD_KEYS.map((k) => [k, true])),
  charts: { grid: true, animations: true, defaultRangeDays: 30 },
});

export const defaultGoals = (): GoalSettings => ({
  daily: { mode: 'percent', value: 5 },
  weekly: { mode: 'percent', value: 20 },
  monthly: { mode: 'percent', value: 60 },
  growth: { mode: 'percent', value: 100 },
  financialTarget: 10000,
  lossLimit: { mode: 'percent', value: 10 },
  desiredOps: 10,
});

export const defaultData = (): AppData => ({
  version: DATA_VERSION,
  settings: defaultSettings(),
  operations: [],
  strategies: [],
  ledger: [],
  goals: defaultGoals(),
  plans: [],
  dayNotes: {},
});

/** Mescla dados salvos com os padrões, garantindo compatibilidade com versões futuras. */
export function hydrate(raw: unknown): AppData {
  const base = defaultData();
  if (!raw || typeof raw !== 'object') return base;
  const r = raw as Partial<AppData>;
  const settings = { ...base.settings, ...(r.settings || {}) } as Settings;
  const savedMgmt = (r.settings?.management || {}) as Partial<Record<ManagementMode, ManagementConfig>>;
  settings.management = Object.fromEntries(
    MANAGEMENT_MODES.map((mode) => [mode, { ...base.settings.management[mode], ...(savedMgmt[mode] || {}) }]),
  ) as Record<ManagementMode, ManagementConfig>;
  settings.dailyGoal = { ...base.settings.dailyGoal, ...(r.settings?.dailyGoal || {}) };
  settings.stopLoss = { ...base.settings.stopLoss, ...(r.settings?.stopLoss || {}) };
  settings.stopGain = { ...base.settings.stopGain, ...(r.settings?.stopGain || {}) };

  // Garante que cards novos apareçam e que cards removidos não quebrem a UI
  const saved = Array.isArray(settings.dashboardCards) ? settings.dashboardCards : [];
  const known = new Set(DASHBOARD_CARDS.map((c) => c.id));
  const merged: DashboardCardDef[] = saved
    .filter((c) => c && known.has(c.id))
    .map((c) => ({ ...c, span: c.span || 1 }));
  for (const c of DASHBOARD_CARDS) {
    if (!merged.some((m) => m.id === c.id)) merged.push({ id: c.id, visible: true, span: c.defaultSpan });
  }
  settings.dashboardCards = merged;
  settings.visibleColumns = Array.isArray(settings.visibleColumns)
    ? settings.visibleColumns.filter((c) => OP_COLUMNS.some((x) => x.id === c)) : base.settings.visibleColumns;
  settings.opFields = { ...base.settings.opFields, ...(settings.opFields || {}) };
  settings.charts = { ...base.settings.charts, ...(settings.charts || {}) };

  const goals = { ...base.goals, ...(r.goals || {}) } as GoalSettings;
  for (const k of ['daily', 'weekly', 'monthly', 'growth', 'lossLimit'] as const) {
    goals[k] = { ...(base.goals[k] as object), ...((r.goals?.[k] as object) || {}) } as GoalSettings[typeof k];
  }

  return {
    version: DATA_VERSION,
    settings,
    operations: Array.isArray(r.operations) ? r.operations.map(normalizeOperation) : [],
    strategies: Array.isArray(r.strategies) ? r.strategies : [],
    ledger: Array.isArray(r.ledger) ? r.ledger : [],
    goals,
    plans: Array.isArray(r.plans) ? r.plans : [],
    dayNotes: r.dayNotes && typeof r.dayNotes === 'object' ? r.dayNotes : {},
  };
}

function normalizeOperation(o: Partial<Operation>): Operation {
  const entry = Number(o.entry) || 0;
  const payout = Number(o.payout) || 0;
  const result = (o.result === 'WIN' || o.result === 'LOSS' || o.result === 'DRAW') ? o.result : 'DRAW';
  return {
    id: o.id || uid(),
    date: o.date || todayISO(),
    time: o.time || '12:00',
    asset: o.asset || '',
    market: o.market === 'OTC' ? 'OTC' : 'Normal',
    direction: o.direction === 'PUT' ? 'PUT' : 'CALL',
    strategyId: o.strategyId || '',
    timeframe: o.timeframe || 'M1',
    expiry: o.expiry || '1m',
    entry,
    payout,
    result,
    profit: typeof o.profit === 'number' ? o.profit : calcProfit(entry, payout, result),
    profitEdited: !!o.profitEdited,
    notes: o.notes || '',
    screenshot: o.screenshot,
    seriesId: o.seriesId,
    demo: !!o.demo,
    createdAt: o.createdAt || Date.now(),
    updatedAt: o.updatedAt,
  };
}

export function calcProfit(entry: number, payout: number, result: string): number {
  if (result === 'WIN') return round2(entry * (payout / 100));
  if (result === 'LOSS') return round2(-entry);
  return 0;
}

export const round2 = (n: number) => Math.round((n + Number.EPSILON) * 100) / 100;
export const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
export function todayISO(d = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
