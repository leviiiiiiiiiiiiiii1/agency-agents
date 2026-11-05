import React, { useMemo, useState } from 'react';
import { ChevronLeft, ChevronRight, CalendarDays, Target, Flame, Clock, Layers3, Plus, Pencil, CircleHelp } from 'lucide-react';
import { useStore } from '../state/store';
import { PageHeader, Card, CardHead, StatCard, Modal, Notice } from '../components/ui';
import { OperationTable } from '../components/OperationTable';
import { dayInfos, stats, byHour, byStrategy, sortOps, resolveValue } from '../lib/calc';
import { money, pct, formatDate, monthLabel, parseISO, daysInMonth, isoOf, addDays } from '../lib/format';

export function DiarioPage() {
  const { data, setData, ops, refDate, setRefDate, openOpEditor } = useStore();
  const s = data.settings;
  const [month, setMonth] = useState(refDate.slice(0, 7));
  const [dayOpen, setDayOpen] = useState<string | null>(null);
  const [noteEdit, setNoteEdit] = useState(false);
  const [noteText, setNoteText] = useState('');

  const infos = useMemo(() => dayInfos(data, ops), [data, ops]);
  const byDate = useMemo(() => new Map(infos.map((d) => [d.date, d])), [infos]);
  const selected = byDate.get(dayOpen || refDate);
  const dayOps = selected?.ops || [];
  const ds = stats(dayOps);
  const hours = byHour(dayOps).filter((g) => g.count > 0).sort((a, b) => b.net - a.net);
  const strategies = byStrategy(dayOps, data.strategies);
  const weekDays = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

  const [year, monthNum] = month.split('-').map(Number);
  const first = new Date(year, monthNum - 1, 1);
  const offset = (first.getDay() + 6) % 7;
  const total = daysInMonth(year, monthNum - 1);
  const cells: (string | null)[] = [...Array(offset).fill(null), ...Array.from({ length: total }, (_, i) => isoOf(new Date(year, monthNum - 1, i + 1)))];

  const monthOps = ops.filter((o) => o.date.startsWith(month));
  const monthStats = stats(monthOps);
  const shiftMonth = (n: number) => {
    const d = new Date(year, monthNum - 1 + n, 1);
    setMonth(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
  };

  const openDay = (iso: string) => {
    setRefDate(iso); setDayOpen(iso);
    setNoteText(data.dayNotes[iso] || '');
  };

  return (
    <>
      <PageHeader title="Resultados diários" description="Acompanhe cada dia, identifique padrões de horário e estratégia e visualize o progresso das metas em um calendário mensal interativo."
        actions={<><button className="btn" onClick={() => setRefDate(new Date().toISOString().slice(0, 10))}><CalendarDays size={15} /> Hoje</button>
          <button className="btn primary" onClick={() => openOpEditor('new')}><Plus size={15} /> Nova operação</button></>} />

      <div className="grid grid-4 mb-14">
        <StatCard label={`Resultado de ${formatDate(refDate, s, false)}`} icon={<CalendarDays size={14} />} value={money(ds.net, s, { signed: true })} tone={ds.net > 0 ? 'pos' : ds.net < 0 ? 'neg' : undefined} foot={`${ds.count} operações`} />
        <StatCard label="Assertividade do dia" value={pct(ds.winRate, 1)} foot={`${ds.wins} WIN · ${ds.losses} LOSS · ${ds.draws} DRAW`} />
        <StatCard label="Lucro médio por WIN" value={money(ds.avgWin, s)} tone="pos" foot={`Prejuízo médio por LOSS: ${money(ds.avgLoss, s)}`} />
        <StatCard label="Payout médio" value={pct(ds.avgPayout, 1)} foot={`Valor médio: ${money(ds.avgEntry, s)}`} />
      </div>

      <div className="grid grid-2 mb-14">
        <Card>
          <CardHead title="Progresso da meta diária" sub={`Meta: ${money(selected?.goal || resolveValue(s.dailyGoal, s.initialBalance), s)} · Stop Loss: ${money(selected?.stopLoss || resolveValue(s.stopLoss, s.initialBalance), s)}`} right={<Target size={16} className="value-accent" />} />
          <div className="row between"><span className={`stat-value sm ${ds.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(ds.net, s, { signed: true })}</span>
            <span className="small muted">{selected && selected.goal > 0 ? pct((ds.net / selected.goal) * 100, 0) : '—'} da meta</span></div>
          <div className="progress-track mt-14"><div className={`progress-fill ${ds.net < 0 ? 'neg' : ''}`} style={{ width: `${selected && selected.goal > 0 ? Math.min(100, Math.max(0, (ds.net / selected.goal) * 100)) : 0}%` }} /></div>
          <div className="row mt-14 wrap" style={{ gap: 8 }}>
            {selected?.goalHit && <span className="badge badge-accent">✓ Meta atingida</span>}
            {selected?.stopLossHit && <span className="badge badge-loss">⛔ Stop Loss</span>}
            {selected?.stopGainHit && <span className="badge badge-accent">✓ Stop Gain</span>}
            {!selected && <span className="badge badge-draw">Dia sem operações</span>}
          </div>
        </Card>
        <Card>
          <CardHead title="Sequência de resultados" sub="Ordem cronológica das operações do dia" right={<Flame size={16} className="muted" />} />
          <div className="result-seq mb-14">{ds.sequence.length ? ds.sequence.map((r, i) => <span key={i} className={`seq-dot ${r}`} title={`Operação ${i + 1}: ${r}`}>{r[0]}</span>) : <span className="muted small">Sem operações neste dia</span>}</div>
          <div className="metric-line"><span className="label">Maior sequência de WIN</span><span className="val value-pos">{ds.maxWinStreak}</span></div>
          <div className="metric-line"><span className="label">Maior sequência de LOSS</span><span className="val value-neg">{ds.maxLossStreak}</span></div>
          <div className="metric-line"><span className="label">Fator de lucro</span><span className="val">{Number.isFinite(ds.profitFactor) ? ds.profitFactor.toFixed(2) : '∞'}</span></div>
          <div className="metric-line"><span className="label">Expectativa por operação</span><span className="val">{money(ds.expectancy, s, { signed: true })}</span></div>
        </Card>
      </div>

      <div className="grid grid-2 mb-14">
        <Card>
          <CardHead title="Horários mais lucrativos" sub="Agrupado pela hora da operação" right={<Clock size={15} className="muted" />} />
          {hours.length === 0 ? <div className="muted small">Sem operações neste dia.</div> : hours.slice(0, 8).map((h) => (
            <div className="metric-line" key={h.key}><span className="label">{h.label} <span className="tag">{h.count} ops</span></span><span className={`val ${h.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(h.net, s, { signed: true })}</span></div>
          ))}
        </Card>
        <Card>
          <CardHead title="Estratégias utilizadas" sub="Desempenho no dia selecionado" right={<Layers3 size={15} className="muted" />} />
          {strategies.length === 0 ? <div className="muted small">Sem operações neste dia.</div> : strategies.map((g) => (
            <div className="metric-line" key={g.key}><span className="label">{g.label} <span className="tag">{g.count} ops · {pct(g.winRate, 0)}</span></span><span className={`val ${g.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(g.net, s, { signed: true })}</span></div>
          ))}
        </Card>
      </div>

      <div className="section-title">Calendário mensal</div>
      <Card>
        <div className="row between mb-14">
          <button className="icon-btn" onClick={() => shiftMonth(-1)}><ChevronLeft size={16} /></button>
          <div style={{ textAlign: 'center' }}><h3 style={{ margin: 0, fontSize: 15, textTransform: 'capitalize' }}>{monthLabel(`${month}-01`)}</h3>
            <div className="tiny muted">Resultado do mês: <b className={monthStats.net >= 0 ? 'value-pos' : 'value-neg'}>{money(monthStats.net, s, { signed: true })}</b> · {monthStats.count} ops · {pct(monthStats.winRate, 1)} de assertividade</div>
          </div>
          <button className="icon-btn" onClick={() => shiftMonth(1)}><ChevronRight size={16} /></button>
        </div>
        <div className="calendar-grid">
          {weekDays.map((d) => <div key={d} className="cal-dow">{d}</div>)}
          {cells.map((iso, i) => {
            if (!iso) return <div key={`e${i}`} className="cal-cell empty" />;
            const info = byDate.get(iso);
            const cls = info ? (info.net > 0 ? 'is-pos' : info.net < 0 ? 'is-neg' : '') : '';
            return (
              <button key={iso} className={`cal-cell ${cls} ${info?.goalHit ? 'is-goal' : ''} ${info?.stopLossHit ? 'is-stop' : ''} ${iso === refDate ? 'today' : ''} ${iso === dayOpen ? 'selected' : ''}`}
                onClick={() => openDay(iso)}>
                <span className="cal-day">{Number(iso.slice(-2))}</span>
                {info ? <>
                  <span className={`cal-net ${info.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(info.net, s, { signed: true, decimals: 0 })}</span>
                  <span className="cal-meta">{info.s.count} ops · {pct(info.s.winRate, 0)}</span>
                </> : <span className="cal-meta">sem operações</span>}
              </button>
            );
          })}
        </div>
        <div className="row wrap mt-14 small muted" style={{ gap: 14 }}>
          <span><i className="legend-dot" style={{ background: 'var(--pos)' }} /> Dia positivo</span>
          <span><i className="legend-dot" style={{ background: 'var(--neg)' }} /> Dia negativo</span>
          <span><i className="legend-dot" style={{ background: 'var(--surface-3)' }} /> Sem operações</span>
          <span><b style={{ color: 'var(--accent)' }}>✓</b> Meta atingida</span>
          <span>⛔ Stop alcançado</span>
          <span className="tiny"><CircleHelp size={11} style={{ verticalAlign: 'middle' }} /> Clique em um dia para ver todos os detalhes</span>
        </div>
      </Card>

      <div className="mt-14"><Notice>Clique em qualquer dia do calendário para abrir as operações daquele período. Dias vazios permanecem neutros — nunca são preenchidos com valores fictícios.</Notice></div>

      {dayOpen && (
        <Modal title={`Detalhes de ${formatDate(dayOpen, s)}`} wide
          sub={`${dayOps.length} operação(ões) · resultado ${money(stats(dayOps).net, s, { signed: true })} · assertividade ${pct(stats(dayOps).winRate, 1)}`}
          onClose={() => setDayOpen(null)}
          footer={<><button className="btn" onClick={() => { setNoteText(data.dayNotes[dayOpen] || ''); setNoteEdit(true); }}><Pencil size={14} /> Anotação do dia</button>
            <button className="btn primary" onClick={() => { setRefDate(dayOpen); openOpEditor('new'); }}><Plus size={14} /> Registrar neste dia</button></>}>
          <div className="grid grid-4 mb-14">
            <div><div className="field-label">Resultado</div><div className={`mono mt-8 ${stats(dayOps).net >= 0 ? 'value-pos' : 'value-neg'}`} style={{ fontSize: 17 }}>{money(stats(dayOps).net, s, { signed: true })}</div></div>
            <div><div className="field-label">WIN / LOSS / DRAW</div><div className="mono mt-8" style={{ fontSize: 17 }}>{stats(dayOps).wins} / {stats(dayOps).losses} / {stats(dayOps).draws}</div></div>
            <div><div className="field-label">Saldo ao final</div><div className="mono mt-8" style={{ fontSize: 17 }}>{selected ? money(selected.balance, s) : money(ops.filter((o) => o.date <= dayOpen).reduce((a, o) => a + o.profit, s.initialBalance), s)}</div></div>
            <div><div className="field-label">Meta</div><div className="mono mt-8" style={{ fontSize: 17 }}>{selected ? money(selected.goal, s) : money(resolveValue(s.dailyGoal, s.initialBalance), s)}</div></div>
          </div>
          {data.dayNotes[dayOpen] && <div className="notice mb-14"><div><b>Anotação do dia:</b> {data.dayNotes[dayOpen]}</div></div>}
          {dayOps.length === 0
            ? <div className="empty-state"><p>Este dia não possui operações registradas.</p></div>
            : <OperationTable ops={sortOps(dayOps).reverse()} compact />}
        </Modal>
      )}

      {noteEdit && dayOpen && (
        <Modal title={`Anotação de ${formatDate(dayOpen, s)}`} narrow onClose={() => setNoteEdit(false)}
          footer={<><button className="btn" onClick={() => setNoteEdit(false)}>Cancelar</button>
            <button className="btn primary" onClick={() => { setData((d) => ({ ...d, dayNotes: { ...d.dayNotes, [dayOpen]: noteText } })); setNoteEdit(false); }}>Salvar anotação</button></>}>
          <div className="field"><label className="field-label">Observações gerais do dia</label>
            <textarea className="textarea" value={noteText} onChange={(e) => setNoteText(e.target.value)} placeholder="Resumo do dia, condições de mercado, lições..." />
          </div>
        </Modal>
      )}
    </>
  );
}
