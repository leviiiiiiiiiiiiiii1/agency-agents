import React, { useMemo, useState } from 'react';
import {
  Wallet, Landmark, CalendarClock, TrendingUp, Percent, Hash, CircleCheck, CircleX,
  MinusCircle, Crosshair, BarChart4, Coins, Flame, ArrowDownRight, Trophy, TrendingDown,
  Target, ShieldAlert, Wand2, Plus, Settings2, GripVertical, Eye, EyeOff, RotateCcw,
  FlaskConical, ArrowUpRight, Activity,
} from 'lucide-react';
import { useStore } from '../state/store';
import { Card, CardHead, StatCard, Modal, EmptyState, PageHeader, Notice } from '../components/ui';
import { EquityChart, DayBars, ResultPie, Sparkline } from '../components/charts';
import { dashboardMetrics, totalProfitability, equityCurve, suggestEntry, sortOps } from '../lib/calc';
import { money, pct, formatDate } from '../lib/format';
import { DASHBOARD_CARDS } from '../lib/defaults';
import { makeDemoOperations } from '../lib/sample';
import type { DashboardCardDef } from '../types';

export function DashboardPage() {
  const store = useStore();
  const { data, setData, ops, refDate, openOpEditor, loadDemo, toast, setIncludeDemo } = store;
  const [customizing, setCustomizing] = useState(false);
  const [dragId, setDragId] = useState<string | null>(null);

  const m = useMemo(() => dashboardMetrics(data, ops, refDate), [data, ops, refDate]);
  const curve = useMemo(() => equityCurve(data, ops), [data, ops]);
  const suggestion = useMemo(() => suggestEntry(data, ops, refDate), [data, ops, refDate]);
  const s = data.settings;
  const profitability = totalProfitability(data, ops);
  const recent = sortOps(ops).slice(-6).reverse();
  const hasData = ops.length > 0;

  const cardMeta = Object.fromEntries(DASHBOARD_CARDS.map((c) => [c.id, c]));
  const visibleCards = s.dashboardCards.filter((c) => c.visible);

  const setCards = (cards: DashboardCardDef[]) => setData((d) => ({ ...d, settings: { ...d.settings, dashboardCards: cards } }));

  const renderCard = (id: string): React.ReactNode => {
    switch (id) {
      case 'balance': return <StatCard label="Saldo atual" icon={<Wallet size={14} />} value={money(m.balance, s)} tone="accent" foot={<span className={m.balance >= m.initialBalance ? 'value-pos' : 'value-neg'}>{money(m.balance - m.initialBalance, s, { signed: true })} vs. banca inicial</span>} />;
      case 'initialBalance': return <StatCard label="Banca inicial" icon={<Landmark size={14} />} value={money(m.initialBalance, s)} foot={`${data.ledger.length} movimentação(ões) registrada(s)`} />;
      case 'dayResult': return <StatCard label="Lucro / prejuízo do dia" icon={<CalendarClock size={14} />} value={money(m.dayNet, s, { signed: true })} tone={m.dayNet > 0 ? 'pos' : m.dayNet < 0 ? 'neg' : undefined} foot={`${m.dayOps} operação(ões) em ${formatDate(refDate, s)}`} />;
      case 'totalResult': return <StatCard label="Lucro / prejuízo acumulado" icon={<TrendingUp size={14} />} value={money(m.totalNet, s, { signed: true })} tone={m.totalNet > 0 ? 'pos' : m.totalNet < 0 ? 'neg' : undefined} foot={`${m.s.grossProfit ? money(m.s.grossProfit, s) : money(0, s)} em ganhos · ${money(m.s.grossLoss, s)} em perdas`} />;
      case 'profitability': return <StatCard label="Rentabilidade" icon={<Percent size={14} />} value={pct(profitability, 2, true)} tone={profitability > 0 ? 'pos' : profitability < 0 ? 'neg' : undefined} foot="Sobre banca inicial + depósitos" />;
      case 'totalOps': return <StatCard label="Total de operações" icon={<Hash size={14} />} value={m.s.count} foot={`${money(m.s.totalEntry, s)} de volume investido`} />;
      case 'wins': return <StatCard label="WIN" icon={<CircleCheck size={14} />} value={m.s.wins} tone="pos" foot={`${pct(m.s.winRateAll, 1)} do total de operações`} />;
      case 'losses': return <StatCard label="LOSS" icon={<CircleX size={14} />} value={m.s.losses} tone="neg" foot={`Média de ${money(m.s.avgLoss, s)} por perda`} />;
      case 'draws': return <StatCard label="DRAW" icon={<MinusCircle size={14} />} value={m.s.draws} foot="Sem alteração financeira" />;
      case 'winRate': return <StatCard label="Assertividade" icon={<Crosshair size={14} />} value={pct(m.s.winRate, 1)} tone="accent" foot={`${m.s.wins} WIN / ${m.s.wins + m.s.losses} decisões`} />;
      case 'avgPayout': return <StatCard label="Payout médio" icon={<BarChart4 size={14} />} value={pct(m.s.avgPayout, 1)} foot="Média de todos os registros" />;
      case 'avgEntry': return <StatCard label="Valor médio por operação" icon={<Coins size={14} />} value={money(m.s.avgEntry, s)} foot={`Fator de lucro: ${Number.isFinite(m.s.profitFactor) ? m.s.profitFactor.toFixed(2) : '∞'}`} />;
      case 'maxWinStreak': return <StatCard label="Maior sequência de WIN" icon={<Flame size={14} />} value={m.maxWinStreak} tone="pos" foot={`Sequência atual: ${m.s.currentStreak.result === 'WIN' ? m.s.currentStreak.length + ' WIN' : '—'}`} />;
      case 'maxLossStreak': return <StatCard label="Maior sequência de LOSS" icon={<ArrowDownRight size={14} />} value={m.maxLossStreak} tone={m.maxLossStreak ? 'neg' : undefined} foot="Histórico completo" />;
      case 'bestDay': return <StatCard label="Melhor dia" icon={<Trophy size={14} />} value={m.bestDay ? money(m.bestDay.net, s, { signed: true }) : '—'} tone="pos" foot={m.bestDay ? `${formatDate(m.bestDay.date, s)} · ${m.bestDay.s.count} ops` : 'Sem dias registrados'} />;
      case 'worstDay': return <StatCard label="Pior dia" icon={<TrendingDown size={14} />} value={m.worstDay ? money(m.worstDay.net, s, { signed: true }) : '—'} tone="neg" foot={m.worstDay ? `${formatDate(m.worstDay.date, s)} · ${m.worstDay.s.count} ops` : 'Sem dias registrados'} />;
      case 'dailyGoal': return (
        <Card>
          <CardHead title="Meta diária" sub={`${s.dailyGoal.mode === 'percent' ? `${s.dailyGoal.value}% da banca` : money(s.dailyGoal.value, s)} · ${formatDate(refDate, s)}`}
            right={<span className={`badge ${m.goalProgress >= 100 ? 'badge-accent' : 'badge-draw'}`}>{m.goalProgress.toFixed(0).replace('.', ',')}%</span>} />
          <div className="row between"><span className="stat-value sm value-accent">{money(m.dayNet, s, { signed: true })}</span><span className="small muted">de {money(m.goalValue, s)}</span></div>
          <div className="progress-track mt-14"><div className="progress-fill" style={{ width: `${m.goalProgress}%` }} /></div>
          <div className="stat-foot mt-8">{m.goalProgress >= 100 ? '✅ Meta atingida' : `Faltam ${money(Math.max(0, m.goalValue - m.dayNet), s)}`} · Stop Gain: {money(m.stopGainValue, s)}</div>
        </Card>
      );
      case 'stopLoss': return (
        <Card>
          <CardHead title="Limite de perda diária" sub={`${s.stopLoss.mode === 'percent' ? `${s.stopLoss.value}% da banca de abertura` : money(s.stopLoss.value, s)} · base ${money(m.dayBalanceStart, s)}`}
            right={<ShieldAlert size={16} className="value-neg" />} />
          <div className="row between"><span className="stat-value sm value-neg">{money(m.remainingLoss, s)}</span><span className="small muted">ainda posso perder</span></div>
          <div className="progress-track mt-14"><div className="progress-fill neg" style={{ width: `${m.stopLossValue ? Math.min(100, (1 - m.remainingLoss / m.stopLossValue) * 100) : 0}%` }} /></div>
          <div className="stat-foot mt-8">Consumido: {money(Math.max(0, -m.dayNet), s)} de {money(m.stopLossValue, s)} · {m.opsToday}/{s.maxOpsPerDay} operações</div>
        </Card>
      );
      case 'nextEntry': return (
        <Card>
          <CardHead title="Próxima entrada sugerida" sub={`Gerenciamento: ${modeLabel(s.activeManagement)}`} right={<Wand2 size={16} className="value-accent" />} />
          <div className="row between"><span className="stat-value sm value-accent">{money(suggestion.value, s)}</span><button className="btn sm primary" onClick={() => openOpEditor('new')}><Plus size={13} /> Registrar</button></div>
          <div className="small muted mt-8" style={{ lineHeight: 1.6 }}>{suggestion.explanation}</div>
          {suggestion.limits.warnings.length > 0 && <div className="mt-8"><Notice kind="warn">{suggestion.limits.warnings[0].label}{suggestion.limits.warnings.length > 1 ? ` (+${suggestion.limits.warnings.length - 1} avisos)` : ''}</Notice></div>}
        </Card>
      );
      case 'equity': return (
        <Card>
          <CardHead title="Curva de evolução da banca" sub="Saldo ao final de cada dia com operações" right={<Activity size={15} className="muted" />} />
          {curve.length ? <EquityChart points={curve} height={220} /> : <div className="empty-state small muted">Sem dados para o gráfico</div>}
          {curve.length > 1 && <div className="mt-8"><Sparkline points={curve} /></div>}
        </Card>
      );
      case 'dayBars': return (
        <Card><CardHead title="Resultado por dia" sub="Lucro / prejuízo diário" />{curve.length ? <DayBars points={curve} height={220} /> : <div className="empty-state small muted">Sem dados para o gráfico</div>}</Card>
      );
      case 'resultPie': return (
        <Card><CardHead title="Distribuição de resultados" sub="WIN · LOSS · DRAW" />{m.s.count ? <ResultPie wins={m.s.wins} losses={m.s.losses} draws={m.s.draws} height={220} /> : <div className="empty-state small muted">Sem dados para o gráfico</div>}</Card>
      );
      case 'recent': return (
        <Card className="pad-0">
          <div className="card-head" style={{ padding: '16px 18px 10px', margin: 0 }}><h3>Últimas operações</h3><div className="right"><button className="btn xs" onClick={() => openOpEditor('new')}><Plus size={12} /> Nova</button></div></div>
          <div className="table-wrap" style={{ border: 0, borderRadius: 0 }}>
            <table className="table"><thead><tr><th>Data</th><th>Ativo</th><th>Resultado</th><th className="num">Entrada</th><th className="num">Retorno</th></tr></thead>
              <tbody>{recent.length === 0 && <tr><td colSpan={5} className="center muted" style={{ padding: 24 }}>Nenhuma operação registrada</td></tr>}
                {recent.map((o) => <tr key={o.id} style={{ cursor: 'pointer' }} onClick={() => openOpEditor(o)}>
                  <td>{formatDate(o.date, s, false)} <span className="muted tiny">{o.time}</span></td>
                  <td className="strong">{o.asset || '—'}</td>
                  <td><span className={`badge badge-${o.result.toLowerCase()}`}>{o.result}</span>{o.demo && <span className="badge badge-demo" style={{ marginLeft: 4 }}>SIM</span>}</td>
                  <td className="num">{money(o.entry, s)}</td>
                  <td className={`num ${o.profit >= 0 ? 'value-pos' : 'value-neg'}`}>{money(o.profit, s, { signed: true })}</td>
                </tr>)}
              </tbody></table>
          </div>
        </Card>
      );
      default: return null;
    }
  };

  return (
    <>
      <PageHeader title="Centro de controle" description={`Visão consolidada de ${formatDate(refDate, s)}. Todos os indicadores são calculados automaticamente a partir das operações registradas — nenhum dado é fictício.`}
        actions={<>
          <button className="btn" onClick={() => setCustomizing(true)}><Settings2 size={15} /> Personalizar cards</button>
          <button className="btn primary" onClick={() => openOpEditor('new')}><Plus size={15} /> Nova operação</button>
        </>} />

      {!hasData && (
        <Card className="mb-14">
          <EmptyState
            icon={<FlaskConical size={34} />}
            title="Nenhuma operação real registrada ainda"
            text="A plataforma começa vazia por princípio: não exibimos números fictícios como se fossem resultados reais. Registre sua primeira operação ou carregue um conjunto de exemplo claramente identificado como SIMULAÇÃO para explorar os recursos."
            action={<div className="btn-row" style={{ justifyContent: 'center' }}>
              <button className="btn primary" onClick={() => openOpEditor('new')}><Plus size={15} /> Registrar operação real</button>
              <button className="btn" onClick={() => { loadDemo(makeDemoOperations()); setIncludeDemo(true); toast('Exemplo demonstrativo carregado e identificado como SIMULAÇÃO.', 'info'); }}>
                <FlaskConical size={15} /> Carregar exemplo demonstrativo
              </button>
            </div>}
          />
        </Card>
      )}

      <div className="grid grid-dash">
        {visibleCards.map((c) => (
          <div key={c.id} className={`span-${c.span}`} style={{ minWidth: 0 }}>
            {renderCard(c.id)}
          </div>
        ))}
      </div>

      {hasData && (
        <>
          <div className="section-title">Resumo operacional do dia</div>
          <Card>
            <div className="grid grid-4">
              <div><div className="field-label mb-8">Sequência de resultados</div>
                <div className="result-seq">{m.s.sequence.slice(-30).map((r, i) => <span key={i} className={`seq-dot ${r}`}>{r[0]}</span>)}</div>
                {m.s.sequence.length === 0 && <span className="muted small">—</span>}
              </div>
              <div><div className="field-label mb-8">Exposição hoje</div><div className="mono" style={{ fontSize: 18 }}>{money(m.exposureToday, s)}</div><span className="tiny muted">Limite: {s.maxExposurePercent}% da banca</span></div>
              <div><div className="field-label mb-8">LOSS consecutivos</div><div className="mono" style={{ fontSize: 18 }}>{m.consecutiveLoss} <span className="tiny muted">/ {s.maxConsecutiveLoss || '∞'}</span></div><span className="tiny muted">Limite configurável</span></div>
              <div><div className="field-label mb-8">Expectativa matemática</div><div className={`mono ${m.s.expectancy >= 0 ? 'value-pos' : 'value-neg'}`} style={{ fontSize: 18 }}>{money(m.s.expectancy, s, { signed: true })}</div><span className="tiny muted">Por operação decidida</span></div>
            </div>
          </Card>
        </>
      )}

      {customizing && (
        <Modal title="Personalizar dashboard" sub="Arraste para reorganizar, oculte/exiba cards e ajuste a largura. As preferências ficam salvas neste navegador."
          onClose={() => setCustomizing(false)} wide
          footer={<>
            <button className="btn" onClick={() => setCards(DASHBOARD_CARDS.map((c) => ({ id: c.id, visible: true, span: c.defaultSpan })))}><RotateCcw size={14} /> Restaurar padrão</button>
            <button className="btn primary" onClick={() => setCustomizing(false)}>Concluir</button>
          </>}>
          <div className="small muted mb-14">Cards visíveis: {visibleCards.length} de {DASHBOARD_CARDS.length} · Largura em colunas de um grid de 4.</div>
          {s.dashboardCards.map((c, idx) => (
            <div key={c.id}
              className={`card-order ${dragId === c.id ? 'dragging' : ''}`}
              draggable
              onDragStart={() => setDragId(c.id)}
              onDragEnd={() => setDragId(null)}
              onDragOver={(e) => e.preventDefault()}
              onDrop={() => {
                if (!dragId || dragId === c.id) return;
                const list = [...s.dashboardCards];
                const from = list.findIndex((x) => x.id === dragId);
                const to = list.findIndex((x) => x.id === c.id);
                const [item] = list.splice(from, 1);
                list.splice(to, 0, item);
                setCards(list);
                setDragId(null);
              }}
            >
              <GripVertical size={15} className="grip" />
              <span className="tiny mono muted">{String(idx + 1).padStart(2, '0')}</span>
              <span className="name">{cardMeta[c.id]?.label || c.id}</span>
              <span className="tag">{cardMeta[c.id]?.group}</span>
              <div className="mode-toggle">
                {([1, 2, 3, 4] as const).map((n) => (
                  <button key={n} type="button" className={c.span === n ? 'on' : ''} onClick={() => setCards(s.dashboardCards.map((x) => x.id === c.id ? { ...x, span: n } : x))}>{n}</button>
                ))}
              </div>
              <button className="icon-btn" title={c.visible ? 'Ocultar' : 'Exibir'} onClick={() => setCards(s.dashboardCards.map((x) => x.id === c.id ? { ...x, visible: !x.visible } : x))}>
                {c.visible ? <Eye size={14} /> : <EyeOff size={14} />}
              </button>
            </div>
          ))}
        </Modal>
      )}
    </>
  );
}

const modeLabel = (m: string) => ({
  fixed: 'Valor fixo', percent: 'Percentual da banca', sorosN1: 'Soros N1', sorosN2: 'Soros N2',
  sorosCustom: 'Soros personalizado', martingale: 'Martingale', custom: 'Personalizado',
}[m] || m);
