import React, { useMemo, useState } from 'react';
import { Plus, Pencil, Trash2, Power, Trophy, Clock, Layers3, Star, BarChart3 } from 'lucide-react';
import { useStore } from '../state/store';
import { Card, CardHead, PageHeader, Modal, Field, ConfirmDialog, EmptyState, Notice, StatCard, Toggle } from '../components/ui';
import { stats, byHour, byStrategy } from '../lib/calc';
import { money, pct } from '../lib/format';
import { uid } from '../lib/defaults';
import type { Strategy } from '../types';

const COLORS = ['#21d4a8', '#60a5fa', '#f59e0b', '#a78bfa', '#f472b6', '#34d399', '#fb7185'];

const blank = (): Strategy => ({
  id: uid(), name: '', description: '', config: '', assets: '', timeframe: 'M1',
  expiry: '1m', active: true, color: COLORS[0], createdAt: Date.now(),
});

export function EstrategiasPage() {
  const { data, ops, saveStrategy, deleteStrategy, toast } = useStore();
  const s = data.settings;
  const [editing, setEditing] = useState<Strategy | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

  const enriched = useMemo(() => data.strategies.map((strategy) => {
    const list = ops.filter((o) => o.strategyId === strategy.id);
    const st = stats(list);
    const hours = byHour(list).sort((a, b) => b.net - a.net);
    const bestHour = hours[0] ? `${hours[0].label} (${money(hours[0].net, s, { signed: true })})` : '—';
    return { strategy, st, bestHour };
  }), [data.strategies, ops, s]);

  const ranking = [...enriched].filter((e) => e.st.count > 0).sort((a, b) => b.st.net - a.st.net || b.st.winRate - a.st.winRate);
  const allStrategyGroups = byStrategy(ops, data.strategies);

  return (
    <>
      <PageHeader title="Estratégias" description="Cadastre suas estratégias e acompanhe o desempenho real de cada uma. O ranking é calculado somente a partir de operações efetivamente registradas."
        actions={<button className="btn primary" onClick={() => setEditing(blank())}><Plus size={15} /> Nova estratégia</button>} />

      <div className="grid grid-4 mb-14">
        <StatCard label="Estratégias cadastradas" icon={<Layers3 size={14} />} value={data.strategies.length} foot={`${data.strategies.filter((x) => x.active).length} ativas`} />
        <StatCard label="Com histórico real" value={ranking.length} foot="Com pelo menos 1 operação" />
        <StatCard label="Melhor resultado" icon={<Trophy size={14} />} value={ranking[0] ? money(ranking[0].st.net, s, { signed: true }) : '—'} tone={ranking[0]?.st.net >= 0 ? 'pos' : 'neg'} foot={ranking[0]?.strategy.name || 'Sem dados'} />
        <StatCard label="Operações sem estratégia" value={allStrategyGroups.find((g) => g.key === 'none')?.count || 0} foot="Vincule-as para comparar desempenho" />
      </div>

      {data.strategies.length === 0 ? (
        <Card><EmptyState icon={<Layers3 size={34} />} title="Nenhuma estratégia cadastrada"
          text="Crie estratégias para classificar suas operações, comparar resultados e identificar quais setups performam melhor no seu histórico real. Nenhuma estratégia de exemplo é criada automaticamente."
          action={<button className="btn primary" onClick={() => setEditing(blank())}><Plus size={15} /> Cadastrar estratégia</button>} /></Card>
      ) : (
        <div className="grid grid-3">
          {enriched.map(({ strategy, st, bestHour }) => (
            <Card key={strategy.id} style={{ borderTop: `3px solid ${strategy.color}` }}>
              <div className="row between mb-8">
                <div className="row" style={{ gap: 8 }}>
                  <span style={{ width: 10, height: 10, borderRadius: '50%', background: strategy.color }} />
                  <b style={{ fontSize: 14 }}>{strategy.name}</b>
                </div>
                <span className={`badge ${strategy.active ? 'badge-win' : 'badge-draw'}`}>{strategy.active ? 'Ativa' : 'Inativa'}</span>
              </div>
              {strategy.description && <div className="small muted mb-14" style={{ lineHeight: 1.55 }}>{strategy.description}</div>}
              <div className="pill-list mb-14">
                <span className="pill">TF <strong>{strategy.timeframe || '—'}</strong></span>
                <span className="pill">Exp. <strong>{strategy.expiry || '—'}</strong></span>
                <span className="pill">Payout <strong>{pct(st.avgPayout, 0)}</strong></span>
              </div>
              {strategy.assets && <div className="tiny muted mb-14">Ativos: {strategy.assets}</div>}
              {strategy.config && <div className="tiny muted mb-14" style={{ whiteSpace: 'pre-wrap' }}>Config: {strategy.config}</div>}
              <div className="divider" />
              <div className="grid grid-2" style={{ gap: 8 }}>
                <div><div className="field-label">Operações</div><div className="mono" style={{ fontSize: 17 }}>{st.count}</div></div>
                <div><div className="field-label">Assertividade</div><div className="mono" style={{ fontSize: 17 }}>{st.count ? pct(st.winRate, 1) : '—'}</div></div>
                <div><div className="field-label">W / L / D</div><div className="mono" style={{ fontSize: 14 }}>{st.wins} / {st.losses} / {st.draws}</div></div>
                <div><div className="field-label">Lucro acumulado</div><div className={`mono ${st.net >= 0 ? 'value-pos' : 'value-neg'}`} style={{ fontSize: 16 }}>{st.count ? money(st.net, s, { signed: true }) : '—'}</div></div>
              </div>
              <div className="metric-line mt-8"><span className="label"><Clock size={12} style={{ verticalAlign: 'middle' }} /> Melhor horário</span><span className="val" style={{ fontSize: 11 }}>{bestHour}</span></div>
              <div className="btn-row mt-14">
                <button className="btn xs" onClick={() => setEditing({ ...strategy })}><Pencil size={12} /> Editar</button>
                <button className="btn xs" onClick={() => { saveStrategy({ ...strategy, active: !strategy.active }); toast(strategy.active ? 'Estratégia desativada.' : 'Estratégia ativada.', 'info'); }}><Power size={12} /> {strategy.active ? 'Desativar' : 'Ativar'}</button>
                <button className="btn xs danger" onClick={() => setDeleting(strategy.id)}><Trash2 size={12} /> Excluir</button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <div className="section-title">Ranking por resultado real</div>
      <Card>
        <CardHead title="Melhores estratégias" sub="Ordenado por lucro acumulado, com desempate por assertividade" right={<Star size={15} className="value-accent" />} />
        {ranking.length === 0 ? <div className="muted small">Ainda não há operações vinculadas a estratégias. O ranking permanece vazio até existir histórico real.</div> :
          ranking.map((e, i) => (
            <div className="rank-row" key={e.strategy.id}>
              <span className={`rank-num ${i === 0 ? 'top' : ''}`}>#{i + 1}</span>
              <span style={{ width: 9, height: 9, background: e.strategy.color, borderRadius: '50%' }} />
              <div style={{ flex: 1 }}><div className="strong">{e.strategy.name}</div>
                <div className="tiny muted">{e.st.count} ops · {e.st.wins}W / {e.st.losses}L · {pct(e.st.winRate, 1)} · payout {pct(e.st.avgPayout, 0)} · melhor {e.bestHour}</div></div>
              <b className={`mono ${e.st.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(e.st.net, s, { signed: true })}</b>
            </div>
          ))}
        <div className="mt-14"><Notice><BarChart3 size={14} /> Este ranking é descritivo: mostra o que aconteceu no histórico registrado. Não é uma recomendação nem uma previsão de desempenho futuro.</Notice></div>
      </Card>

      {editing && (
        <Modal title={data.strategies.some((x) => x.id === editing.id) ? 'Editar estratégia' : 'Nova estratégia'}
          sub="Campos de cadastro e configuração da estratégia" onClose={() => setEditing(null)}
          footer={<><button className="btn" onClick={() => setEditing(null)}>Cancelar</button>
            <button className="btn primary" disabled={!editing.name.trim()} onClick={() => {
              saveStrategy({ ...editing, name: editing.name.trim() });
              toast('Estratégia salva.'); setEditing(null);
            }}>Salvar estratégia</button></>}>
          <div className="form-grid">
            <Field label="Nome *"><input className="input" value={editing.name} placeholder="Ex.: Rejeição em suporte M5" onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></Field>
            <Field label="Timeframe"><input className="input" value={editing.timeframe} onChange={(e) => setEditing({ ...editing, timeframe: e.target.value })} /></Field>
            <Field label="Expiração"><input className="input" value={editing.expiry} onChange={(e) => setEditing({ ...editing, expiry: e.target.value })} /></Field>
            <Field label="Ativos recomendados" hint="Separe por vírgula"><input className="input" value={editing.assets} placeholder="EUR/USD, GBP/USD" onChange={(e) => setEditing({ ...editing, assets: e.target.value })} /></Field>
            <Field label="Descrição" full><textarea className="textarea" value={editing.description} onChange={(e) => setEditing({ ...editing, description: e.target.value })} placeholder="Explique a lógica da estratégia..." /></Field>
            <Field label="Configuração / regras" full><textarea className="textarea" value={editing.config} onChange={(e) => setEditing({ ...editing, config: e.target.value })} placeholder="Indicadores, parâmetros, gatilhos, filtros..." /></Field>
            <Field label="Cor de identificação">
              <div className="btn-row">{COLORS.map((c) => (
                <button key={c} className="icon-btn" style={{ background: c, border: editing.color === c ? '2px solid var(--text)' : '2px solid transparent', width: 28, height: 28 }}
                  onClick={() => setEditing({ ...editing, color: c })} aria-label={`Cor ${c}`} />
              ))}</div>
            </Field>
            <div className="field"><label className="field-label">Status</label><div style={{ paddingTop: 6 }}><Toggle checked={editing.active} onChange={(v) => setEditing({ ...editing, active: v })} label="Estratégia ativa (disponível no formulário de operações)" /></div></div>
          </div>
          <div className="divider" />
          <div className="small muted">Total de operações, WIN/LOSS/DRAW, assertividade, lucro acumulado, melhor horário e payout médio são <b>calculados automaticamente</b> a partir do histórico — não são campos editáveis.</div>
        </Modal>
      )}

      {deleting && <ConfirmDialog title="Excluir estratégia" danger confirmLabel="Excluir"
        text={<>A estratégia será removida. As operações vinculadas a ela <b>não serão excluídas</b>: passarão a constar como "Sem estratégia", preservando todo o histórico financeiro.</>}
        onClose={() => setDeleting(null)} onConfirm={() => { deleteStrategy(deleting); setDeleting(null); toast('Estratégia excluída. Histórico preservado.', 'info'); }} />}
    </>
  );
}
