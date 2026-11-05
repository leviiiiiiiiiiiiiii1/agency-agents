import React, { useEffect, useMemo, useState } from 'react';
import { ImagePlus, Trash2, Wand2, AlertTriangle, Lock, Unlock } from 'lucide-react';
import { useStore } from '../state/store';
import { Modal, Field, Notice, ResultBadge } from './ui';
import { calcProfit, todayISO, uid } from '../lib/defaults';
import { money, formatDate } from '../lib/format';
import { validateEntry, suggestEntry } from '../lib/calc';
import { compressImage } from '../lib/storage';
import type { Operation, TradeResult } from '../types';

const MARKETS = ['Normal', 'OTC'] as const;
const TIMEFRAMES = ['M1', 'M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'Ticks'];
const EXPIRIES = ['30s', '1m', '2m', '3m', '5m', '10m', '15m', '30m', '1h', 'Fim do dia'];

export function blankOperation(data: ReturnType<typeof useStore>['data'], date = todayISO()): Operation {
  const last = [...data.operations].sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))[0];
  return {
    id: uid(), date, time: new Date().toTimeString().slice(0, 5),
    asset: last?.asset || '', market: last?.market || 'Normal', direction: 'CALL',
    strategyId: last?.strategyId || '', timeframe: last?.timeframe || 'M1',
    expiry: last?.expiry || '1m', entry: Number(data.settings.baseEntry) || 0,
    payout: 85, result: 'WIN', profit: 0, notes: '',
    seriesId: last?.seriesId || '', demo: false, createdAt: Date.now(),
  };
}

export function OperationEditor() {
  const store = useStore();
  const { data, ops: visibleOps, allOps, opEditor, closeOpEditor, saveOp, toast } = store;
  const [form, setForm] = useState<Operation | null>(null);
  const [confirmOverride, setConfirmOverride] = useState(false);
  const [editProfit, setEditProfit] = useState(false);

  useEffect(() => {
    if (opEditor === 'new') {
      const b = blankOperation(data, store.refDate);
      const suggestion = suggestEntry(data, visibleOps, store.refDate);
      setForm({ ...b, entry: suggestion.value });
      setConfirmOverride(false);
      setEditProfit(false);
    } else if (opEditor) {
      setForm({ ...opEditor });
      setConfirmOverride(false);
      setEditProfit(!!opEditor.profitEdited);
    } else {
      setForm(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opEditor]);

  const editing = opEditor !== 'new';
  const show = (k: string) => data.settings.opFields[k] !== false;
  const set = <K extends keyof Operation>(k: K, v: Operation[K]) => setForm((f) => f ? { ...f, [k]: v } : f);

  const computedProfit = useMemo(() => form ? calcProfit(Number(form.entry) || 0, Number(form.payout) || 0, form.result) : 0, [form?.entry, form?.payout, form?.result]);
  const displayProfit = form ? (editProfit || form.profitEdited ? form.profit : computedProfit) : 0;

  const limits = useMemo(() => {
    if (!form) return null;
    const other = visibleOps.filter((o) => o.id !== form.id);
    return validateEntry(data, other, Number(form.entry) || 0, form.date);
  }, [form?.entry, form?.date, form?.id, data, visibleOps]);

  if (!form || !opEditor) return null;

  const assetOptions = [...new Set(allOps.map((o) => o.asset).filter(Boolean))].sort();
  const needsConfirmation = !!data.settings.requireLimitConfirmation && limits && !limits.ok && !confirmOverride;
  const suggestion = suggestEntry(data, visibleOps.filter((o) => o.id !== form.id), form.date);

  const submit = () => {
    if (!form.entry || form.entry < 0) { toast('Informe um valor de entrada válido.', 'error'); return; }
    if (needsConfirmation) { toast('Confirme explicitamente o uso acima dos limites.', 'error'); return; }
    const op: Operation = {
      ...form,
      entry: Number(form.entry) || 0,
      payout: Number(form.payout) || 0,
      profit: editProfit || form.profitEdited ? Number(form.profit) || 0 : computedProfit,
      profitEdited: editProfit || form.profitEdited,
      createdAt: form.createdAt || Date.now(),
    };
    saveOp(op);
    toast(editing ? 'Operação atualizada. Todos os cálculos foram recalculados.' : 'Operação registrada com sucesso.');
    closeOpEditor();
  };

  return (
    <Modal
      title={editing ? 'Editar operação' : 'Registrar nova operação'}
      sub={editing ? `Registro de ${formatDate(form.date, data.settings)} · ID ${form.id.slice(0, 8)}` : 'Preencha os campos configuráveis. O resultado financeiro é calculado automaticamente.'}
      wide
      onClose={closeOpEditor}
      footer={<>
        {editing && <button className="btn danger" style={{ marginRight: 'auto' }} onClick={() => {
          const copy = { ...form, id: uid(), createdAt: Date.now(), updatedAt: undefined, date: todayISO() };
          saveOp(copy);
          toast('Cópia criada com os mesmos dados.');
          closeOpEditor();
        }}>Duplicar</button>}
        <button className="btn" onClick={closeOpEditor}>Cancelar</button>
        <button className="btn primary" onClick={submit}>{editing ? 'Salvar alterações' : 'Registrar operação'}</button>
      </>}
    >
      <div className="form-grid cols-4">
        <Field label="Data"><input type="date" className="input" value={form.date} onChange={(e) => set('date', e.target.value)} /></Field>
        <Field label="Horário"><input type="time" className="input" value={form.time} onChange={(e) => set('time', e.target.value)} /></Field>
        <Field label="Ativo negociado" hint="Livre: use qualquer ativo">
          <input className="input" list="asset-list" placeholder="Ex.: EUR/USD" value={form.asset} onChange={(e) => set('asset', e.target.value)} />
          <datalist id="asset-list">{assetOptions.map((a) => <option key={a} value={a} />)}</datalist>
        </Field>
        {show('market') && <Field label="Tipo de mercado">
          <select className="select" value={form.market} onChange={(e) => set('market', e.target.value as Operation['market'])}>
            {MARKETS.map((m) => <option key={m}>{m}</option>)}
          </select>
        </Field>}
        {show('direction') && <Field label="Direção">
          <div className="mode-toggle">
            {(['CALL', 'PUT'] as const).map((d) => <button type="button" key={d} className={form.direction === d ? 'on' : ''} onClick={() => set('direction', d)}>{d}</button>)}
          </div>
        </Field>}
        {show('strategy') && <Field label="Estratégia">
          <select className="select" value={form.strategyId} onChange={(e) => set('strategyId', e.target.value)}>
            <option value="">Sem estratégia</option>
            {data.strategies.filter((st) => st.active).map((st) => <option key={st.id} value={st.id}>{st.name}</option>)}
            {data.strategies.filter((st) => !st.active && st.id === form.strategyId).map((st) => <option key={st.id} value={st.id}>{st.name} (inativa)</option>)}
          </select>
        </Field>}
        {show('timeframe') && <Field label="Timeframe">
          <input className="input" list="tf-list" value={form.timeframe} onChange={(e) => set('timeframe', e.target.value)} />
          <datalist id="tf-list">{TIMEFRAMES.map((t) => <option key={t} value={t} />)}</datalist>
        </Field>}
        {show('expiry') && <Field label="Tempo de expiração">
          <input className="input" list="exp-list" value={form.expiry} onChange={(e) => set('expiry', e.target.value)} />
          <datalist id="exp-list">{EXPIRIES.map((t) => <option key={t} value={t} />)}</datalist>
        </Field>}
      </div>

      <div className="divider" />

      <div className="form-grid cols-4">
        <Field label="Valor da entrada" hint={`Sugerido: ${money(suggestion.value, data.settings)} (${data.settings.activeManagement})`}>
          <div className="inline-value">
            <input className="input mono" type="number" step="0.01" min="0" value={form.entry} onChange={(e) => set('entry', Number(e.target.value))} />
            <button className="icon-btn" title="Usar valor sugerido" onClick={() => set('entry', suggestion.value)}><Wand2 size={14} /></button>
          </div>
        </Field>
        <Field label="Payout (%)" hint="Lucro líquido sobre a entrada"><input className="input mono" type="number" step="1" min="0" value={form.payout} onChange={(e) => set('payout', Number(e.target.value))} /></Field>
        <Field label="Resultado">
          <div className="mode-toggle">
            {(['WIN', 'LOSS', 'DRAW'] as TradeResult[]).map((r) => (
              <button type="button" key={r} className={form.result === r ? 'on' : ''} onClick={() => set('result', r)}>{r}</button>
            ))}
          </div>
        </Field>
        <Field label="Lucro / prejuízo (calculado)">
          <div className="inline-value">
            <input className={`input mono ${displayProfit >= 0 ? 'value-pos' : 'value-neg'}`} type="number" step="0.01"
              value={displayProfit} disabled={!editProfit && !form.profitEdited}
              onChange={(e) => set('profit', Number(e.target.value))} />
            <label className="icon-btn" title="Corrigir valor manualmente">
              {editProfit || form.profitEdited ? <Unlock size={14} /> : <Lock size={14} />}
              <input type="checkbox" style={{ display: 'none' }} checked={editProfit || !!form.profitEdited}
                onChange={(e) => {
                  setEditProfit(e.target.checked);
                  if (!e.target.checked) set('profitEdited', false);
                  else set('profitEdited', true);
                  if (!e.target.checked) set('profit', computedProfit);
                }} />
            </label>
          </div>
        </Field>
      </div>

      <div className="row mt-8" style={{ gap: 14, flexWrap: 'wrap' }}>
        <span className="small muted">Cálculo:</span>
        <ResultBadge result={form.result} />
        <span className="small mono">{money(form.entry || 0, data.settings)} × {form.payout}% → <b className={computedProfit >= 0 ? 'value-pos' : 'value-neg'}>{money(computedProfit, data.settings, { signed: true })}</b></span>
        {(editProfit || form.profitEdited) && <span className="badge badge-warn">Valor corrigido manualmente</span>}
      </div>

      {!suggestion.limits.ok && (
        <div className="mt-14"><Notice kind="warn">Gerenciamento: {suggestion.limits.warnings.filter((w) => w.level === 'block').map((w) => w.label).join(' ')}</Notice></div>
      )}

      <div className="divider" />

      <div className="form-grid cols-2">
        {show('notes') && <Field label="Observações" full>
          <textarea className="textarea" placeholder="Contexto, gatilho, erro de execução, lição aprendida..." value={form.notes} onChange={(e) => set('notes', e.target.value)} />
        </Field>}
        {show('series') && <Field label="Micro série (agrupamento)" hint="Usado na visão Planilha / Séries">
          <input className="input" placeholder="Ex.: série-01" value={form.seriesId || ''} onChange={(e) => set('seriesId', e.target.value)} />
        </Field>}
        {show('screenshot') && <Field label="Screenshot da operação (opcional)">
          <div className="row">
            <label className="btn sm" style={{ cursor: 'pointer' }}>
              <ImagePlus size={14} /> Escolher imagem
              <input type="file" accept="image/*" style={{ display: 'none' }} onChange={async (e) => {
                const f = e.target.files?.[0];
                if (!f) return;
                const url = await compressImage(f);
                set('screenshot', url);
                toast('Screenshot anexada (comprimida para caber no armazenamento local).');
              }} />
            </label>
            {form.screenshot && <>
              <img className="screenshot-thumb" src={form.screenshot} alt="screenshot" onClick={() => window.open(form.screenshot, '_blank')} />
              <button className="btn xs danger" onClick={() => set('screenshot', undefined)}><Trash2 size={12} /></button>
            </>}
          </div>
        </Field>}
      </div>

      <div className="divider" />
      <label className="check-row">
        <input type="checkbox" checked={!!form.demo} onChange={(e) => set('demo', e.target.checked)} />
        <span>Marcar como <b>simulação / exemplo</b> (não entra nos dados reais por padrão)</span>
      </label>
      {form.demo && <div className="mt-8"><Notice kind="warn">Este registro será identificado com o selo SIMULAÇÃO e ficará separado das operações reais em todos os relatórios.</Notice></div>}

      {limits && limits.warnings.length > 0 && (
        <div className="mt-14">
          <Notice kind="danger">
            <div style={{ width: '100%' }}>
              <b style={{ display: 'flex', alignItems: 'center', gap: 6 }}><AlertTriangle size={13} /> Limites de risco configurados</b>
              <ul style={{ margin: '7px 0 0', paddingLeft: 18, lineHeight: 1.8 }}>
                {limits.warnings.map((w, i) => <li key={i}>{w.label}</li>)}
              </ul>
              {data.settings.requireLimitConfirmation && (
                <label className="check-row mt-8">
                  <input type="checkbox" checked={confirmOverride} onChange={(e) => setConfirmOverride(e.target.checked)} />
                  <span>Autorizo explicitamente registrar esta operação acima dos limites definidos.</span>
                </label>
              )}
            </div>
          </Notice>
        </div>
      )}

      <div className="mt-14 tiny muted">Dica: use o botão <b>Nova operação</b> no topo ou pressione os atalhos na barra lateral. Campos e opções são configuráveis em Configurações.</div>
    </Modal>
  );
}
