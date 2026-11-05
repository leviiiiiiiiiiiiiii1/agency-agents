import React, { useMemo, useState } from 'react';
import { Plus, Search, Columns3, FlaskConical, RotateCcw, SlidersHorizontal } from 'lucide-react';
import { useStore } from '../state/store';
import { PageHeader, Card, CardHead, Field, Modal, Notice, EmptyState } from '../components/ui';
import { OperationTable } from '../components/OperationTable';
import { sortOps, stats } from '../lib/calc';
import { money, pct } from '../lib/format';
import { OP_COLUMNS } from '../lib/defaults';
import { makeDemoOperations } from '../lib/sample';

export function OperacoesPage() {
  const { data, setData, ops, openOpEditor, loadDemo, setIncludeDemo, toast, setPage } = useStore();
  const s = data.settings;
  const [search, setSearch] = useState('');
  const [result, setResult] = useState('ALL');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [columnsOpen, setColumnsOpen] = useState(false);
  const [fieldsOpen, setFieldsOpen] = useState(false);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sortOps(ops.filter((o) => {
      if (result !== 'ALL' && o.result !== result) return false;
      if (from && o.date < from) return false;
      if (to && o.date > to) return false;
      if (!q) return true;
      const strat = data.strategies.find((st) => st.id === o.strategyId)?.name || '';
      return [o.asset, strat, o.notes, o.timeframe, o.expiry, o.seriesId, o.date, o.market, o.direction]
        .join(' ').toLowerCase().includes(q);
    })).reverse();
  }, [ops, search, result, from, to, data.strategies]);

  const st = stats(filtered);
  const cols = s.visibleColumns;
  const toggleCol = (id: string) => setData((d) => ({
    ...d, settings: {
      ...d.settings,
      visibleColumns: cols.includes(id) ? cols.filter((c) => c !== id) : [...OP_COLUMNS.map((c) => c.id).filter((c) => cols.includes(c) || c === id)],
    },
  }));

  return (
    <>
      <PageHeader title="Registro de operações" description="Cadastre cada operação manualmente. O resultado financeiro é calculado a partir de entrada × payout × resultado, e editar/excluir qualquer registro recalcula todo o histórico."
        actions={<>
          <button className="btn" onClick={() => setFieldsOpen(true)}><SlidersHorizontal size={15} /> Campos do formulário</button>
          <button className="btn" onClick={() => setColumnsOpen(true)}><Columns3 size={15} /> Colunas</button>
          <button className="btn primary" onClick={() => openOpEditor('new')}><Plus size={15} /> Nova operação</button>
        </>} />

      <Card className="pad-0 mb-14">
        <div className="filter-bar">
          <Field label="Pesquisar (ativo, estratégia, data, observação...)"><input className="input" value={search} placeholder="Buscar..." onChange={(e) => setSearch(e.target.value)} /></Field>
          <Field label="Resultado">
            <select className="select" value={result} onChange={(e) => setResult(e.target.value)}>
              <option value="ALL">Todos</option><option value="WIN">WIN</option><option value="LOSS">LOSS</option><option value="DRAW">DRAW</option>
            </select>
          </Field>
          <Field label="De"><input className="input" type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="Até"><input className="input" type="date" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          <div className="field"><label className="field-label">&nbsp;</label>
            <button className="btn" onClick={() => { setSearch(''); setResult('ALL'); setFrom(''); setTo(''); }}><RotateCcw size={14} /> Limpar filtros</button>
          </div>
        </div>
      </Card>

      <div className="grid grid-4 mb-14">
        <div className="card stat-card"><div className="stat-top">Operações no filtro</div><div className="stat-value">{st.count}</div><div className="stat-foot">de {ops.length} no total</div></div>
        <div className="card stat-card"><div className="stat-top">Resultado financeiro</div><div className={`stat-value ${st.net >= 0 ? 'value-pos' : 'value-neg'}`}>{money(st.net, s, { signed: true })}</div><div className="stat-foot">Volume: {money(st.totalEntry, s)}</div></div>
        <div className="card stat-card"><div className="stat-top">Assertividade</div><div className="stat-value">{pct(st.winRate, 1)}</div><div className="stat-foot">{st.wins} WIN · {st.losses} LOSS · {st.draws} DRAW</div></div>
        <div className="card stat-card"><div className="stat-top">Payout médio</div><div className="stat-value">{pct(st.avgPayout, 1)}</div><div className="stat-foot">Lucro médio WIN: {money(st.avgWin, s)}</div></div>
      </div>

      {filtered.length === 0 ? (
        <Card><EmptyState title={ops.length ? 'Nenhuma operação corresponde aos filtros' : 'Ainda não há operações registradas'}
          text={ops.length ? 'Ajuste os filtros acima para visualizar os registros.' : 'A plataforma não cria dados fictícios. Registre sua primeira operação real ou carregue um exemplo claramente marcado como SIMULAÇÃO.'}
          action={<div className="btn-row" style={{ justifyContent: 'center' }}>
            {ops.length === 0 && <button className="btn primary" onClick={() => openOpEditor('new')}><Plus size={15} /> Registrar operação real</button>}
            {ops.length === 0 && <button className="btn" onClick={() => { loadDemo(makeDemoOperations()); setIncludeDemo(true); toast('Exemplo demonstrativo carregado (selo SIMULAÇÃO).', 'info'); }}><FlaskConical size={15} /> Carregar exemplo</button>}
            {ops.length > 0 && <button className="btn" onClick={() => { setSearch(''); setResult('ALL'); setFrom(''); setTo(''); }}>Limpar filtros</button>}
          </div>} /></Card>
      ) : <OperationTable ops={filtered} maxHeight={680} />}

      <div className="mt-14"><Notice>Dica: clique duas vezes em uma linha para editar. Para filtros avançados, exportação e backup completos, acesse <button className="btn xs ghost" onClick={() => setPage('historico')}><Search size={11} /> Histórico & dados</button></Notice></div>

      {columnsOpen && (
        <Modal title="Colunas da tabela" sub="Escolha quais colunas aparecem nas tabelas de operações. Preferência salva automaticamente."
          onClose={() => setColumnsOpen(false)}
          footer={<><button className="btn" onClick={() => setData((d) => ({ ...d, settings: { ...d.settings, visibleColumns: OP_COLUMNS.map((c) => c.id) } }))}><RotateCcw size={14} /> Mostrar todas</button><button className="btn primary" onClick={() => setColumnsOpen(false)}>Concluir</button></>}>
          <div className="grid grid-2">
            {OP_COLUMNS.map((c) => (
              <label key={c.id} className="card-order">
                <input type="checkbox" checked={cols.includes(c.id)} onChange={() => toggleCol(c.id)} style={{ accentColor: 'var(--accent)' }} />
                <span className="name">{c.label}</span>
              </label>
            ))}
          </div>
        </Modal>
      )}

      {fieldsOpen && (
        <Modal title="Campos do formulário" sub="Oculte campos opcionais que você não utiliza. Os campos essenciais (data,horário, ativo, entrada, payout, resultado) permanecem sempre disponíveis."
          onClose={() => setFieldsOpen(false)} footer={<button className="btn primary" onClick={() => setFieldsOpen(false)}>Concluir</button>}>
          <div className="grid grid-2">
            {Object.keys(s.opFields).map((k) => ({
              key: k, label: ({
                market: 'Tipo de mercado', direction: 'Direção CALL/PUT', strategy: 'Estratégia',
                timeframe: 'Timeframe', expiry: 'Tempo de expiração', notes: 'Observações',
                screenshot: 'Screenshot', series: 'Micro série',
              } as Record<string, string>)[k] || k,
            })).map((f) => (
              <label key={f.key} className="card-order">
                <input type="checkbox" checked={s.opFields[f.key] !== false}
                  onChange={(e) => setData((d) => ({ ...d, settings: { ...d.settings, opFields: { ...d.settings.opFields, [f.key]: e.target.checked } } }))}
                  style={{ accentColor: 'var(--accent)' }} />
                <span className="name">{f.label}</span>
              </label>
            ))}
          </div>
          <div className="mt-14"><Notice>Ocultar um campo não apaga os valores já gravados: eles continuam no histórico e nos relatórios.</Notice></div>
        </Modal>
      )}
    </>
  );
}
