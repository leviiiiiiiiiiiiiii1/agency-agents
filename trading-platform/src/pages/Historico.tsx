import React, { useMemo, useRef, useState } from 'react';
import {
  Search, Download, FileSpreadsheet, Database, Upload, RotateCcw, FlaskConical,
  ShieldCheck, HardDrive, Trash2, AlertTriangle, Info, Filter,
} from 'lucide-react';
import { useStore } from '../state/store';
import { PageHeader, Card, CardHead, Field, Notice, Modal, ConfirmDialog, StatCard, ResultBadge } from '../components/ui';
import { OperationTable } from '../components/OperationTable';
import { sortOps, stats } from '../lib/calc';
import { money, formatDate, pct } from '../lib/format';
import { download, wipeData } from '../lib/storage';
import { exportCsv, exportExcel, backupPayload } from '../lib/exporters';
import { makeDemoOperations } from '../lib/sample';
import type { Operation } from '../types';

export function HistoricoPage() {
  const { data, ops, allOps, includeDemo, setIncludeDemo, range, toast, loadDemo, removeDemo, restore, resetAll } = useStore();
  const s = data.settings;
  const fileRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState('');
  const [asset, setAsset] = useState('ALL');
  const [strategy, setStrategy] = useState('ALL');
  const [result, setResult] = useState('ALL');
  const [market, setMarket] = useState('ALL');
  const [from, setFrom] = useState(range.from);
  const [to, setTo] = useState(range.to);
  const [minVal, setMinVal] = useState('');
  const [maxVal, setMaxVal] = useState('');
  const [confirmReset, setConfirmReset] = useState(false);
  const [restorePreview, setRestorePreview] = useState<unknown>(null);

  const assets = [...new Set(allOps.map((o) => o.asset).filter(Boolean))].sort();
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return sortOps(ops.filter((o) => {
      if (asset !== 'ALL' && o.asset !== asset) return false;
      if (strategy !== 'ALL' && (o.strategyId || 'none') !== strategy) return false;
      if (result !== 'ALL' && o.result !== result) return false;
      if (market !== 'ALL' && o.market !== market) return false;
      if (from && o.date < from) return false;
      if (to && o.date > to) return false;
      if (minVal && o.entry < Number(minVal)) return false;
      if (maxVal && o.entry > Number(maxVal)) return false;
      if (!q) return true;
      const strat = data.strategies.find((x) => x.id === o.strategyId)?.name || '';
      return [o.asset, strat, o.notes, o.date, o.time, o.timeframe, o.expiry, o.seriesId, o.market, o.direction].join(' ').toLowerCase().includes(q);
    })).reverse();
  }, [ops, search, asset, strategy, result, market, from, to, minVal, maxVal, data.strategies]);

  const st = stats(filtered);
  const demoOps = allOps.filter((o) => o.demo);
  const realOps = allOps.filter((o) => !o.demo);

  const doBackup = () => {
    download(`backup-trading-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(backupPayload(data), null, 2));
    toast('Backup JSON gerado com todos os dados e configurações.');
  };

  const handleFile = async (file: File) => {
    try {
      const parsed = JSON.parse(await file.text());
      setRestorePreview(parsed);
    } catch {
      toast('Arquivo inválido: selecione um backup JSON desta plataforma.', 'error');
    }
  };

  return (
    <>
      <PageHeader title="Histórico & segurança dos dados" description="Histórico completo com filtros avançados, exportação, backup e restauração. Os dados são salvos automaticamente no armazenamento local deste navegador e permanecem após atualizar ou fechar a página."
        actions={<><button className="btn" onClick={() => exportCsv(filtered, data, `operacoes-${new Date().toISOString().slice(0, 10)}.csv`)}><Download size={15} /> CSV</button>
          <button className="btn" onClick={() => { exportExcel(data, filtered); toast('Planilha Excel exportada.'); }}><FileSpreadsheet size={15} /> Excel</button>
          <button className="btn primary" onClick={doBackup}><Database size={15} /> Fazer backup</button></>} />

      <div className="grid grid-4 mb-14">
        <StatCard label="Operações reais" icon={<ShieldCheck size={14} />} value={realOps.length} foot="Sempre separadas das simulações" />
        <StatCard label="Registros de simulação" icon={<FlaskConical size={14} />} value={demoOps.length} foot="Identificados com selo SIMULAÇÃO" />
        <StatCard label="Estratégias / movimentações" value={`${data.strategies.length} / ${data.ledger.length}`} foot="Incluídos no backup" />
        <StatCard label="Armazenamento" icon={<HardDrive size={14} />} value="Local" foot="localStorage do navegador · sem servidor" />
      </div>

      <div className="section-title">Filtros avançados</div>
      <Card className="pad-0 mb-14">
        <div className="filter-bar">
          <Field label="Pesquisa geral"><input className="input" value={search} placeholder="Ativo, estratégia, data, observação..." onChange={(e) => setSearch(e.target.value)} /></Field>
          <Field label="Ativo"><select className="select" value={asset} onChange={(e) => setAsset(e.target.value)}><option value="ALL">Todos</option>{assets.map((a) => <option key={a}>{a}</option>)}</select></Field>
          <Field label="Estratégia"><select className="select" value={strategy} onChange={(e) => setStrategy(e.target.value)}><option value="ALL">Todas</option><option value="none">Sem estratégia</option>{data.strategies.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          <Field label="Resultado"><select className="select" value={result} onChange={(e) => setResult(e.target.value)}><option value="ALL">Todos</option><option>WIN</option><option>LOSS</option><option>DRAW</option></select></Field>
          <Field label="Mercado"><select className="select" value={market} onChange={(e) => setMarket(e.target.value)}><option value="ALL">Todos</option><option>Normal</option><option>OTC</option></select></Field>
          <Field label="De"><input type="date" className="input" value={from} onChange={(e) => setFrom(e.target.value)} /></Field>
          <Field label="Até"><input type="date" className="input" value={to} onChange={(e) => setTo(e.target.value)} /></Field>
          <Field label="Entrada mínima"><input type="number" className="input mono" value={minVal} onChange={(e) => setMinVal(e.target.value)} placeholder="0" /></Field>
          <Field label="Entrada máxima"><input type="number" className="input mono" value={maxVal} onChange={(e) => setMaxVal(e.target.value)} placeholder="∞" /></Field>
          <div className="field"><label className="field-label">&nbsp;</label>
            <button className="btn" onClick={() => { setSearch(''); setAsset('ALL'); setStrategy('ALL'); setResult('ALL'); setMarket('ALL'); setFrom(''); setTo(''); setMinVal(''); setMaxVal(''); }}><RotateCcw size={14} /> Limpar</button>
          </div>
          <div className="field"><label className="field-label">Incluir simulações nos resultados</label>
            <div style={{ paddingTop: 6 }}><label className="check-row"><input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} /><span>{includeDemo ? 'Simulações incluídas' : 'Somente dados reais'}</span></label></div>
          </div>
        </div>
      </Card>

      <div className="row wrap mb-14" style={{ gap: 10 }}>
        <span className="pill"><Filter size={11} /> <strong>{filtered.length}</strong> registros</span>
        <span className="pill">Resultado <strong className={st.net >= 0 ? 'value-pos' : 'value-neg'}>{money(st.net, s, { signed: true })}</strong></span>
        <span className="pill">WIN <strong className="value-pos">{st.wins}</strong></span>
        <span className="pill">LOSS <strong className="value-neg">{st.losses}</strong></span>
        <span className="pill">DRAW <strong>{st.draws}</strong></span>
        <span className="pill">Assertividade <strong>{pct(st.winRate, 1)}</strong></span>
        <span className="pill">Volume <strong>{money(st.totalEntry, s)}</strong></span>
      </div>

      <OperationTable ops={filtered} maxHeight={620} />

      <div className="section-title">Backup, restauração e persistência</div>
      <div className="grid grid-2">
        <Card>
          <CardHead title="Backup & restauração" sub="Arquivo JSON com todos os dados e configurações" right={<Database size={15} className="muted" />} />
          <div className="btn-row">
            <button className="btn primary" onClick={doBackup}><Download size={14} /> Exportar backup completo</button>
            <button className="btn" onClick={() => fileRef.current?.click()}><Upload size={14} /> Restaurar de arquivo</button>
            <input ref={fileRef} type="file" accept="application/json,.json" style={{ display: 'none' }} onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); e.target.value = ''; }} />
          </div>
          <div className="divider" />
          <div className="metric-line"><span className="label">Operações</span><span className="val">{allOps.length}</span></div>
          <div className="metric-line"><span className="label">Estratégias</span><span className="val">{data.strategies.length}</span></div>
          <div className="metric-line"><span className="label">Movimentações</span><span className="val">{data.ledger.length}</span></div>
          <div className="metric-line"><span className="label">Planos / anotações</span><span className="val">{data.plans.length} / {Object.keys(data.dayNotes).length}</span></div>
          <div className="metric-line"><span className="label">Screenshots anexadas</span><span className="val">{allOps.filter((o) => o.screenshot).length}</span></div>
          <div className="mt-14"><Notice><HardDrive size={14} /> Os dados são gravados no <b>localStorage</b> deste navegador a cada alteração e persistem após atualizar, fechar ou reiniciar a aplicação. Para migrar entre navegadores/dispositivos, use o backup JSON. Limpar os dados do navegador apaga o armazenamento local — mantenha backups.</Notice></div>
        </Card>

        <Card>
          <CardHead title="Separação: dados reais × exemplos × simulações" sub="Transparência total sobre a origem de cada número" right={<ShieldCheck size={15} className="muted" />} />
          <div className="metric-line"><span className="label"><span className="badge badge-win">REAL</span> Operações registradas pelo usuário</span><span className="val">{realOps.length}</span></div>
          <div className="metric-line"><span className="label"><span className="badge badge-demo">SIMULAÇÃO</span> Exemplos demonstrativos</span><span className="val">{demoOps.length}</span></div>
          <div className="metric-line"><span className="label">Projeções e simulador de ciclo</span><span className="val">não gravados</span></div>
          <div className="divider" />
          <div className="small muted mb-14" style={{ lineHeight: 1.7 }}>
            A plataforma <b>começa vazia</b> e nunca apresenta dados fictícios como se fossem operações reais. O exemplo demonstrativo, quando carregado, cria registros marcados com <span className="badge badge-demo">SIMULAÇÃO</span> que só entram nos cálculos se você ativar a opção "Incluir simulações".
          </div>
          <div className="btn-row">
            <button className="btn" onClick={() => { loadDemo(makeDemoOperations()); setIncludeDemo(true); toast('Exemplo demonstrativo carregado (marcado como SIMULAÇÃO).', 'info'); }}><FlaskConical size={14} /> Carregar exemplo demonstrativo</button>
            <button className="btn danger" disabled={demoOps.length === 0} onClick={() => { removeDemo(); toast('Todos os registros de simulação foram removidos.', 'info'); }}><Trash2 size={14} /> Remover simulações ({demoOps.length})</button>
            <button className="btn danger" onClick={() => setConfirmReset(true)}><RotateCcw size={14} /> Apagar todos os dados</button>
          </div>
          {demoOps.length > 0 && <div className="mt-14"><Notice kind="warn"><Info size={14} /> Existem {demoOps.length} registros de simulação armazenados. Eles estão incluídos no backup, mas identificados como tal.</Notice></div>}
        </Card>
      </div>

      <div className="section-title">Exportações</div>
      <Card>
        <div className="grid grid-3">
          <div className="card-order"><Download size={16} /><div className="name"><b>CSV</b><div className="tiny muted">Operações filtradas, separador ; com BOM UTF-8 (abre no Excel)</div></div><button className="btn sm" onClick={() => exportCsv(filtered, data)}>Baixar</button></div>
          <div className="card-order"><FileSpreadsheet size={16} /><div className="name"><b>Excel (.xlsx)</b><div className="tiny muted">Aba de operações, diário, estratégias, movimentações, semanal e mensal</div></div><button className="btn sm" onClick={() => { exportExcel(data, filtered); toast('Excel exportado.'); }}>Baixar</button></div>
          <div className="card-order"><Database size={16} /><div className="name"><b>Backup JSON</b><div className="tiny muted">Restauração completa: dados + personalizações + screenshots</div></div><button className="btn sm" onClick={doBackup}>Baixar</button></div>
        </div>
      </Card>

      {confirmReset && <ConfirmDialog title="Apagar TODOS os dados" danger confirmLabel="Apagar tudo"
        text={<><AlertTriangle size={16} color="var(--neg)" /> <b>Esta ação é irreversível.</b> Todas as operações, estratégias, movimentações, screenshots, metas e personalizações serão removidas deste navegador. Recomendamos <b>fazer um backup antes</b>.</>}
        onClose={() => setConfirmReset(false)} onConfirm={() => { wipeData(); resetAll(); setConfirmReset(false); }} />}

      {restorePreview !== null && (
        <Modal title="Confirmar restauração de backup" narrow onClose={() => setRestorePreview(null)}
          footer={<><button className="btn" onClick={() => setRestorePreview(null)}>Cancelar</button>
            <button className="btn primary" onClick={() => { if (restore(restorePreview)) { setRestorePreview(null); } }}>Restaurar e substituir dados atuais</button></>}>
          <div className="confirm-text">
            O conteúdo do arquivo substituirá <b>todos os dados atuais</b> deste navegador (operações, configurações e estratégias).<br /><br />
            Arquivo: <span className="tag">{((restorePreview as { format?: string }).format) || 'JSON sem identificação'}</span><br />
            Exportado em: <span className="tag">{String((restorePreview as { exportedAt?: string }).exportedAt || 'desconhecido').slice(0, 19)}</span><br /><br />
            <b>Recomendação:</b> faça um backup dos dados atuais antes de restaurar.
          </div>
        </Modal>
      )}
    </>
  );
}
