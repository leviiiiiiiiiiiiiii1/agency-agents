import React, { useMemo, useState } from 'react';
import { Table2, Download, ArrowUp, ArrowDown, Info, SlidersHorizontal } from 'lucide-react';
import { useStore } from '../state/store';
import { PageHeader, Card, CardHead, Notice, Segmented, EmptyState } from '../components/ui';
import { seriesBlocks, sortOps, stats, balanceAt } from '../lib/calc';
import { money, pct, formatDate, downloadCsv } from '../lib/format';
import { addDays } from '../lib/format';

type GroupMode = 'series' | 'day';

export function SeriesPage() {
  const { data, ops, toast } = useStore();
  const s = data.settings;
  const [mode, setMode] = useState<GroupMode>('series');
  const [limit, setLimit] = useState(60);

  const prepared = useMemo(() => {
    if (mode === 'day') {
      // Agrupa por dia, usando a data como identificador de série
      return { ...data, operations: ops.map((o) => ({ ...o, seriesId: `dia-${o.date}` })) };
    }
    return { ...data, operations: ops.map((o) => ({ ...o, seriesId: o.seriesId || `dia-${o.date}` })) };
  }, [data, ops, mode]);

  const blocks = useMemo(() => seriesBlocks(prepared, prepared.operations).slice(-limit), [prepared, limit]);

  const exportSheet = () => {
    const rows: (string | number)[][] = [['Série', 'Nº', 'W-L', 'Investimento', 'Retorno', 'Capital Atual', '% Micro Série', 'Repor Aqui', 'Data', 'Ativo']];
    for (const b of blocks) {
      b.ops.forEach((o, i) => rows.push([
        b.label, i + 1, o.result === 'WIN' ? 'W' : o.result === 'LOSS' ? 'L' : 'D',
        o.entry, o.profit, '', '', o.result === 'WIN' ? '▲' : '▼', formatDate(o.date, s), o.asset,
      ]));
      rows.push([b.label, 'Resultados', '', b.totalEntry, b.totalReturn, b.endCapital, pct(b.s.winRate, 2), '', '', '']);
    }
    downloadCsv(`micro-series-${new Date().toISOString().slice(0, 10)}.csv`, rows);
    toast('Planilha de micro séries exportada em CSV.');
  };

  const rowOf = (b: typeof blocks[number], o: typeof blocks[number]['ops'][number], i: number, runningCapital: number, runningWinRate: number) => (
    <tr key={o.id} className={o.result === 'WIN' ? 'row-win' : o.result === 'LOSS' ? 'row-loss' : ''}>
      {i === 0 && <td className="series-cell" rowSpan={b.ops.length + 1}>
        <div style={{ fontSize: 15 }}>{pct(b.s.winRate, 2)}</div>
        <div className="tiny" style={{ opacity: .8 }}>{b.label}</div>
      </td>}
      <td>{i + 1}</td>
      <td style={{ fontWeight: 800, color: o.result === 'WIN' ? 'var(--pos)' : o.result === 'LOSS' ? 'var(--neg)' : undefined }}>
        {o.result === 'WIN' ? 'W' : o.result === 'LOSS' ? 'L' : 'D'}
      </td>
      <td>{money(o.entry, s)}</td>
      <td className={o.profit >= 0 ? 'pos' : 'neg'}>{money(o.profit, s, { signed: true })}</td>
      <td>{money(runningCapital, s)}</td>
      <td><ArrowUp size={11} style={{ verticalAlign: 'middle', color: o.profit >= 0 ? 'var(--pos)' : 'var(--neg)', transform: o.profit < 0 ? 'rotate(180deg)' : undefined }} /> {pct(runningWinRate, 2)}</td>
      <td className={o.result === 'LOSS' ? 'arrow-loss' : 'arrow-win'} style={{ background: o.result === 'LOSS' ? 'var(--sheet-loss)' : undefined }}>
        {o.result === 'WIN' ? '▲' : '▼'}
      </td>
      <td className="left tiny muted">{formatDate(o.date, s, false)}</td>
      <td className="left tiny">{o.asset}</td>
    </tr>
  );

  return (
    <>
      <PageHeader title="Planilha / Micro séries" description="Visão em formato de planilha inspirada no modelo enviado: linhas verdes/vermelhas por resultado, blocos de micro séries com assertividade, totais de investimento e retorno, capital atual e marcação de recomposição."
        actions={<>
          <button className="btn" onClick={exportSheet}><Download size={15} /> Exportar planilha</button>
        </>} />

      <Card className="pad-0 mb-14">
        <div className="filter-bar">
          <div className="field"><label className="field-label">Agrupar micro séries por</label>
            <Segmented value={mode} options={[{ value: 'series', label: 'Série informada' }, { value: 'day', label: 'Dia' }]} onChange={setMode} />
          </div>
          <div className="field"><label className="field-label">Últimos blocos exibidos</label>
            <select className="select" value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[10, 20, 40, 60, 100, 500].map((n) => <option key={n} value={n}>{n} séries</option>)}
            </select>
          </div>
          <div className="field"><label className="field-label">Como definir uma série</label>
            <div className="small muted" style={{ paddingTop: 5 }}>Preencha o campo <b>Micro série</b> no formulário de cada operação.</div>
          </div>
        </div>
      </Card>

      {blocks.length === 0 ? (
        <Card><EmptyState icon={<Table2 size={34} />} title="Nenhuma série para exibir"
          text="As micro séries surgem a partir das operações registradas. Cada operação sem série informada é agrupada automaticamente pelo dia — nenhum dado de exemplo é criado." /></Card>
      ) : (
        <>
          <div className="grid grid-4 mb-14">
            <div className="card stat-card"><div className="stat-top">Séries exibidas</div><div className="stat-value">{blocks.length}</div><div className="stat-foot">{blocks.reduce((a, b) => a + b.ops.length, 0)} operações</div></div>
            <div className="card stat-card"><div className="stat-top">Investimento total</div><div className="stat-value sm">{money(blocks.reduce((a, b) => a + b.totalEntry, 0), s)}</div><div className="stat-foot">Somatório das entradas</div></div>
            <div className="card stat-card"><div className="stat-top">Retorno total</div><div className={`stat-value sm ${blocks.reduce((a, b) => a + b.totalReturn, 0) >= 0 ? 'value-pos' : 'value-neg'}`}>{money(blocks.reduce((a, b) => a + b.totalReturn, 0), s, { signed: true })}</div><div className="stat-foot">Lucro / prejuízo</div></div>
            <div className="card stat-card"><div className="stat-top">Assertividade média</div><div className="stat-value">{pct(stats(prepared.operations).winRate, 2)}</div><div className="stat-foot">Sobre as operações exibidas</div></div>
          </div>

          <Card>
            <CardHead title="Séries e resultados" sub={`${blocks.length} blocos · role horizontalmente em telas menores`} right={<SlidersHorizontal size={15} className="muted" />} />
            <div className="table-wrap" style={{ maxHeight: 760, overflow: 'auto' }}>
              <table className="sheet">
                <thead><tr>
                  <th style={{ width: 90 }}>Observação Nº</th><th style={{ width: 40 }}>Nº</th><th style={{ width: 46 }}>W - L</th>
                  <th>Investimento</th><th>Retorno</th><th>Capital Atual</th><th style={{ width: 130 }}>% Micro Série</th>
                  <th style={{ width: 90 }}>Repor Aqui</th><th>Data</th><th>Ativo</th>
                </tr></thead>
                <tbody>
                  {blocks.map((b) => {
                    let capital = balanceAt(prepared, addDays(b.ops[0].date, -1), prepared.operations);
                    const rows: React.ReactNode[] = [];
                    b.ops.forEach((o, i) => {
                      capital += o.profit;
                      const partial = stats(b.ops.slice(0, i + 1));
                      rows.push(rowOf(b, o, i, capital, partial.winRate));
                    });
                    rows.push(
                      <tr className="row-summary" key={`sum-${b.id}`}>
                        <td style={{ textAlign: 'right', fontWeight: 700 }}>Resultados</td>
                        <td />
                        <td>{money(b.totalEntry, s)}</td><td className={b.totalReturn >= 0 ? 'pos' : 'neg'}>{money(b.totalReturn, s, { signed: true })}</td>
                        <td>{money(b.endCapital, s)}</td><td>{pct(b.s.winRate, 2)}</td>
                        <td className="profit-total" colSpan={3}>{`Lucro de ${pct(b.profitPct, 3)} | ${pct(b.capitalPct, 2)}`}</td>
                      </tr>,
                    );
                    return rows;
                  })}
                </tbody>
              </table>
            </div>
            <div className="row wrap mt-14 tiny muted" style={{ gap: 16 }}>
              <span><i className="legend-dot" style={{ background: 'var(--pos)' }} /> WIN (fundo verde)</span>
              <span><i className="legend-dot" style={{ background: 'var(--neg)' }} /> LOSS (fundo vermelho)</span>
              <span>▲ recomposição positiva · ▼ recomposição negativa</span>
            </div>
          </Card>

          <div className="mt-14"><Notice><Info size={14} /> O "Capital Atual" de cada linha parte do saldo de abertura do primeiro dia da série e soma os retornos linha a linha. "% Micro Série" mostra a assertividade acumulada dentro do bloco. Os totais usam exclusivamente operações registradas — reais ou de simulação, quando esta última estiver habilitada.</Notice></div>
        </>
      )}
    </>
  );
}
