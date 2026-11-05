/* ==========================================================================
   Trading Control Center — Modelo de dados
   Todos os tipos são serializáveis em JSON (backup / localStorage).
   ========================================================================== */

export type TradeResult = 'WIN' | 'LOSS' | 'DRAW';
export type MarketType = 'Normal' | 'OTC';
export type Direction = 'CALL' | 'PUT';
export type ThemeMode = 'dark' | 'light';

export interface Operation {
  id: string;
  date: string;          // YYYY-MM-DD
  time: string;          // HH:mm
  asset: string;
  market: MarketType;
  direction: Direction;
  strategyId: string;    // '' = sem estratégia
  timeframe: string;     // ex.: M1, M5, M15
  expiry: string;        // ex.: 1m, 5m
  entry: number;         // valor investido
  payout: number;        // % (ex.: 85 => 85% de lucro líquido sobre a entrada)
  result: TradeResult;
  /** Lucro/prejuízo calculado automaticamente. Pode ser corrigido manualmente. */
  profit: number;
  /** true quando o usuário editou o valor financeiro manualmente */
  profitEdited?: boolean;
  notes: string;
  screenshot?: string;   // data URL (imagem comprimida)
  seriesId?: string;     // agrupamento em "micro séries" (visão planilha)
  /** Dados de demonstração / simulação — nunca misturados com dados reais */
  demo?: boolean;
  createdAt: number;
  updatedAt?: number;
}

export interface LedgerEntry {
  id: string;
  date: string;
  type: 'deposit' | 'withdraw' | 'adjust';
  amount: number;        // positivo = entra, negativo = sai / ajuste negativo
  note: string;
  createdAt: number;
}

export interface Strategy {
  id: string;
  name: string;
  description: string;
  config: string;           // configuração / regras da estratégia (texto livre)
  assets: string;           // ativos recomendados separados por vírgula
  timeframe: string;
  expiry: string;
  active: boolean;
  color: string;
  createdAt: number;
}

export type ManagementMode =
  | 'fixed'
  | 'percent'
  | 'sorosN1'
  | 'sorosN2'
  | 'sorosCustom'
  | 'martingale'
  | 'custom';

export interface ManagementConfig {
  fixedValue: number;
  percentValue: number;             // % da banca
  sorosLevels: number;              // níveis antes de resetar
  sorosResetOnLoss: boolean;
  sorosUsePercent: number;          // % do lucro reinvestido
  martingaleMultiplier: number;
  martingaleMaxLevels: number;
  martingaleResetOnWin: boolean;
  customSteps: string;              // sequência: "1,2,4,8" (multiplicadores) ou "10|20|30"
  customStepsAreValues: boolean;
  cycleStartBalance?: number;
}

export interface ModeValue {
  mode: 'currency' | 'percent';
  value: number;
}

export interface GrowthPlan {
  id: string;
  name: string;
  initial: number;
  target: number;
  dailyRate: number;       // % ao dia
  days: number;
  compound: boolean;
  createdAt: number;
}

export interface GoalSettings {
  daily: ModeValue;
  weekly: ModeValue;
  monthly: ModeValue;
  growth: ModeValue;         // meta de crescimento da banca (% ou valor)
  financialTarget: number;   // objetivo financeiro em R$
  lossLimit: ModeValue;
  desiredOps: number;
}

export interface DashboardCardDef {
  id: string;
  visible: boolean;
  span: 1 | 2 | 3 | 4;      // largura em colunas (grid de 4)
}

export interface Settings {
  platformName: string;
  platformSubtitle: string;
  theme: ThemeMode;
  accent: string;
  positive: string;
  negative: string;
  currency: string;          // BRL, USD, EUR...
  currencySymbol: string;
  locale: string;            // pt-BR, en-US...
  dateFormat: string;        // dd/MM/yyyy, MM/dd/yyyy, yyyy-MM-dd
  compactNumbers: boolean;

  initialBalance: number;
  baseEntry: number;
  minEntry: number;
  maxEntry: number;
  riskPercent: number;
  dailyGoal: ModeValue;
  stopLoss: ModeValue;
  stopGain: ModeValue;
  maxOpsPerDay: number;
  maxConsecutiveLoss: number;
  maxConsecutiveWin: number;
  maxExposurePercent: number;
  profitReservePercent: number;
  requireLimitConfirmation: boolean;

  activeManagement: ManagementMode;
  /** Configurações independentes para cada modalidade de gerenciamento */
  management: Record<ManagementMode, ManagementConfig>;

  dashboardCards: DashboardCardDef[];
  showDemoBanner: boolean;
  /** Colunas visíveis na tabela de operações */
  visibleColumns: string[];
  /** Campos opcionais exibidos no formulário de operação */
  opFields: Record<string, boolean>;
  /** Preferências de gráficos e filtros */
  charts: { grid: boolean; animations: boolean; defaultRangeDays: number };
}

export interface AppData {
  version: number;
  settings: Settings;
  operations: Operation[];
  strategies: Strategy[];
  ledger: LedgerEntry[];
  goals: GoalSettings;
  plans: GrowthPlan[];
  /** último dia "fechado" com observação do usuário (notas diárias) */
  dayNotes: Record<string, string>;
}

export interface PageDef {
  id: string;
  label: string;
  group: string;
  icon: string;
}
