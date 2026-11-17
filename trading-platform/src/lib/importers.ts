/* ==========================================================================
   Importação de resultados a partir de planilhas (.xlsx / .xls / .csv / .tsv)
   - Lê a planilha com SheetJS (carregado sob demanda)
   - Detecta automaticamente o mapeamento de colunas
   - Normaliza datas, horas, números em pt-BR e resultados W/L/D
   - Nunca inventa valores: linhas inválidas são ignoradas e relatadas
   ========================================================================== */
import type { Operation, Strategy, TradeResult, MarketType, Direction, AppData } from '../types';
import { uid, todayISO, calcProfit, round2 } from './defaults';

export type FieldKey =
  | 'date' | 'time' | 'asset' | 'market' | 'direction' | 'strategy'
  | 'timeframe' | 'expiry' | 'entry' | 'payout' | 'result' | 'profit'
  | 'notes' | 'series';

export type ColumnMapping = Partial<Record<FieldKey, string>>;

export interface FieldDef {
  key: FieldKey;
  label: string;
  required?: boolean;
  aliases: string[];
  hint: string;
}

/** Sinônimos aceitos nos cabeçalhos (em português e inglês). */
export const IMPORT_FIELDS: FieldDef[] = [
  { key: 'date', label: 'Data', required: true, aliases: ['data', 'date', 'dia', 'dia da operacao', 'data da operacao', 'data operacao', 'trade date', 'datahora', 'data hora'], hint: 'ISO, dd/MM/yyyy, MM/dd/yyyy ou data serial do Excel' },
  { key: 'time', label: 'Horário', aliases: ['hora', 'horario', 'time', 'hour', 'hora da operacao', 'horario da entrada', 'hora entrada'], hint: 'HH:mm. Ausente → 00:00' },
  { key: 'asset', label: 'Ativo', aliases: ['ativo', 'asset', 'par', 'par de moedas', 'symbol', 'moeda', 'instrumento', 'ticker', 'papel'], hint: 'Texto livre' },
  { key: 'market', label: 'Mercado', aliases: ['mercado', 'market', 'tipo de mercado', 'tipo mercado'], hint: 'Normal / OTC' },
  { key: 'direction', label: 'Direção', aliases: ['direcao', 'direction', 'operacao', 'tipo', 'call put', 'compra venda'], hint: 'CALL / PUT' },
  { key: 'strategy', label: 'Estratégia', aliases: ['estrategia', 'strategy', 'setup', 'metodo', 'metodo utilizado', 'sistema'], hint: 'Nome da estratégia (pode ser criada automaticamente)' },
  { key: 'timeframe', label: 'Timeframe', aliases: ['timeframe', 'tempo grafico', 'tempo gráfico', 'tf', 'periodo', 'periodo do grafico'], hint: 'M1, M5, M15...' },
  { key: 'expiry', label: 'Expiração', aliases: ['expiracao', 'expiration', 'vencimento', 'tempo de expiracao', 'expiry', 'tempo'], hint: '1m, 5m...' },
  { key: 'entry', label: 'Valor da entrada', required: true, aliases: ['entrada', 'investimento', 'valor', 'valor da entrada', 'stake', 'amount', 'investido', 'valor investido', 'entry', 'capital de entrada'], hint: 'Aceita R$ 1.234,56 ou 1234.56' },
  { key: 'payout', label: 'Payout (%)', aliases: ['payout', '% payout', 'percentual de payout', 'retorno percentual', 'taxa de retorno', 'percentual payout'], hint: '85 ou 85%. Frações (0,85) viram 85%' },
  { key: 'result', label: 'Resultado', required: true, aliases: ['resultado', 'result', 'w l', 'win loss', 'w-l', 'status', 'situacao', 'wl', 'ganho perda', 'resultado da operacao'], hint: 'W/WIN, L/LOSS, D/DRAW (ou inferido pelo lucro)' },
  { key: 'profit', label: 'Lucro / prejuízo', aliases: ['lucro', 'prejuizo', 'retorno', 'profit', 'pnl', 'resultado financeiro', 'lucro prejuizo', 'ganho', 'retorno financeiro'], hint: 'Opcional: por padrão o lucro é recalculado da entrada × payout' },
  { key: 'notes', label: 'Observações', aliases: ['observacao', 'observacoes', 'notes', 'note', 'obs', 'comentario', 'descricao', 'anotacao'], hint: 'Texto livre' },
  { key: 'series', label: 'Micro série', aliases: ['serie', 'micro serie', 'micro series', 'serie id', 'grupo', 'bloco', 'lote', 'series'], hint: 'Agrupamento na visão Planilha / Séries' },
];

export interface ImportOptions {
  markDemo: boolean;
  skipDuplicates: boolean;
  recalcProfit: boolean;
  createStrategies: boolean;
  defaultPayout: number;
  defaultAsset: string;
  defaultDate: string;
  dateOrder: 'auto' | 'dmy' | 'mdy' | 'ymd';
}

export const defaultImportOptions = (data: AppData): ImportOptions => ({
  markDemo: false,
  skipDuplicates: true,
  recalcProfit: true,
  createStrategies: false,
  defaultPayout: 85,
  defaultAsset: '',
  defaultDate: todayISO(),
  dateOrder: data.settings.dateFormat.startsWith('MM') ? 'mdy' : data.settings.dateFormat.startsWith('yyyy') ? 'ymd' : 'dmy',
});

export interface WorkbookData {
  fileName: string;
  sheetNames: string[];
  grids: Record<string, CellValue[][]>;
}
export type CellValue = string | number | boolean | Date | null | undefined;

/* --------------------------------- Leitura -------------------------------- */

/** Parser de texto delimitado com suporte a aspas, aspas escapadas e CRLF.
    Mantém tudo como TEXTO: o parser de CSV do SheetJS converte "05/11/2026"
    em serial de data no formato americano, trocando dia e mês. */
export function parseDelimited(text: string, sep: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') { cell += '"'; i++; }
        else quoted = false;
      } else cell += ch;
    } else if (ch === '"' && cell === '') {
      quoted = true;
    } else if (ch === sep) {
      row.push(cell); cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i++;
      row.push(cell); cell = '';
      if (row.some((c) => c.trim() !== '')) rows.push(row);
      row = [];
    } else {
      cell += ch;
    }
  }
  row.push(cell);
  if (row.some((c) => c.trim() !== '')) rows.push(row);
  return rows;
}

export async function readWorkbook(file: File): Promise<WorkbookData> {
  const name = file.name.toLowerCase();

  if (name.endsWith('.csv') || name.endsWith('.tsv') || name.endsWith('.txt')) {
    const raw = await file.text();
    const text = raw.replace(/^\uFEFF/, '');
    const firstLine = text.split(/\r?\n/)[0] || '';
    const counts = (c: string) => (firstLine.match(new RegExp(c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length;
    const semicolons = counts(';'), commas = counts(','), tabs = counts('\t');
    const sep = tabs > semicolons && tabs > commas ? '\t' : semicolons >= commas ? ';' : ',';
    const sheetName = file.name.replace(/\.[^.]+$/, '') || 'Dados';
    return { fileName: file.name, sheetNames: [sheetName], grids: { [sheetName]: parseDelimited(text, sep) } };
  }

  const XLSX = await import('xlsx');
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: 'array', cellDates: true });
  const grids: Record<string, CellValue[][]> = {};
  for (const sheetName of wb.SheetNames) {
    const ws = wb.Sheets[sheetName];
    if (!ws) continue;
    const rows = XLSX.utils.sheet_to_json<CellValue[]>(ws, { header: 1, raw: true, defval: '', blankrows: false });
    grids[sheetName] = rows.map((r) => Array.isArray(r) ? r : []);
  }
  return { fileName: file.name, sheetNames: wb.SheetNames, grids };
}

/** Transforma a grade a partir da linha de cabeçalho escolhida (1-based). */
export function buildRows(grid: CellValue[][], headerRow: number): { headers: string[]; rows: Record<string, CellValue>[] } {
  const rawHeaders = (grid[headerRow - 1] || []).map((h) => String(h ?? '').trim());
  const used = new Map<string, number>();
  const headers = rawHeaders.map((h, i) => {
    const base = h || `Coluna ${i + 1}`;
    const n = (used.get(base) || 0) + 1;
    used.set(base, n);
    return n > 1 ? `${base} (${n})` : base;
  });
  const rows = grid.slice(headerRow)
    .filter((r) => r.some((c) => c !== '' && c !== null && c !== undefined && String(c).trim() !== ''))
    .map((r) => Object.fromEntries(headers.map((h, i) => [h, r[i] ?? ''])) as Record<string, CellValue>);
  return { headers, rows };
}

const norm = (s: string) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
  .replace(/[%()_\-.]/g, ' ').replace(/\s+/g, ' ').trim();

/** Localiza automaticamente a linha que contém os cabeçalhos (1-based). */
export function guessHeaderRow(grid: CellValue[][]): number {
  const aliases = IMPORT_FIELDS.flatMap((f) => f.aliases).map((a) => norm(a));
  let best = { row: 1, score: 0 };
  for (let i = 0; i < Math.min(15, grid.length); i++) {
    let score = 0;
    for (const cell of grid[i] || []) {
      const v = norm(String(cell ?? ''));
      if (v && aliases.some((a) => v.includes(a))) score++;
    }
    if (score > best.score) best = { row: i + 1, score };
  }
  return best.score >= 2 ? best.row : 1;
}

/* ---------------------------- Detecção de colunas --------------------------- */

export function guessMapping(headers: string[]): ColumnMapping {
  const mapping: ColumnMapping = {};
  for (const field of IMPORT_FIELDS) {
    let best: { header: string; score: number } | null = null;
    for (const header of headers) {
      const h = norm(header);
      if (!h) continue;
      // Colunas de percentual só fazem sentido para payout; evita mapear
      // "% Micro Série" como série ou como observação. Usa o cabeçalho cru
      // porque norm() remove o símbolo "%".
      if (field.key !== 'payout' && /%|percentual/i.test(header)) continue;
      // "Observação Nº" costuma ser o rótulo do bloco, não texto livre.
      if (field.key === 'notes' && /n[º°]|numero|observacao n/.test(h)) continue;
      const hTokens = h.split(' ').filter(Boolean);
      let score = 0;
      for (const alias of field.aliases) {
        const a = norm(alias);
        const aTokens = a.split(' ').filter(Boolean);
        if (h === a) score = Math.max(score, 100);
        // Todas as palavras do alias aparecem como palavras inteiras no cabeçalho
        else if (aTokens.length && aTokens.every((t) => hTokens.includes(t))) score = Math.max(score, 80);
        else if (h.startsWith(a + ' ') || h.endsWith(' ' + a)) score = Math.max(score, 70);
        // Substring só para aliases longos, evitando "time" dentro de "investimento"
        else if (a.length >= 6 && h.includes(a)) score = Math.max(score, 45);
      }
      if (score > 0 && (!best || score > best.score)) best = { header, score };
    }
    if (best) mapping[field.key] = best.header;
  }
  return mapping;
}

/* ------------------------------ Normalização ------------------------------- */

export function parseNumber(v: CellValue): number {
  if (v === null || v === undefined || v === '') return NaN;
  if (typeof v === 'number') return Number.isFinite(v) ? v : NaN;
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (v instanceof Date) return NaN;
  let str = String(v).trim();
  if (!str) return NaN;
  const negative = /^\(.*\)$/.test(str) || str.startsWith('-');
  str = str.replace(/[()]/g, '').replace(/^[-+]/, '')
    .replace(/r\$/gi, '').replace(/[a-zA-Z€$£¥\s%]/g, '');
  if (!str) return NaN;
  const lastComma = str.lastIndexOf(',');
  const lastDot = str.lastIndexOf('.');
  if (lastComma >= 0 && lastDot >= 0) {
    if (lastComma > lastDot) str = str.replace(/\./g, '').replace(',', '.');
    else str = str.replace(/,/g, '');
  } else if (lastComma >= 0) {
    // "1.234,56" já tratado; "12,50" é decimal; "1,234" é milhar
    const decimals = str.length - lastComma - 1;
    const commaCount = (str.match(/,/g) || []).length;
    if (commaCount === 1 && decimals === 2) str = str.replace(',', '.');
    else if (commaCount === 1 && decimals > 2) str = str.replace(',', '.');
    else str = str.replace(/,/g, '');
  }
  const n = Number(str);
  if (!Number.isFinite(n)) return NaN;
  return negative ? -n : n;
}

export function parseDate(v: CellValue, order: ImportOptions['dateOrder'], fallback: string): { date: string; time?: string } | null {
  if (v === null || v === undefined || v === '') return null;
  if (v instanceof Date) {
    if (Number.isNaN(v.getTime())) return null;
    const d = `${v.getFullYear()}-${String(v.getMonth() + 1).padStart(2, '0')}-${String(v.getDate()).padStart(2, '0')}`;
    return { date: d, time: `${String(v.getHours()).padStart(2, '0')}:${String(v.getMinutes()).padStart(2, '0')}` };
  }
  if (typeof v === 'number') {
    // serial do Excel (base 1899-12-30)
    const days = Math.floor(v);
    if (days > 1 && days < 100000) {
      const dt = new Date(Math.round((days - 25569) * 86400 * 1000));
      const date = dt.toISOString().slice(0, 10);
      const fraction = v - days;
      const time = fraction > 0 ? `${String(Math.floor(fraction * 24)).padStart(2, '0')}:${String(Math.floor((fraction * 1440) % 60)).padStart(2, '0')}` : undefined;
      return { date, time };
    }
    return null;
  }
  const str = String(v).trim();
  if (!str) return null;

  // ISO: 2026-11-05 ou 2026-11-05T14:30:00
  let m = str.match(/^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?/);
  if (m) return { date: iso(Number(m[1]), Number(m[2]), Number(m[3])), time: m[4] ? `${m[4].padStart(2, '0')}:${m[5]}` : undefined };

  // dd/MM/yyyy (ou MM/dd/yyyy) opcionalmente com horário
  m = str.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?:\s+(\d{1,2}):(\d{2}))?/);
  if (m) {
    const a = Number(m[1]), b = Number(m[2]);
    let year = Number(m[3]);
    if (year < 100) year += year < 70 ? 2000 : 1900;
    let day = a, month = b;
    const effective = order === 'auto'
      ? (a > 12 ? 'dmy' : b > 12 ? 'mdy' : 'dmy') : order;
    if (effective === 'mdy') { month = a; day = b; }
    if (effective === 'ymd') { year = a; month = b; day = Number(m[3]); }
    const date = iso(year, month, day);
    if (date) return { date, time: m[4] ? `${m[4].padStart(2, '0')}:${m[5]}` : undefined };
  }

  // dd/MM (sem ano) → usa o ano da data padrão
  m = str.match(/^(\d{1,2})[-/.](\d{1,2})$/);
  if (m) {
    const year = Number((fallback || todayISO()).slice(0, 4));
    const a = Number(m[1]), b = Number(m[2]);
    const month = order === 'mdy' ? a : b;
    const day = order === 'mdy' ? b : a;
    return { date: iso(year, month, day) };
  }
  return null;
}

function iso(year: number, month: number, day: number): string {
  if (month < 1 || month > 12 || day < 1 || day > 31) return '';
  const d = new Date(year, month - 1, day);
  if (d.getFullYear() !== year || d.getMonth() !== month - 1 || d.getDate() !== day) return '';
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function parseTime(v: CellValue): string | null {
  if (v === null || v === undefined || v === '') return null;
  if (v instanceof Date) return `${String(v.getHours()).padStart(2, '0')}:${String(v.getMinutes()).padStart(2, '0')}`;
  if (typeof v === 'number') {
    const fraction = v > 1 && v < 2 ? v - 1 : v; // 1,5 às vezes aparece como 1.5
    if (fraction >= 0 && fraction < 1) {
      const minutes = Math.round(fraction * 1440);
      return `${String(Math.floor(minutes / 60)).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`;
    }
    return null;
  }
  const m = String(v).trim().match(/^(\d{1,2}):(\d{2})/);
  if (!m) return null;
  const h = Math.min(23, Number(m[1])), min = Math.min(59, Number(m[2]));
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

export function parseResult(v: CellValue): TradeResult | null {
  if (v === null || v === undefined || v === '') return null;
  const s = norm(String(v));
  if (['win', 'w', 'g', 'green', 'ganho', 'ganhou', 'gain', 'acerto', 'positivo', '1', 'sim', 'ok', 'vitoria'].some((x) => s === x || s.startsWith(x + ' '))) return 'WIN';
  if (['loss', 'l', 'p', 'red', 'perda', 'perdeu', 'lost', 'erro', 'negativo', '0', 'nao', 'derrota'].some((x) => s === x || s.startsWith(x + ' '))) return 'LOSS';
  if (['draw', 'd', 'e', 'empate', 'doji', 'zero', 'neutro', 'devolucao', 'devolução'].some((x) => s === x || s.startsWith(x + ' '))) return 'DRAW';
  return null;
}

const parseMarket = (v: CellValue): MarketType => /otc|binaria|binary/i.test(String(v ?? '')) ? 'OTC' : 'Normal';
const parseDirection = (v: CellValue): Direction => /put|venda|sell|baixa|down/i.test(String(v ?? '')) ? 'PUT' : 'CALL';
const str = (v: CellValue) => v === null || v === undefined ? '' : String(v).trim();

/* ------------------------------- Conversão -------------------------------- */

export interface ConvertResult {
  ops: Operation[];
  strategies: Strategy[];
  errors: { row: number; message: string }[];
  duplicates: number;
  warnings: string[];
  totalRows: number;
  inferredResults: number;
  profitFromSheet: number;
}

export function convertRows(
  rows: Record<string, CellValue>[],
  mapping: ColumnMapping,
  options: ImportOptions,
  data: AppData,
): ConvertResult {
  const val = (row: Record<string, CellValue>, key: FieldKey): CellValue => {
    const col = mapping[key];
    return col ? row[col] : '';
  };
  const errors: ConvertResult['errors'] = [];
  const warnings: string[] = [];
  const ops: Operation[] = [];
  const strategies: Strategy[] = [];
  const seen = new Set<string>();
  const existing = new Set(data.operations.map((o) => `${o.date}|${o.time}|${o.asset}|${o.entry}|${o.result}`));
  const strategyByName = new Map(data.strategies.map((s) => [norm(s.name), s.id]));
  const createdNames = new Set<string>();
  let duplicates = 0, inferredResults = 0, profitFromSheet = 0;

  const fallbackDate = parseDate(options.defaultDate, 'ymd', todayISO())?.date || todayISO();

  rows.forEach((row, index) => {
    const rowNumber = index + 1;
    const parsedDate = parseDate(val(row, 'date'), options.dateOrder, fallbackDate);
    const date = parsedDate?.date || fallbackDate;
    if (!parsedDate) warnings.push(`Linha ${rowNumber}: data não reconhecida, foi usada a data padrão ${date}.`);

    let time = parseTime(val(row, 'time')) || parsedDate?.time || '00:00';
    const asset = str(val(row, 'asset')) || options.defaultAsset;
    const entry = parseNumber(val(row, 'entry'));
    if (!Number.isFinite(entry) || entry <= 0) {
      errors.push({ row: rowNumber, message: 'valor de entrada ausente ou inválido' });
      return;
    }

    let payoutRaw = parseNumber(val(row, 'payout'));
    let payout = Number.isFinite(payoutRaw) ? payoutRaw : options.defaultPayout;
    if (payout > 0 && payout < 1) payout = round2(payout * 100); // 0,85 → 85%
    if (payout < 0) payout = 0;

    let result = parseResult(val(row, 'result'));
    const sheetProfit = parseNumber(val(row, 'profit'));
    if (!result && Number.isFinite(sheetProfit)) {
      result = sheetProfit > 0 ? 'WIN' : sheetProfit < 0 ? 'LOSS' : 'DRAW';
      inferredResults++;
    }
    if (!result) {
      errors.push({ row: rowNumber, message: 'resultado (W/L/D) não reconhecido e não há lucro para inferi-lo' });
      return;
    }

    const useSheetProfit = !options.recalcProfit && Number.isFinite(sheetProfit);
    const profit = useSheetProfit ? round2(sheetProfit as number) : calcProfit(entry, payout, result);
    if (useSheetProfit) profitFromSheet++;

    let strategyId = '';
    const strategyName = str(val(row, 'strategy'));
    if (strategyName) {
      const key = norm(strategyName);
      strategyId = strategyByName.get(key) || '';
      if (!strategyId && options.createStrategies && !createdNames.has(key)) {
        const st: Strategy = {
          id: uid(), name: strategyName, description: 'Criada automaticamente na importação da planilha',
          config: '', assets: asset, timeframe: str(val(row, 'timeframe')) || 'M1',
          expiry: str(val(row, 'expiry')) || '1m', active: true,
          color: '#60a5fa', createdAt: Date.now(),
        };
        strategies.push(st);
        strategyByName.set(key, st.id);
        createdNames.add(key);
        strategyId = st.id;
      } else if (!strategyId) {
        strategyId = '';
      }
    }

    const key = `${date}|${time}|${asset}|${entry}|${result}`;
    if (options.skipDuplicates && (existing.has(key) || seen.has(key))) { duplicates++; return; }
    seen.add(key);

    const op: Operation = {
      id: uid(), date, time, asset,
      market: parseMarket(val(row, 'market')),
      direction: parseDirection(val(row, 'direction')),
      strategyId,
      timeframe: str(val(row, 'timeframe')) || 'M1',
      expiry: str(val(row, 'expiry')) || '1m',
      entry: round2(entry), payout: round2(payout), result, profit,
      profitEdited: useSheetProfit,
      notes: str(val(row, 'notes')),
      seriesId: str(val(row, 'series')) || undefined,
      demo: options.markDemo,
      source: 'import',
      createdAt: Date.now() + index,
    };
    ops.push(op);
  });

  if (inferredResults) warnings.push(`${inferredResults} resultado(s) foram inferidos pela coluna de lucro (positivo = WIN, negativo = LOSS, zero = DRAW).`);
  if (profitFromSheet) warnings.push(`${profitFromSheet} linha(s) usaram o valor de lucro da planilha e foram marcadas como "corrigido manualmente".`);
  if (!mapping.payout) warnings.push(`Nenhuma coluna de payout mapeada: foi usado o payout padrão de ${options.defaultPayout}%.`);
  if (!mapping.date) warnings.push(`Nenhuma coluna de data mapeada: todas as linhas usarão a data padrão ${fallbackDate}.`);

  return { ops, strategies, errors, duplicates, warnings, totalRows: rows.length, inferredResults, profitFromSheet };
}

/** Gera um modelo de planilha (cabeçalhos + instruções), sem dados fictícios. */
export async function downloadTemplate() {
  const XLSX = await import('xlsx');
  const wb = XLSX.utils.book_new();
  const header = ['Data', 'Horário', 'Ativo', 'Mercado', 'Direção', 'Estratégia', 'Timeframe', 'Expiração', 'Entrada', 'Payout (%)', 'Resultado', 'Lucro/Prejuízo', 'Observações', 'Micro série'];
  const ws = XLSX.utils.aoa_to_sheet([header]);
  ws['!cols'] = header.map(() => ({ wch: 18 }));
  XLSX.utils.book_append_sheet(wb, ws, 'Operações');
  const instructions = [
    ['Coluna', 'Obrigatória?', 'Formatos aceitos'],
    ...IMPORT_FIELDS.map((f) => [f.label, f.required ? 'Sim' : 'Não', f.hint]),
    ['', '', ''],
    ['Regras', '', ''],
    ['WIN', '', 'Lucro = entrada × payout%'],
    ['LOSS', '', 'Lucro = -entrada'],
    ['DRAW', '', 'Lucro = 0'],
    ['', '', 'O mapeamento de colunas é ajustável na tela de importação.'],
    ['', '', 'Este modelo contém apenas cabeçalhos — nenhum dado fictício.'],
  ];
  const wi = XLSX.utils.aoa_to_sheet(instructions);
  wi['!cols'] = [{ wch: 24 }, { wch: 16 }, { wch: 78 }];
  XLSX.utils.book_append_sheet(wb, wi, 'Instruções');
  XLSX.writeFile(wb, 'modelo-importacao-trading.xlsx');
}
