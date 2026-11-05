import React, { useMemo, useState } from 'react';
import { BarChart3, TrendingUp, CalendarRange, PieChart as PieIcon, LayoutGrid, Layers3, Download } from 'lucide-react';
import { useStore } from '../state/store';
import { PageHeader, Card, CardHead, DateRangeBar, Notice, Segmented, EmptyState } from '../components/ui';
import { EquityChart, DayBars, ResultPie, WinRateLine, GroupBars, GroupTable, SimpleBars, MultiSeriesChart } from '../components/charts';
import {
  equityCurve, stats, byAsset, byStrategy, byHour, byTimeframe, byPayout,
  byWeek, byMonth, inRange, sortOps,
} from '../lib/calc';
import { money, pct, formatDate, weekLabel, weekKey } from '../lib/format';
import { exportExcel } from '../lib/exporters';

type Tab = 'evolucao' | 'distribuicao' | 'desempenho' | 'estrategias' | 'tabelas';

export function RelatoriosPage() {
  const { data, ops, range, setRange, toast } = useStore();
  const s = data.settings;
  const [tab, setTab] = useState<Tab>('evolucao');
  const [equityMode, setEquityMode] = useState<'balance' | 'cumulative'>('balance');

  const filtered = useMemo(() => ops.filter((o) => inRange(o, range.from, range.to)), [ops, range]);
  const st = useMemo(() => stats(filtered), [filtered]);
  const curve = useMemo(() => equityCurve(data, filtered), [data, filtered]);
  const weeks = byWeek(filtered).sort((a, b) => a.key.localeCompare(b.key));
  const months = byMonth(filtered).sort((a, b) => a.key.localeCompare(b.key));
  const groups = useMemo(() => ({
    asset: byAsset(filtered), strategy: byStrategy(filtered, data.strategies),
    hour: byHour(filtered).sort((a, b) => a.key.localeCompare(b.key)),
    timeframe: byTimeframe(filtered), payout: byPayout(filtered),
  }), [filtered, data.strategies]);

  const strategyComparison = useMemo(() => {
    const sorted = sortOps(filtered);
    const ids = [...new Set(sorted.map((o) => o.strategyId || 'none'))].slice(0, 6);
    const dates = [...new Set(sorted.map((o) => o.date))].sort();
    const acc: Record<string, number> = Object.fromEntries(ids.map((i) => [i, 0]));
    return dates.map((date) => {
      for (const o of sorted.filter((x) => x.date === date)) acc[o.strategyId || 'none'] = (acc[o.strategyId || 'none'] || 0) + o.profit;
      const point: Record<string, string | number> = { label: formatDate(date, s, false), date };
      for (const id of ids) point[id] = Math.round(acc[id] * 100) / 100;
      return point;
    });
  }, [filtered, s]);

  const palette = ['var(--accent)', '#60a5fa', '#f59e0b', '#a78bfa', '#f472b6', '#34d399'];
  const series = [...new Set(sortOps(filtered).map((o) => o.strategyId || 'none'))].slice(0, 6).map((id, i) => ({
    key: id, color: palette[i % palette.length],
    label: id === 'none' ? 'Sem estratégia' : data.strategies.find((x) => x.id === id)?.name || 'Estratégia removida',
  }));

  return (
    <>
      <PageHeader title="Relatórios & estatísticas" description="Análise interativa do histórico real. Passe o mouse sobre os pontos para ver valores detalhados e filtre por qualquer intervalo de datas."
        actions={<button className="btn" onClick={() => { exportExcel(data, filtered); toast('Relatório Excel exportado.'); }}><Download size={15} /> Exportar Excel</button>} />

      <DateRangeBar from={range.from} to={range.to} onChange={setRange} extra={
        <div className="field"><label className="field-label">Período selecionado</label><div className="pill-list" style={{ paddingTop: 5 }}>
          <span className="pill">{filtered.length} ops</span>
          <span className="pill"><b className={st.net >= 0 ? 'value-pos' : 'value-neg'}>{money(st.net, s, { signed: true })}</b></span>
          <span className="pill">{pct(st.winRate, 1)} assert.</span>
        </div></div>
      } />

      {filtered.length === 0 ? (
        <Card><EmptyState title="Sem dados no período selecionado" text="Ajuste o intervalo de datas ou registre operações para gerar os gráficos. Nenhum gráfico é preenchido com dados inventados." /></Card>
      ) : <>
        <div className="tabs mb-14">
          {([
            ['evolucao', 'Evolução & período'], ['distribuicao', 'Distribuição'],
            ['desempenho', 'Desempenho'], ['estrategias', 'Comparação de estratégias'], ['tabelas', 'Tabelas detalhadas'],
          ] as [Tab, string][]).map(([id, label]) => <button key={id} className={tab === id ? 'on' : ''} onClick={() => setTab(id)}>{label}</button>)}
        </div>

        {tab === 'evolucao' && <>
          <div className="grid grid-4 mb-14">
            <div className="card stat-card"><div className="stat-top"><TrendingUp size={14} /> Resultado no período</div><div className={`stat-value ${st.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(st.net, s, { signed: true })}</div><div className="stat-foot">{curve.length} dias com operações</div></div>
            <div className="card stat-card"><div className="stat-top">Volume investido</div><div className="stat-value sm">{money(st.totalEntry, s)}</div><div className="stat-foot">{money(st.avgEntry, s)} por operação</div></div>
            <div className="card stat-card"><div className="stat-top">Melhor / pior operação</div><div className="stat-value sm"><span className="value-pos">{money(st.bestTrade, s)}</span> / <span className="value-neg">{money(st.worstTrade, s)}</span></div><div className="stat-foot">Fator de lucro {Number.isFinite(st.profitFactor) ? st.profitFactor.toFixed(2) : '∞'}</div></div>
            <div className="card stat-card"><div className="stat-top">Expectativa</div><div className={`stat-value ${st.expectancy >= 0 ? 'value-pos' : 'value-neg'}`}>{money(st.expectancy, s, { signed: true })}</div><div className="stat-foot">Por operação decidida</div></div>
          </div>
          <div className="grid grid-2">
            <Card><CardHead title="Curva de evolução da banca (Equity Curve)" sub="Saldo ao final de cada dia" right={<Segmented value={equityMode} options={[{ value: 'balance', label: 'Saldo' }, { value: 'cumulative', label: 'Lucro acumulado' }]} onChange={setEquityMode} />} />
              <EquityChart points={curve} height={300} showNet={equityMode === 'cumulative'} /></Card>
            <Card><CardHead title="Lucro / prejuízo por dia" sub="Barras verdes = positivo, vermelhas = negativo" /><DayBars points={curve} height={300} /></Card>
            <Card><CardHead title="Resultado semanal" sub="Agrupado pela semana (início na segunda-feira)" right={<CalendarRange size={15} className="muted" />} />
              <SimpleBars data={weeks.map((w) => ({ label: formatDate(w.key, s, false), value: w.net }))} name="Resultado semanal" /></Card>
            <Card><CardHead title="Resultado mensal" sub="Somatório por mês" />
              <SimpleBars data={months.map((m) => ({ label: m.key, value: m.net }))} name="Resultado mensal" /></Card>
            <Card><CardHead title="Assertividade ao longo do tempo" sub="Percentual acumulado de WIN sobre decisões" /><WinRateLine points={curve} height={260} /></Card>
            <Card><CardHead title="Distribuição WIN / LOSS / DRAW" sub={`${st.wins} · ${st.losses} · ${st.draws}`} right={<PieIcon size={15} className="muted" />} /><ResultPie wins={st.wins} losses={st.losses} draws={st.draws} height={260} /></Card>
          </div>
        </>}

        {tab === 'distribuicao' && <>
          <div className="grid grid-2">
            <Card><CardHead title="Desempenho por ativo" sub="Resultado financeiro por ativo negociado" /><GroupBars groups={groups.asset} /></Card>
            <Card><CardHead title="Desempenho por horário" sub="Hora de entrada (00h–23h)" /><GroupBars groups={groups.hour} /></Card>
            <Card><CardHead title="Desempenho por timeframe" sub="M1, M5, M15..." /><GroupBars groups={groups.timeframe} /></Card>
            <Card><CardHead title="Desempenho por payout" sub="Faixas de payout registradas" /><GroupBars groups={groups.payout} /></Card>
          </div>
          <div className="section-title">Resumo por dia</div>
          <Card className="pad-0"><div className="table-wrap" style={{ border: 0 }}>
            <table className="table"><thead><tr><th>Data</th><th className="num">Ops</th><th className="num">W/L/D</th><th className="num">Assertividade</th><th className="num">Resultado</th><th className="num">Acumulado</th><th className="num">Saldo</th></tr></thead>
              <tbody>{curve.map((p) => <tr key={p.date}><td>{formatDate(p.date, s)}</td><td className="num">{p.ops}</td>
                <td className="num">—</td><td className="num">{p.winRate.toFixed(1).replace('.', ',')}%</td>
                <td className={`num ${p.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(p.net, s, { signed: true })}</td>
                <td className="num">{money(p.cumulative, s)}</td><td className="num strong">{money(p.balance, s)}</td></tr>)}</tbody>
            </table></div></Card>
        </>}

        {tab === 'desempenho' && <>
          <div className="grid grid-2">
            {([['asset', 'Ativo'], ['strategy', 'Estratégia'], ['hour', 'Horário'], ['timeframe', 'Timeframe'], ['payout', 'Payout']] as const).map(([key, label]) => (
              <Card key={key}><CardHead title={`Desempenho por ${label.toLowerCase()}`} sub="Ordenado por resultado financeiro" /><GroupBars groups={key === 'hour' ? groups.hour : groups[key]} /></Card>
            ))}
          </div>
          <div className="section-title">Ranking de horários mais lucrativos</div>
          <Card><div className="grid grid-3">
            {[...groups.hour].sort((a, b) => b.net - a.net).slice(0, 3).map((g, i) => (
              <div key={g.key} className="rank-row"><span className={`rank-num ${i === 0 ? 'top' : ''}`}>#{i + 1}</span>
                <div style={{ flex: 1 }}><div className="strong">{g.label}</div><div className="tiny muted">{g.count} ops · {pct(g.winRate, 1)} de assertividade</div></div>
                <b className={`mono ${g.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(g.net, s, { signed: true })}</b></div>
            ))}
          </div></Card>
        </>}

        {tab === 'estrategias' && <>
          <Card className="mb-14"><CardHead title="Comparação entre estratégias" sub="Lucro acumulado ao longo do período selecionado" right={<Layers3 size={15} className="muted" />} />
            {series.length === 0 ? <div className="muted small">Sem estratégias vinculadas às operações.</div> : <MultiSeriesChart data={strategyComparison} series={series} height={320} />}
          </Card>
          <div className="grid grid-2">
            <Card><CardHead title="Resultado por estratégia" /><GroupBars groups={groups.strategy} /></Card>
            <Card><CardHead title="Ranking de estratégias" sub="Ordenado por resultado real acumulado" />
              {[...groups.strategy].sort((a, b) => b.net - a.net).map((g, i) => (
                <div key={g.key} className="rank-row"><span className={`rank-num ${i === 0 ? 'top' : ''}`}>#{i + 1}</span>
                  <div style={{ flex: 1 }}><div className="strong">{g.label}</div><div className="tiny muted">{g.count} ops · {pct(g.winRate, 1)} · payout {pct(g.avgPayout, 0)}</div></div>
                  <b className={`mono ${g.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(g.net, s, { signed: true })}</b></div>
              ))}
            </Card>
          </div>
          <div className="mt-14"><Notice><LayoutGrid size={14} /> O ranking considera exclusivamente operações registradas no intervalo selecionado. Estratégias sem histórico não aparecem como "melhores" — não há estimativas inventadas.</Notice></div>
        </>}

        {tab === 'tabelas' && <>
          {([['Ativo', groups.asset], ['Estratégia', groups.strategy], ['Horário', groups.hour], ['Timeframe', groups.timeframe], ['Payout', groups.payout]] as const).map(([label, g]) => (
            <React.Fragment key={label}><div className="section-title">{label}</div><GroupTable groups={g} title={label} /></React.Fragment>
          ))}
          <div className="section-title">Semanal</div>
          <GroupTable groups={weeks.map((w) => ({ ...w, label: weekLabel(w.key, s) }))} title="Semana" />
          <div className="section-title">Mensal</div>
          <GroupTable groups={months} title="Mês" />
        </>}
      </>}
    </>
  );
}
