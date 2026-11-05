import type { AppData, Operation } from '../types';
import { downloadCsv, formatDate, weekKey, monthKey } from './format';
import { dayInfos, stats } from './calc';

const headers = [
  'ID', 'Data', 'Horário', 'Ativo', 'Mercado', 'Direção', 'Estratégia', 'Timeframe',
  'Expiração', 'Entrada', 'Payout (%)', 'Resultado', 'Lucro/Prejuízo', 'Observações',
  'Série', 'Tipo de dado',
];

function rowOf(o: Operation, d: AppData): (string | number)[] {
  return [
    o.id, formatDate(o.date, d.settings), o.time, o.asset, o.market, o.direction,
    d.strategies.find((s) => s.id === o.strategyId)?.name || 'Sem estratégia',
    o.timeframe, o.expiry, o.entry, o.payout, o.result, o.profit, o.notes,
    o.seriesId || '', o.demo ? 'SIMULAÇÃO' : 'REAL',
  ];
}

export function exportCsv(ops: Operation[], data: AppData, filename = 'operacoes.csv') {
  downloadCsv(filename, [headers, ...ops.map((o) => rowOf(o, data))]);
}

export async function exportExcel(data: AppData, ops: Operation[]) {
  const XLSX = await import('xlsx');
  const wb = XLSX.utils.book_new();
  const s = data.settings;

  const opSheet = XLSX.utils.aoa_to_sheet([
    headers,
    ...ops.map((o) => rowOf(o, data)),
  ]);
  opSheet['!cols'] = headers.map(() => ({ wch: 16 }));
  XLSX.utils.book_append_sheet(wb, opSheet, 'Operações');

  const daily = dayInfos(data, ops);
  const dailySheet = XLSX.utils.aoa_to_sheet([
    ['Data', 'Operações', 'WIN', 'LOSS', 'DRAW', 'Assertividade (%)', 'Resultado', 'Saldo final', 'Investido', 'Payout médio', 'Meta atingida', 'Stop Loss', 'Stop Gain'],
    ...daily.map((d) => [
      formatDate(d.date, s), d.s.count, d.s.wins, d.s.losses, d.s.draws,
      Number(d.s.winRate.toFixed(2)), d.net, d.balance, d.s.totalEntry,
      Number(d.s.avgPayout.toFixed(2)), d.goalHit ? 'Sim' : 'Não',
      d.stopLossHit ? 'Sim' : 'Não', d.stopGainHit ? 'Sim' : 'Não',
    ]),
  ]);
  dailySheet['!cols'] = Array.from({ length: 13 }, () => ({ wch: 17 }));
  XLSX.utils.book_append_sheet(wb, dailySheet, 'Resultados Diários');

  const strat = XLSX.utils.aoa_to_sheet([
    ['Estratégia', 'Ativa', 'Descrição', 'Timeframe', 'Expiração', 'Operações', 'WIN', 'LOSS', 'Assertividade (%)', 'Lucro acumulado'],
    ...data.strategies.map((st) => {
      const list = ops.filter((o) => o.strategyId === st.id);
      const x = stats(list);
      return [st.name, st.active ? 'Sim' : 'Não', st.description, st.timeframe, st.expiry, x.count, x.wins, x.losses, Number(x.winRate.toFixed(2)), x.net];
    }),
  ]);
  XLSX.utils.book_append_sheet(wb, strat, 'Estratégias');

  const ledger = XLSX.utils.aoa_to_sheet([
    ['Data', 'Tipo', 'Valor', 'Observação'],
    ...data.ledger.map((l) => [formatDate(l.date, s), l.type, l.amount, l.note]),
  ]);
  XLSX.utils.book_append_sheet(wb, ledger, 'Movimentações');

  const weeks = new Map<string, Operation[]>();
  const months = new Map<string, Operation[]>();
  for (const o of ops) {
    const w = weekKey(o.date), m = monthKey(o.date);
    if (!weeks.has(w)) weeks.set(w, []);
    if (!months.has(m)) months.set(m, []);
    weeks.get(w)!.push(o); months.get(m)!.push(o);
  }
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
    ['Semana (início)', 'Operações', 'Resultado', 'Assertividade (%)'],
    ...[...weeks.entries()].sort().map(([w, list]) => [w, list.length, stats(list).net, Number(stats(list).winRate.toFixed(2))]),
  ]), 'Semanal');
  XLSX.utils.book_append_sheet(wb, XLSX.utils.aoa_to_sheet([
    ['Mês', 'Operações', 'Resultado', 'Assertividade (%)'],
    ...[...months.entries()].sort().map(([m, list]) => [m, list.length, stats(list).net, Number(stats(list).winRate.toFixed(2))]),
  ]), 'Mensal');

  XLSX.writeFile(wb, `relatorio-trading-${new Date().toISOString().slice(0, 10)}.xlsx`);
}

export function backupPayload(data: AppData) {
  return {
    format: 'trading-control-center-backup',
    version: 1,
    exportedAt: new Date().toISOString(),
    disclaimer: 'Este arquivo contém os dados reais registrados pelo usuário e, se houver, dados marcados como simulação.',
    data,
  };
}
