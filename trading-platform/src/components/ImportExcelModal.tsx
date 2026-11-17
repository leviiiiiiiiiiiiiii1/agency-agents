import React, { useMemo, useRef, useState } from 'react';
import {
  FileSpreadsheet, Upload, Download, AlertTriangle, CheckCircle2, Info,
  Wand2, X, Table2, ShieldCheck,
} from 'lucide-react';
import { useStore } from '../state/store';
import { Modal, Field, Notice, ResultBadge } from './ui';
import {
  readWorkbook, buildRows, guessMapping, convertRows, downloadTemplate,
  IMPORT_FIELDS, defaultImportOptions, guessHeaderRow,
  type WorkbookData, type ColumnMapping, type ImportOptions,
} from '../lib/importers';
import { money, formatDate } from '../lib/format';

const ACCEPT = '.xlsx,.xls,.xlsm,.csv,.tsv,.txt';

export function ImportExcelModal() {
  const { data, importOpen, closeImport, importOperations, toast } = useStore();
  const fileRef = useRef<HTMLInputElement>(null);
  const [book, setBook] = useState<WorkbookData | null>(null);
  const [sheet, setSheet] = useState('');
  const [headerRow, setHeaderRow] = useState(1);
  const [mapping, setMapping] = useState<ColumnMapping>({});
  const [options, setOptions] = useState<ImportOptions>(() => defaultImportOptions(data));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);

  const grid = book && sheet ? book.grids[sheet] || [] : [];
  const parsed = useMemo(() => grid.length ? buildRows(grid, headerRow) : { headers: [] as string[], rows: [] }, [grid, headerRow]);

  const result = useMemo(() => {
    if (!parsed.rows.length) return null;
    try { return convertRows(parsed.rows, mapping, options, data); }
    catch (e) { return null; }
  }, [parsed.rows, mapping, options, data]);

  const reset = () => {
    setBook(null); setSheet(''); setHeaderRow(1); setMapping({}); setError('');
    setOptions(defaultImportOptions(data));
  };

  const loadFile = async (file: File) => {
    setBusy(true); setError('');
    try {
      const wb = await readWorkbook(file);
      if (!wb.sheetNames.length) throw new Error('A planilha não possui abas com dados.');
      // Escolhe a aba com mais linhas preenchidas
      const bestSheet = [...wb.sheetNames].sort((a, b) => (wb.grids[b]?.length || 0) - (wb.grids[a]?.length || 0))[0];
      setBook(wb);
      setSheet(bestSheet);
      const hr = guessHeaderRow(wb.grids[bestSheet] || []);
      setHeaderRow(hr);
      const { headers } = buildRows(wb.grids[bestSheet] || [], hr);
      setMapping(guessMapping(headers));
      toast(`Arquivo "${file.name}" lido: ${wb.sheetNames.length} aba(s). Confira o mapeamento.`, 'info');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível ler o arquivo.');
      setBook(null);
    } finally { setBusy(false); }
  };

  const changeSheet = (name: string) => {
    setSheet(name);
    const hr = guessHeaderRow(book?.grids[name] || []);
    setHeaderRow(hr);
    setMapping(guessMapping(buildRows(book?.grids[name] || [], hr).headers));
  };

  const changeHeaderRow = (n: number) => {
    setHeaderRow(n);
    setMapping(guessMapping(buildRows(grid, n).headers));
  };

  const doImport = () => {
    if (!result || result.ops.length === 0) return;
    importOperations(result.ops, result.strategies);
    reset();
    closeImport();
  };

  if (!importOpen) return null;

  return (
    <Modal
      title="Importar resultados do Excel"
      sub="Carregue uma planilha .xlsx, .xls ou .csv. Nada é gravado antes de você conferir a prévia e confirmar."
      wide
      onClose={() => { reset(); closeImport(); }}
      footer={<>
        {book && <button className="btn ghost" style={{ marginRight: 'auto' }} onClick={reset}><X size={14} /> Trocar arquivo</button>}
        <button className="btn" onClick={() => { reset(); closeImport(); }}>Cancelar</button>
        <button className="btn primary" disabled={!result || result.ops.length === 0 || busy}
          onClick={doImport}>
          <CheckCircle2 size={15} /> Importar {result?.ops.length || 0} operação(ões)
        </button>
      </>}
    >
      {/* 1. Arquivo */}
      <div className={`card pad-0 mb-14`} style={{ borderStyle: 'dashed', background: dragging ? 'var(--accent-soft)' : undefined }}
        onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files?.[0]; if (f) loadFile(f); }}>
        <div className="row wrap" style={{ padding: 16, gap: 14 }}>
          <FileSpreadsheet size={28} className="value-accent" />
          <div style={{ flex: 1, minWidth: 200 }}>
            <b style={{ fontSize: 13 }}>{book ? book.fileName : 'Selecione ou arraste sua planilha aqui'}</b>
            <div className="tiny muted mt-8">{book ? `${book.sheetNames.length} aba(s) · ${grid.length} linha(s)` : 'Formatos: .xlsx, .xls, .xlsm, .csv (separador ; ou ,), .tsv'}</div>
          </div>
          <button className="btn sm" onClick={() => fileRef.current?.click()} disabled={busy}><Upload size={14} /> {busy ? 'Lendo...' : 'Escolher arquivo'}</button>
          <button className="btn sm" onClick={() => { downloadTemplate(); toast('Modelo de planilha baixado.', 'info'); }}><Download size={14} /> Baixar modelo .xlsx</button>
          <input ref={fileRef} type="file" accept={ACCEPT} style={{ display: 'none' }}
            onChange={(e) => { const f = e.target.files?.[0]; if (f) loadFile(f); e.target.value = ''; }} />
        </div>
      </div>
      {error && <div className="mb-14"><Notice kind="danger"><AlertTriangle size={14} /> {error}</Notice></div>}

      {!book && (
        <Notice><Info size={14} /> O modelo .xlsx contém apenas os cabeçalhos e uma aba de instruções — <b>nenhum dado fictício</b>. Você também pode importar sua própria planilha: o mapeamento de colunas é detectado automaticamente e pode ser ajustado abaixo.</Notice>
      )}

      {book && <>
        {/* 2. Aba e cabeçalho */}
        <div className="form-grid cols-4 mb-14">
          <Field label="Aba da planilha">
            <select className="select" value={sheet} onChange={(e) => changeSheet(e.target.value)}>
              {book.sheetNames.map((n) => <option key={n} value={n}>{n} ({(book.grids[n] || []).length} linhas)</option>)}
            </select>
          </Field>
          <Field label="Linha do cabeçalho" hint="Linha que contém os nomes das colunas">
            <select className="select" value={headerRow} onChange={(e) => changeHeaderRow(Number(e.target.value))}>
              {Array.from({ length: Math.min(15, grid.length) }, (_, i) => i + 1).map((n) => <option key={n} value={n}>Linha {n}</option>)}
            </select>
          </Field>
          <Field label="Colunas detectadas"><div className="pill" style={{ paddingTop: 9 }}>{parsed.headers.length} colunas</div></Field>
          <Field label="Linhas de dados"><div className="pill" style={{ paddingTop: 9 }}>{parsed.rows.length} linhas</div></Field>
        </div>

        {/* 3. Mapeamento */}
        <div className="section-title">Mapeamento de colunas <button className="btn xs" onClick={() => setMapping(guessMapping(parsed.headers))}><Wand2 size={12} /> Detectar novamente</button></div>
        <div className="grid grid-3 mb-14">
          {IMPORT_FIELDS.map((f) => (
            <Field key={f.key} label={`${f.label}${f.required ? ' *' : ''}`} hint={f.hint}>
              <select className="select" value={mapping[f.key] || ''} onChange={(e) => setMapping({ ...mapping, [f.key]: e.target.value })}>
                <option value="">— não importar —</option>
                {parsed.headers.map((h) => <option key={h} value={h}>{h}</option>)}
              </select>
            </Field>
          ))}
        </div>

        {/* 4. Opções */}
        <div className="section-title">Opções de importação</div>
        <div className="card mb-14" style={{ padding: 14 }}>
          <div className="form-grid cols-4">
            <Field label="Payout padrão (%)" hint="Usado se a coluna não existir"><input className="input mono" type="number" value={options.defaultPayout} onChange={(e) => setOptions({ ...options, defaultPayout: Number(e.target.value) })} /></Field>
            <Field label="Data padrão" hint="Usada se a data estiver vazia/inválida"><input className="input" type="date" value={options.defaultDate} onChange={(e) => setOptions({ ...options, defaultDate: e.target.value })} /></Field>
            <Field label="Ordem das datas" hint="Para dd/MM ou MM/dd ambíguos">
              <select className="select" value={options.dateOrder} onChange={(e) => setOptions({ ...options, dateOrder: e.target.value as ImportOptions['dateOrder'] })}>
                <option value="dmy">dia / mês / ano</option><option value="mdy">mês / dia / ano</option>
                <option value="ymd">ano / mês / dia</option><option value="auto">Automático</option>
              </select>
            </Field>
            <Field label="Ativo padrão" hint="Quando a coluna estiver vazia"><input className="input" placeholder="Opcional" value={options.defaultAsset} onChange={(e) => setOptions({ ...options, defaultAsset: e.target.value })} /></Field>
          </div>
          <div className="divider" />
          <div className="grid grid-2">
            <label className="check-row"><input type="checkbox" checked={options.recalcProfit} onChange={(e) => setOptions({ ...options, recalcProfit: e.target.checked })} />
              <span>Recalcular lucro pela regra <b>entrada × payout × resultado</b> (recomendado)</span></label>
            <label className="check-row"><input type="checkbox" checked={options.skipDuplicates} onChange={(e) => setOptions({ ...options, skipDuplicates: e.target.checked })} />
              <span>Ignorar duplicatas (mesma data, hora, ativo, entrada e resultado)</span></label>
            <label className="check-row"><input type="checkbox" checked={options.createStrategies} onChange={(e) => setOptions({ ...options, createStrategies: e.target.checked })} />
              <span>Criar automaticamente estratégias ainda não cadastradas</span></label>
            <label className="check-row"><input type="checkbox" checked={options.markDemo} onChange={(e) => setOptions({ ...options, markDemo: e.target.checked })} />
              <span>Marcar linhas importadas como <b>SIMULAÇÃO</b></span></label>
          </div>
        </div>

        {/* 5. Prévia */}
        <div className="section-title">Prévia e validação</div>
        {result && <>
          <div className="grid grid-4 mb-14">
            <div className="card stat-card"><div className="stat-top">Linhas lidas</div><div className="stat-value sm">{result.totalRows}</div></div>
            <div className="card stat-card"><div className="stat-top"><CheckCircle2 size={13} /> Prontas para importar</div><div className="stat-value sm value-pos">{result.ops.length}</div></div>
            <div className="card stat-card"><div className="stat-top"><AlertTriangle size={13} /> Linhas com erro</div><div className={`stat-value sm ${result.errors.length ? 'value-neg' : ''}`}>{result.errors.length}</div></div>
            <div className="card stat-card"><div className="stat-top">Duplicatas ignoradas</div><div className="stat-value sm">{result.duplicates}</div><div className="stat-foot">{result.strategies.length} estratégia(s) serão criadas</div></div>
          </div>

          {result.warnings.length > 0 && <div className="mb-14"><Notice kind="warn"><div><b>{result.warnings.length} aviso(s):</b><ul style={{ margin: '6px 0 0', paddingLeft: 18, lineHeight: 1.7 }}>{result.warnings.slice(0, 6).map((w, i) => <li key={i}>{w}</li>)}</ul>{result.warnings.length > 6 && <div>+ {result.warnings.length - 6} outros avisos</div>}</div></Notice></div>}
          {result.errors.length > 0 && <div className="mb-14"><Notice kind="danger"><div><b>{result.errors.length} linha(s) serão ignoradas:</b><ul style={{ margin: '6px 0 0', paddingLeft: 18, lineHeight: 1.7 }}>{result.errors.slice(0, 6).map((er, i) => <li key={i}>Linha {er.row}: {er.message}</li>)}</ul>{result.errors.length > 6 && <div>+ {result.errors.length - 6} outras</div>}</div></Notice></div>}

          <div className="table-wrap mb-14">
            <table className="table">
              <thead><tr><th>Data</th><th>Hora</th><th>Ativo</th><th>Resultado</th><th className="num">Entrada</th><th className="num">Payout</th><th className="num">Lucro</th><th>Origem</th></tr></thead>
              <tbody>
                {result.ops.length === 0 && <tr><td colSpan={8} className="center muted" style={{ padding: 22 }}>Nenhuma linha válida. Ajuste o mapeamento das colunas obrigatórias.</td></tr>}
                {result.ops.slice(0, 8).map((o) => <tr key={o.id}>
                  <td>{formatDate(o.date, data.settings)}</td><td className="mono">{o.time}</td><td className="strong">{o.asset || '—'}</td>
                  <td><ResultBadge result={o.result} /></td>
                  <td className="num">{money(o.entry, data.settings)}</td><td className="num">{o.payout.toFixed(0)}%</td>
                  <td className={`num ${o.profit >= 0 ? 'value-pos' : 'value-neg'}`}>{money(o.profit, data.settings, { signed: true })}</td>
                  <td><span className={`badge ${o.demo ? 'badge-demo' : 'badge-accent'}`}>{o.demo ? 'SIMULAÇÃO' : 'IMPORTADO'}</span></td>
                </tr>)}
              </tbody>
            </table>
          </div>
          {result.ops.length > 8 && <div className="tiny muted mb-14">Exibindo 8 de {result.ops.length} linhas da prévia.</div>}

          <Notice><ShieldCheck size={14} /> A importação registra <b>resultados históricos</b>: limites operacionais (stop, exposição, risco) continuam válidos para novas operações, mas não bloqueiam a carga de histórico. Todos os indicadores, saldos e relatórios são recalculados automaticamente. Registros importados recebem o selo IMPORTADO e podem ser editados ou excluídos normalmente.</Notice>
        </>}
      </>}
    </Modal>
  );
}
