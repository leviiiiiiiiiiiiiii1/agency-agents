import React, { useMemo, useState } from 'react';
import { AlertTriangle, Trash2, CalendarClock, Copy, Undo2, FileSpreadsheet, ArrowRight, ShieldAlert, Check } from 'lucide-react';
import { useStore } from '../state/store';
import { Modal, Notice, Field } from '../components/ui';
import { money, formatDate } from '../lib/format';
import { stats, sortOps } from '../lib/calc';
import { opsOnDate, moveDay, copyDayTo, deleteDay, recentDates } from '../lib/dayTools';
import type { OpFilter } from '../lib/dayTools';
import type { Operation } from '../types';

type Mode = 'move' | 'delete' | 'copy';

/**
 * Gerenciador de histórico por dia.
 * Resolve erros de importação (dia errado), restauração de um dia específico
 * e limpeza seletiva — sempre com prévia e confirmação explícita.
 */
export function DayToolsModal({ initialDate, onClose }: { initialDate: string; onClose: () => void }) {
  const { data, mutateWithUndo, refDate, setRefDate, toast, openOpEditor } = useStore();
  const s = data.settings;
  const [date, setDate] = useState(initialDate || refDate);
  const [mode, setMode] = useState<Mode>('move');
  const [target, setTarget] = useState(refDate);
  const [onlyImported, setOnlyImported] = useState(false);
  const [includeDemo, setIncludeDemo] = useState(true);
  const [confirming, setConfirming] = useState(false);

  const filter: OpFilter = { onlyImported, includeDemo };
  const dayOps = useMemo(() => sortOps(opsOnDate(data, date, filter)), [data, date, onlyImported, includeDemo]);
  const allOnDay = useMemo(() => opsOnDate(data, date, { includeDemo: true }), [data, date]);
  const st = stats(dayOps);
  const importedCount = allOnDay.filter((o) => o.source === 'import').length;

  const suggestions = useMemo(() => {
    const list = recentDates(14, refDate);
    return [...new Set([...list, ...allOnDay.map((o) => o.date)])];
  }, [refDate, allOnDay]);

  const apply = () => {
    if (!dayOps.length) return;
    const res = mode === 'delete'
      ? deleteDay(data, date, filter)
      : mode === 'move'
        ? moveDay(data, date, target, filter)
        : copyDayTo(data, date, target, filter);
    if (res.removed === 0) { toast(res.message, 'error'); return; }
    const actionLabel = mode === 'delete' ? 'Exclusão' : mode === 'move' ? 'Movimentação' : 'Cópia';
    mutateWithUndo(`${actionLabel.toLowerCase()} de ${res.removed} operação(ões) em ${formatDate(date, s, false)}`, () => res.data);
    toast(`${res.message} Use “Desfazer última ação” para reverter.`, 'info');
    onClose();
  };

  const label = mode === 'move' ? 'Mover operações' : mode === 'copy' ? 'Copiar para outro dia' : 'Excluir operações';

  return (
    <Modal title="Gerenciar histórico do dia" sub="Corrija uma importação feita na data errada, mova, copie ou exclua apenas um dia"
      wide onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>Cancelar</button>
        <button className={`btn ${mode === 'delete' || confirming ? 'danger' : 'primary'}`} disabled={!dayOps.length}
          onClick={() => (confirming ? apply() : setConfirming(true))}>
          {mode === 'delete' ? <Trash2 size={14} /> : mode === 'move' ? <CalendarClock size={14} /> : <Copy size={14} />}
          {confirming ? `Confirmar: ${label.toLowerCase()}` : label}
        </button>
      </>}>

      <div className="grid grid-2" style={{ alignItems: 'start' }}>
        <div>
          <Field label="Dia do histórico" hint="Dia em que as operações foram lançadas (o dia “errado”, se for o caso)">
            <input type="date" className="input" value={date} onChange={(e) => { setDate(e.target.value); setConfirming(false); }} />
          </Field>
          <div className="row wrap mt-8" style={{ gap: 6 }}>
            {suggestions.slice(0, 6).map((d) => (
              <button key={d} className={`btn xs ${d === date ? 'primary' : ''}`} onClick={() => { setDate(d); setConfirming(false); }}>{formatDate(d, s, false)}</button>
            ))}
          </div>
        </div>
        <div>
          <div className="card" style={{ padding: 12 }}>
            <div className="tiny muted">Operações neste dia</div>
            <div className="mono" style={{ fontSize: 22, fontWeight: 700 }}>{dayOps.length}</div>
            <div className="tiny muted mt-8">
              Importadas: <b>{importedCount}</b> · Resultado:{' '}
              <b className={st.net >= 0 ? 'value-pos' : 'value-neg'}>{money(st.net, s, { signed: true })}</b>
            </div>
            <div className="tiny muted mt-8">WIN {st.wins} · LOSS {st.losses} · DRAW {st.draws}</div>
          </div>
        </div>
      </div>

      <div className="section-title mt-14">Ação</div>
      <div className="row wrap" style={{ gap: 8 }}>
        <button className={`btn sm ${mode === 'move' ? 'primary' : ''}`} onClick={() => { setMode('move'); setConfirming(false); }}><CalendarClock size={13} /> Mover para outro dia</button>
        <button className={`btn sm ${mode === 'delete' ? 'primary' : ''}`} onClick={() => { setMode('delete'); setConfirming(false); }}><Trash2 size={13} /> Excluir do dia</button>
        <button className={`btn sm ${mode === 'copy' ? 'primary' : ''}`} onClick={() => { setMode('copy'); setConfirming(false); }}><Copy size={13} /> Copiar para outro dia</button>
      </div>

      {(mode === 'move' || mode === 'copy') && (
        <div className="mt-14">
          <Field label={mode === 'move' ? 'Mover para a data correta' : 'Copiar para a data'} hint="As operações mantêm horário, ativo, entrada, payout, resultado e observações">
            <input type="date" className="input" value={target} onChange={(e) => { setTarget(e.target.value); setConfirming(false); }} />
          </Field>
          <div className="row wrap mt-8" style={{ gap: 6 }}>
            <button className="btn xs" onClick={() => setTarget(refDate)}>Hoje ({formatDate(refDate, s, false)})</button>
            {suggestions.filter((d) => d !== date).slice(0, 4).map((d) => (
              <button key={d} className={`btn xs ${d === target ? 'primary' : ''}`} onClick={() => { setTarget(d); setConfirming(false); }}>{formatDate(d, s, false)}</button>
            ))}
          </div>
        </div>
      )}

      <div className="section-title mt-14">Escopo</div>
      <label className="check-row"><input type="checkbox" checked={onlyImported} onChange={(e) => { setOnlyImported(e.target.checked); setConfirming(false); }} /><span>Somente operações <b>importadas</b> de planilha ({importedCount} neste dia)</span></label>
      <label className="check-row mt-8"><input type="checkbox" checked={includeDemo} onChange={(e) => { setIncludeDemo(e.target.checked); setConfirming(false); }} /><span>Incluir registros de simulação</span></label>

      {confirming && (
        <div className="mt-14">
          <Notice kind={mode === 'delete' ? 'danger' : 'warn'}>
            <AlertTriangle size={14} /> <b>{dayOps.length} operação(ões)</b> de <b>{formatDate(date, s)}</b>{' '}
            {mode === 'move' ? <>serão movidas para <b>{formatDate(target, s)}</b>.</> : mode === 'copy' ? <>serão copiadas para <b>{formatDate(target, s)}</b>.</> : <>serão <b>excluídas</b>.</>}{' '}
            Você poderá desfazer com um clique. {(mode === 'delete' || mode === 'move') && 'Faça um backup antes se quiser guardar o estado atual.'}
          </Notice>
        </div>
      )}

      {dayOps.length > 0 && (
        <>
          <div className="section-title mt-14">Prévia ({dayOps.length})</div>
          <div className="table-wrap" style={{ maxHeight: 240 }}>
            <table className="table">
              <thead><tr><th>Hora</th><th>Ativo</th><th>Entrada</th><th>Payout</th><th>Resultado</th><th>Lucro</th><th>Origem</th></tr></thead>
              <tbody>
                {dayOps.slice(0, 60).map((o: Operation) => (
                  <tr key={o.id}>
                    <td className="mono">{o.time}</td>
                    <td>{o.asset || '—'}</td>
                    <td className="mono">{money(o.entry, s)}</td>
                    <td className="mono">{o.payout}%</td>
                    <td><span className={`badge ${o.result === 'WIN' ? 'badge-win' : o.result === 'LOSS' ? 'badge-loss' : 'badge-draw'}`}>{o.result}</span></td>
                    <td className={`mono ${o.profit >= 0 ? 'value-pos' : 'value-neg'}`}>{money(o.profit, s, { signed: true })}</td>
                    <td>{o.source === 'import' ? <span className="badge badge-demo"><FileSpreadsheet size={10} /> IMPORTADO</span> : <span className="tag">manual</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {dayOps.length > 60 && <div className="tiny muted mt-8">Mostrando as 60 primeiras de {dayOps.length}.</div>}
        </>
      )}

      {!dayOps.length && (
        <div className="mt-14">
          <Notice kind="warn">Nenhuma operação encontrada nesse dia com o escopo selecionado. Ajuste o dia ou desmarque “somente importadas”.</Notice>
        </div>
      )}

      <div className="row wrap mt-14" style={{ gap: 8 }}>
        <button className="btn sm" onClick={() => { setRefDate(date); openOpEditor('new'); onClose(); }}><Check size={13} /> Registrar operação manual em {formatDate(date, s, false)}</button>
        <span className="tiny muted row" style={{ gap: 4 }}><ShieldAlert size={12} /> Exclusões e movimentações ficam registradas no histórico de ações (veja Histórico & dados → Desfazer última ação).</span>
      </div>
    </Modal>
  );
}

export function UndoActionButton() {
  const { undo, undoInfo } = useStore();
  if (!undoInfo) return null;
  return (
    <button className="btn sm" onClick={undo} title={undoInfo.label}>
      <Undo2 size={13} /> Desfazer: {undoInfo.label}
    </button>
  );
}
