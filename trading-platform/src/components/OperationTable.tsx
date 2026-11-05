import React, { useState } from 'react';
import { Pencil, Copy, Trash2, Image as ImageIcon } from 'lucide-react';
import { useStore } from '../state/store';
import { Modal, ConfirmDialog, ResultBadge } from './ui';
import { money, formatDate } from '../lib/format';
import { OP_COLUMNS } from '../lib/defaults';
import type { Operation } from '../types';

export function OperationTable({ ops, compact = false, maxHeight }: { ops: Operation[]; compact?: boolean; maxHeight?: number }) {
  const { data, openOpEditor, saveOp, deleteOp, duplicateOp, toast } = useStore();
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [image, setImage] = useState<string | null>(null);
  const columns = data.settings.visibleColumns.length ? data.settings.visibleColumns : OP_COLUMNS.map((c) => c.id);
  const col = (id: string) => columns.includes(id);
  const s = data.settings;

  const cell = (o: Operation, id: string): React.ReactNode => {
    switch (id) {
      case 'date': return <><span className="strong">{formatDate(o.date, s, false)}</span> <span className="muted tiny mono">{o.time}</span></>;
      case 'asset': return <span className="strong">{o.asset || '—'}</span>;
      case 'market': return <span className="tag">{o.market}</span>;
      case 'direction': return <span className={o.direction === 'CALL' ? 'value-pos' : 'value-neg'}>{o.direction}</span>;
      case 'strategy': return data.strategies.find((st) => st.id === o.strategyId)?.name || <span className="muted">—</span>;
      case 'timeframe': return o.timeframe || '—';
      case 'expiry': return o.expiry || '—';
      case 'entry': return <span className="mono">{money(o.entry, s)}</span>;
      case 'payout': return <span className="mono">{o.payout.toFixed(0)}%</span>;
      case 'result': return <><ResultBadge result={o.result} />{o.demo && <span className="badge badge-demo" style={{ marginLeft: 4 }}>SIM</span>}{o.profitEdited && <span className="badge badge-warn" style={{ marginLeft: 4 }} title="Valor financeiro corrigido manualmente">CORRIGIDO</span>}</>;
      case 'profit': return <span className={`mono strong ${o.profit > 0 ? 'value-pos' : o.profit < 0 ? 'value-neg' : ''}`}>{money(o.profit, s, { signed: true })}</span>;
      case 'notes': return <span className="muted" style={{ maxWidth: 190, display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={o.notes}>{o.notes || '—'}</span>;
      case 'screenshot': return o.screenshot ? <img className="screenshot-thumb" src={o.screenshot} alt="screenshot" onClick={() => setImage(o.screenshot!)} /> : <span className="muted">—</span>;
      case 'series': return o.seriesId || <span className="muted">—</span>;
      case 'actions': return (
        <div className="row" style={{ gap: 4, justifyContent: 'flex-end' }}>
          <button className="btn xs" title="Editar" onClick={() => openOpEditor(o)}><Pencil size={11} /></button>
          <button className="btn xs" title="Duplicar" onClick={() => duplicateOp(o)}><Copy size={11} /></button>
          <button className="btn xs danger" title="Excluir" onClick={() => setDeleteId(o.id)}><Trash2 size={11} /></button>
        </div>
      );
      default: return null;
    }
  };
  const isNum = (id: string) => ['entry', 'payout', 'profit'].includes(id);

  return (
    <>
      <div className="table-wrap">
        <div className="table-scroll" style={maxHeight ? { maxHeight } : undefined}>
          <table className="table">
            <thead><tr>{OP_COLUMNS.filter((c) => col(c.id)).map((c) => (
              <th key={c.id} className={isNum(c.id) || c.id === 'actions' ? 'num' : ''}>{c.label}</th>
            ))}</tr></thead>
            <tbody>
              {ops.length === 0 && <tr><td colSpan={Math.max(1, columns.length)} className="center muted" style={{ padding: compact ? 18 : 34 }}>
                <ImageIcon size={18} style={{ verticalAlign: 'middle', marginRight: 8, opacity: .5 }} />Nenhuma operação encontrada
              </td></tr>}
              {ops.map((o) => (
                <tr key={o.id} style={{ cursor: 'pointer' }} onDoubleClick={() => openOpEditor(o)}>
                  {OP_COLUMNS.filter((c) => col(c.id)).map((c) => (
                    <td key={c.id} className={`${isNum(c.id) ? 'num' : ''} ${c.id === 'actions' ? 'right' : ''}`}>{cell(o, c.id)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {deleteId && <ConfirmDialog title="Excluir operação" danger confirmLabel="Excluir definitivamente"
        text={<>Tem certeza de que deseja excluir esta operação? O saldo, as metas, as sequências e todos os relatórios serão recalculados automaticamente. Esta ação não pode ser desfeita (use um backup para restaurar).</>}
        onClose={() => setDeleteId(null)}
        onConfirm={() => { deleteOp(deleteId); setDeleteId(null); toast('Operação excluída e cálculos recalculados.', 'info'); }} />}

      {image && <Modal title="Screenshot da operação" onClose={() => setImage(null)} wide>
        <img className="img-preview" src={image} alt="Screenshot da operação" />
      </Modal>}
    </>
  );
}
