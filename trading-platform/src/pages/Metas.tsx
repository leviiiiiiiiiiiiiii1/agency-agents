import React, { useMemo, useState } from 'react';
import { Target, Plus, Trash2, TrendingUp, AlertTriangle, CalendarDays, FlaskConical, Pencil } from 'lucide-react';
import { useStore } from '../state/store';
import { Card, CardHead, PageHeader, ModeValueField, NumberField, Field, Notice, Modal, ConfirmDialog, StatCard, Toggle } from '../components/ui';
import { MultiSeriesChart, SimpleBars } from '../components/charts';
import { goalProgress, projectPlan, historicScenarios, currentBalance, stats } from '../lib/calc';
import { money, pct, weekKey, monthKey } from '../lib/format';
import { uid } from '../lib/defaults';
import type { GrowthPlan } from '../types';

const blankPlan = (initial: number): GrowthPlan => ({
  id: uid(), name: 'Novo plano', initial, target: initial * 2,
  dailyRate: 2, days: 30, compound: true, createdAt: Date.now(),
});

export function MetasPage() {
  const { data, setData, ops, refDate, savePlan, deletePlan, toast } = useStore();
  const s = data.settings;
  const g = data.goals;
  const [editingPlan, setEditingPlan] = useState<GrowthPlan | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [selectedPlan, setSelectedPlan] = useState<string | null>(null);

  const setGoal = <K extends keyof typeof g>(k: K, v: typeof g[K]) => setData((d) => ({ ...d, goals: { ...d.goals, [k]: v } }));
  const progress = useMemo(() => goalProgress(data, ops, refDate), [data, ops, refDate]);
  const balance = currentBalance(data, ops);
  const scenarios = historicScenarios(data, ops);
  const st = stats(ops);

  const activePlan = data.plans.find((p) => p.id === selectedPlan) || data.plans[0];
  const projection = useMemo(() => {
    if (!activePlan) return [];
    const base = projectPlan(activePlan);
    const scen = [
      { rate: scenarios.conservative, label: 'Conservador (histórico × 0,5)' },
      { rate: scenarios.realistic, label: 'Realista (expectativa histórica)' },
      { rate: scenarios.aggressive, label: 'Agressivo (histórico × 1,5)' },
    ];
    return base.map((p) => {
      const point: Record<string, number | string> = { label: `D${p.day}`, day: p.day, Plano: p.value };
      if (scenarios.hasData) for (const sc of scen) {
        point[sc.label] = Math.round(activePlan.initial * Math.pow(1 + sc.rate / 100, p.day) * 100) / 100;
      }
      return point;
    });
  }, [activePlan, scenarios]);

  const projSeries = [
    { key: 'Plano', label: `Plano: ${activePlan?.name || ''} (${activePlan?.dailyRate}%/dia)`, color: 'var(--accent)' },
    ...(scenarios.hasData ? [
      { key: 'Conservador (histórico × 0,5)', label: 'Cenário conservador', color: '#60a5fa' },
      { key: 'Realista (expectativa histórica)', label: 'Cenário realista', color: '#f59e0b' },
      { key: 'Agressivo (histórico × 1,5)', label: 'Cenário agressivo', color: '#a78bfa' },
    ] : []),
  ];

  return (
    <>
      <PageHeader title="Metas & planejamento" description="Defina objetivos diários, semanais, mensais e de crescimento, acompanhe o progresso e crie planos de evolução da banca com cenários configuráveis."
        actions={<button className="btn primary" onClick={() => setEditingPlan(blankPlan(balance))}><Plus size={15} /> Novo plano de crescimento</button>} />

      <div className="grid grid-3 mb-14">
        <StatCard label="Saldo atual" icon={<TrendingUp size={14} />} value={money(balance, s)} tone="accent" foot={`Banca inicial: ${money(s.initialBalance, s)}`} />
        <StatCard label="Objetivo financeiro" value={money(g.financialTarget, s)} foot={`${balance > 0 ? pct((balance / g.financialTarget) * 100, 1) : '0%'} alcançado`} />
        <StatCard label="Expectativa histórica" value={money(scenarios.expectancy, s, { signed: true })} tone={scenarios.expectancy >= 0 ? 'pos' : 'neg'} foot={`${scenarios.realistic >= 0 ? '+' : ''}${scenarios.realistic.toFixed(2).replace('.', ',')}% ao dia sobre a banca inicial · ${st.count} ops`} />
      </div>

      <div className="section-title">Progresso dos objetivos</div>
      <div className="grid grid-3 mb-14">
        {progress.map((p) => (
          <Card key={p.id}>
            <div className="row between mb-8"><div className="stat-top">{p.label}</div><span className={`badge ${p.progress >= 100 ? 'badge-accent' : p.progress >= 50 ? 'badge-win' : 'badge-draw'}`}>{pct(p.progress, 0)}</span></div>
            <div className="row between"><span className="stat-value sm">{p.unit === 'ops' ? `${p.current} / ${p.target} ops` : money(p.current, s)}</span><span className="small muted">{p.unit === 'ops' ? '' : `de ${money(p.target, s)}`}</span></div>
            <div className="progress-track mt-14"><div className={`progress-fill ${p.id === 'lossLimit' ? 'neg' : ''} ${p.progress >= 100 ? 'pos' : ''}`} style={{ width: `${Math.min(100, p.progress)}%` }} /></div>
            <div className="stat-foot mt-8">{p.detail}</div>
          </Card>
        ))}
      </div>

      <div className="grid grid-2">
        <Card>
          <CardHead title="Configuração de metas" sub={`Referência: ${refDate} · semana ${weekKey(refDate)} · mês ${monthKey(refDate)}`} />
          <div className="form-grid">
            <ModeValueField label="Meta diária" value={g.daily} onChange={(v) => setGoal('daily', v)} />
            <ModeValueField label="Meta semanal" value={g.weekly} onChange={(v) => setGoal('weekly', v)} />
            <ModeValueField label="Meta mensal" value={g.monthly} onChange={(v) => setGoal('monthly', v)} />
            <ModeValueField label="Meta de crescimento da banca" value={g.growth} onChange={(v) => setGoal('growth', v)} />
            <NumberField label="Objetivo financeiro (saldo alvo)" value={g.financialTarget} onChange={(v) => setGoal('financialTarget', v)} step={100} prefix={s.currencySymbol} />
            <ModeValueField label="Limite de perda" value={g.lossLimit} onChange={(v) => setGoal('lossLimit', v)} />
            <NumberField label="Operações desejadas por dia" value={g.desiredOps} onChange={(v) => setGoal('desiredOps', v)} suffix="ops" />
          </div>
          <div className="divider" />
          <Notice><Target size={14} /> Metas em % usam como base o saldo de abertura do período. A meta diária de planejamento é independente da "Meta diária" de risco configurada em Banca — ambas são personalizáveis.</Notice>
        </Card>

        <Card>
          <CardHead title="Planos de crescimento" sub="Projeções matemáticas configuráveis" right={<FlaskConical size={15} className="muted" />} />
          {data.plans.length === 0 ? <div className="muted small mb-14">Nenhum plano criado. Crie um plano para visualizar projeções de evolução da banca.</div> :
            data.plans.map((p) => {
              const last = projectPlan(p).slice(-1)[0];
              return (
                <div key={p.id} className={`card-order ${activePlan?.id === p.id ? '' : ''}`} style={{ borderColor: activePlan?.id === p.id ? 'var(--accent)' : undefined }}>
                  <span className="name"><b>{p.name}</b><div className="tiny muted">{money(p.initial, s)} → {money(p.target, s)} · {p.dailyRate}%/dia · {p.days} dias · {p.compound ? 'juros compostos' : 'linear'}</div></span>
                  <span className={`tag ${last.value >= p.target ? 'value-pos' : ''}`}>Projeção D{p.days}: {money(last.value, s)}</span>
                  <button className="icon-btn" title="Visualizar" onClick={() => setSelectedPlan(p.id)}><TrendingUp size={13} /></button>
                  <button className="icon-btn" title="Editar" onClick={() => setEditingPlan({ ...p })}><Pencil size={13} /></button>
                  <button className="icon-btn" title="Excluir" onClick={() => setDeleteId(p.id)}><Trash2 size={13} /></button>
                </div>
              );
            })}
          <div className="mt-14"><button className="btn" onClick={() => setEditingPlan(blankPlan(balance))}><Plus size={14} /> Criar plano</button></div>
          <div className="divider" />
          <Notice kind="warn"><b>Projeções são estimativas matemáticas e não garantias de resultados futuros.</b> Operações de trading envolvem risco real de perda. Os cenários "conservador / realista / agressivo" usam apenas a expectativa histórica dos registros e não preveem o mercado.</Notice>
        </Card>
      </div>

      {activePlan && (
        <>
          <div className="section-title">Projeção · {activePlan.name}</div>
          <Card className="mb-14">
            <CardHead title="Evolução projetada da banca" sub={`${activePlan.dailyRate}% ao dia · ${activePlan.days} dias · ${activePlan.compound ? 'capitalização composta' : 'crescimento linear'}`} />
            {projection.length > 0 && <MultiSeriesChart data={projection} series={projSeries} height={320} />}
            <div className="row wrap mt-14 small muted" style={{ gap: 16 }}>
              {projSeries.map((x) => <span key={x.key}><i className="legend-dot" style={{ background: x.color }} />{x.label}</span>)}
              {!scenarios.hasData && <span className="badge badge-draw">Sem histórico: apenas a curva do plano é exibida</span>}
            </div>
          </Card>
          <Card>
            <CardHead title="Marcos da projeção" sub="Valores em intervalos regulares" />
            <SimpleBars data={projectPlan(activePlan).filter((_, i) => i % Math.max(1, Math.ceil(activePlan.days / 12)) === 0 || i === activePlan.days).map((p) => ({ label: `D${p.day}`, value: p.value }))} name="Saldo projetado" height={230} />
          </Card>
        </>
      )}

      {editingPlan && (
        <Modal title={data.plans.some((p) => p.id === editingPlan.id) ? 'Editar plano' : 'Novo plano de crescimento'}
          sub="Todos os parâmetros são configuráveis" onClose={() => setEditingPlan(null)}
          footer={<><button className="btn" onClick={() => setEditingPlan(null)}>Cancelar</button>
            <button className="btn primary" onClick={() => { savePlan(editingPlan); setSelectedPlan(editingPlan.id); setEditingPlan(null); toast('Plano salvo.'); }}>Salvar plano</button></>}>
          <div className="form-grid">
            <Field label="Nome do plano"><input className="input" value={editingPlan.name} onChange={(e) => setEditingPlan({ ...editingPlan, name: e.target.value })} /></Field>
            <NumberField label="Banca inicial do plano" value={editingPlan.initial} onChange={(v) => setEditingPlan({ ...editingPlan, initial: v })} step={100} prefix={s.currencySymbol} />
            <NumberField label="Meta / banca alvo" value={editingPlan.target} onChange={(v) => setEditingPlan({ ...editingPlan, target: v })} step={100} prefix={s.currencySymbol} />
            <NumberField label="Rentabilidade diária estimada" value={editingPlan.dailyRate} onChange={(v) => setEditingPlan({ ...editingPlan, dailyRate: v })} step={0.1} suffix="%" hint="Valor livre — não é uma previsão" />
            <NumberField label="Horizonte (dias)" value={editingPlan.days} onChange={(v) => setEditingPlan({ ...editingPlan, days: Math.max(1, Math.min(730, v)) })} suffix="dias" />
            <div className="field"><label className="field-label">Capitalização</label><div style={{ paddingTop: 6 }}><Toggle checked={editingPlan.compound} onChange={(v) => setEditingPlan({ ...editingPlan, compound: v })} label="Juros compostos (reinvestimento)" /></div></div>
          </div>
          <div className="divider" />
          <Notice kind="warn"><AlertTriangle size={14} /> Projeção meramente matemática: não representa promessa, garantia ou expectativa de resultado futuro. Use apenas para planejamento e controle de risco.</Notice>
        </Modal>
      )}

      {deleteId && <ConfirmDialog title="Excluir plano" danger confirmLabel="Excluir" text="O plano de crescimento será removido. Nenhuma operação real é afetada." onClose={() => setDeleteId(null)} onConfirm={() => { deletePlan(deleteId); setDeleteId(null); toast('Plano excluído.', 'info'); }} />}
    </>
  );
}
