/* ==========================================================================
   Ferramentas para excluir / corrigir / mover o histórico de um dia inteiro
   - Resolve o problema clássico de uma importação feita na data errada
   - Sempre gera um snapshot para desfazer a última ação
   - Nunca inventa registros: apenas move, apaga ou recria com data explícita
   ========================================================================== */
import type { AppData, Operation } from '../types';
import { uid } from './defaults';

export interface OpFilter {
  /** Somente operações importadas de planilha */
  onlyImported?: boolean;
  /** Incluir registros marcados como simulação */
  includeDemo?: boolean;
}

export interface ImportBatch {
  /** Data em que as operações foram parar no painel */
  date: string;
  count: number;
  imported: number;
  manual: number;
  demo: number;
  net: number;
  /** createdAts distintos — usado para separar importações diferentes no mesmo dia */
  stamps: number[];
}

/** Operações de uma data, respeitando os filtros de origem. */
export function opsOnDate(data: AppData, date: string, filter: OpFilter = {}): Operation[] {
  return data.operations.filter((o) => {
    if (o.date !== date) return false;
    if (filter.onlyImported && o.source !== 'import') return false;
    if (filter.includeDemo === false && o.demo) return false;
    return true;
  });
}

/** Datas que possuem operações, em ordem decrescente. */
export function datesWithOps(data: AppData): string[] {
  return [...new Set(data.operations.map((o) => o.date))].sort().reverse();
}

/**
 * Agrupa as operações por data e por "lote" de criação, para que o usuário
 * identifique exatamente a importação que precisa remover.
 */
export function importBatches(data: AppData): ImportBatch[] {
  const byDate = new Map<string, Operation[]>();
  for (const o of data.operations) {
    const list = byDate.get(o.date) || [];
    list.push(o);
    byDate.set(o.date, list);
  }
  return [...byDate.entries()]
    .map(([date, ops]) => {
      // Um lote = operações criadas com menos de 5 segundos de diferença
      const sorted = [...ops].sort((a, b) => a.createdAt - b.createdAt);
      const stamps: number[] = [];
      for (const o of sorted) {
        if (!stamps.length || o.createdAt - stamps[stamps.length - 1] > 5000) stamps.push(o.createdAt);
      }
      return {
        date,
        count: ops.length,
        imported: ops.filter((o) => o.source === 'import').length,
        manual: ops.filter((o) => !o.source || o.source === 'manual').length,
        demo: ops.filter((o) => o.demo).length,
        net: ops.reduce((a, o) => a + o.profit, 0),
        stamps,
      };
    })
    .sort((a, b) => b.date.localeCompare(a.date));
}

export interface DayAction {
  data: AppData;
  removed: number;
  /** Snapshot completo do estado anterior — permite desfazer */
  snapshot: AppData;
  message: string;
}

function snapshotOf(data: AppData): AppData {
  return JSON.parse(JSON.stringify(data)) as AppData;
}

/** Remove as operações de um dia (ou apenas as importadas). */
export function deleteDay(data: AppData, date: string, filter: OpFilter = {}): DayAction {
  const targets = new Set(opsOnDate(data, date, filter).map((o) => o.id));
  if (!targets.size) {
    return { data, removed: 0, snapshot: snapshotOf(data), message: 'Nenhuma operação encontrada com esses critérios.' };
  }
  return {
    data: { ...data, operations: data.operations.filter((o) => !targets.has(o.id)) },
    removed: targets.size,
    snapshot: snapshotOf(data),
    message: `${targets.size} operação(ões) removida(s) de ${date}.`,
  };
}

/**
 * Move as operações de um dia para outra data (corrige o "dia errado").
 * Preserva horário, ativo, entrada, payout, resultado, observações e prints.
 */
export function moveDay(data: AppData, from: string, to: string, filter: OpFilter = {}): DayAction {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(to)) {
    return { data, removed: 0, snapshot: snapshotOf(data), message: 'Data de destino inválida.' };
  }
  if (from === to) {
    return { data, removed: 0, snapshot: snapshotOf(data), message: 'A data de destino é igual à data atual.' };
  }
  const targets = new Set(opsOnDate(data, from, filter).map((o) => o.id));
  if (!targets.size) {
    return { data, removed: 0, snapshot: snapshotOf(data), message: 'Nenhuma operação encontrada nesse dia.' };
  }
  return {
    data: {
      ...data,
      operations: data.operations.map((o) => (targets.has(o.id) ? { ...o, date: to, updatedAt: Date.now() } : o)),
    },
    removed: targets.size,
    snapshot: snapshotOf(data),
    message: `${targets.size} operação(ões) movida(s) de ${from} para ${to}.`,
  };
}

/**
 * Duplica as operações de um dia em outra data, gerando novos IDs.
 * Útil quando o dia correto precisa receber a mesma sequência já lançada.
 */
export function copyDayTo(data: AppData, from: string, to: string, filter: OpFilter = {}): DayAction {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(to)) {
    return { data, removed: 0, snapshot: snapshotOf(data), message: 'Data de destino inválida.' };
  }
  const source = opsOnDate(data, from, filter);
  if (!source.length) {
    return { data, removed: 0, snapshot: snapshotOf(data), message: 'Nenhuma operação encontrada nesse dia.' };
  }
  const now = Date.now();
  const copies: Operation[] = source.map((o, i) => ({
    ...o,
    id: uid(),
    date: to,
    createdAt: now + i,
    updatedAt: undefined,
  }));
  return {
    data: { ...data, operations: [...data.operations, ...copies] },
    removed: copies.length,
    snapshot: snapshotOf(data),
    message: `${copies.length} operação(ões) copiada(s) de ${from} para ${to}.`,
  };
}

/** Lista simples de datas para preencher o seletor de dias. */
export function recentDates(count = 30, today: string): string[] {
  const out: string[] = [];
  const base = new Date(`${today}T12:00:00`);
  for (let i = 0; i < count; i++) {
    const d = new Date(base);
    d.setDate(d.getDate() - i);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`);
  }
  return out;
}
