import React, { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import type { AppData, Operation, Strategy, LedgerEntry, GrowthPlan } from '../types';
import { loadData, saveData, wipeData } from '../lib/storage';
import { defaultData, uid, todayISO, calcProfit, round2, hydrate } from '../lib/defaults';
import { addDays } from '../lib/format';

export type PageId =
  | 'dashboard' | 'banca' | 'gerenciamento' | 'operacoes' | 'diario'
  | 'relatorios' | 'estrategias' | 'metas' | 'historico' | 'series' | 'configuracoes';

interface Toast { id: string; text: string; kind: 'success' | 'error' | 'info' }

interface StoreValue {
  data: AppData;
  setData: (fn: (d: AppData) => AppData) => void;
  /** Dados visíveis conforme o filtro de simulação */
  ops: Operation[];
  allOps: Operation[];
  page: PageId;
  setPage: (p: PageId) => void;
  refDate: string;
  setRefDate: (d: string) => void;
  range: { from: string; to: string };
  setRange: (r: { from: string; to: string }) => void;
  includeDemo: boolean;
  setIncludeDemo: (v: boolean) => void;
  toasts: Toast[];
  toast: (text: string, kind?: Toast['kind']) => void;
  dismissToast: (id: string) => void;
  saveOp: (op: Operation) => void;
  deleteOp: (id: string) => void;
  duplicateOp: (op: Operation) => void;
  saveStrategy: (s: Strategy) => void;
  deleteStrategy: (id: string) => void;
  addLedger: (l: Omit<LedgerEntry, 'id' | 'createdAt'>) => void;
  deleteLedger: (id: string) => void;
  savePlan: (p: GrowthPlan) => void;
  deletePlan: (id: string) => void;
  resetAll: () => void;
  restore: (raw: unknown) => boolean;
  storageError: string | null;
  loadDemo: (ops: Operation[]) => void;
  removeDemo: () => void;
  sidebarOpen: boolean;
  setSidebarOpen: (v: boolean) => void;
  opEditor: Operation | 'new' | null;
  openOpEditor: (op: Operation | 'new') => void;
  closeOpEditor: () => void;
}

const Ctx = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [data, setDataState] = useState<AppData>(() => loadData());
  const [page, setPage] = useState<PageId>('dashboard');
  const [refDate, setRefDate] = useState(todayISO());
  const [range, setRange] = useState<{ from: string; to: string }>(() => ({ from: addDays(todayISO(), -(loadData().settings.charts?.defaultRangeDays || 30)), to: todayISO() }));
  const [includeDemo, setIncludeDemo] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [opEditor, setOpEditor] = useState<Operation | 'new' | null>(null);
  const [storageError, setStorageError] = useState<string | null>(null);
  const first = useRef(true);

  const setData = useCallback((fn: (d: AppData) => AppData) => {
    setDataState((prev) => fn(prev));
  }, []);

  useEffect(() => {
    if (first.current) { first.current = false; return; }
    const res = saveData(data);
    setStorageError(res.ok ? null : res.error || 'Erro ao salvar no navegador');
  }, [data]);

  // Aplica tema + cores personalizadas
  useEffect(() => {
    const root = document.documentElement;
    const s = data.settings;
    root.dataset.theme = s.theme;
    root.style.setProperty('--accent', s.accent);
    root.style.setProperty('--pos', s.positive);
    root.style.setProperty('--neg', s.negative);
    document.title = s.platformName;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', s.theme === 'dark' ? '#0a0f1c' : '#f5f7fb');
  }, [data.settings.theme, data.settings.accent, data.settings.positive, data.settings.negative, data.settings.platformName]);

  const toast = useCallback((text: string, kind: Toast['kind'] = 'success') => {
    const id = uid();
    setToasts((t) => [...t, { id, text, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4200);
  }, []);
  const dismissToast = useCallback((id: string) => setToasts((t) => t.filter((x) => x.id !== id)), []);

  const allOps = data.operations;
  const ops = useMemo(() => data.operations.filter((o) => includeDemo || !o.demo), [data.operations, includeDemo]);

  const saveOp = useCallback((op: Operation) => {
    setData((d) => {
      const exists = d.operations.some((o) => o.id === op.id);
      const normalized: Operation = {
        ...op,
        profit: op.profitEdited ? round2(op.profit) : calcProfit(Number(op.entry) || 0, Number(op.payout) || 0, op.result),
        updatedAt: Date.now(),
      };
      return {
        ...d,
        operations: exists
          ? d.operations.map((o) => (o.id === op.id ? normalized : o))
          : [...d.operations, normalized],
      };
    });
  }, [setData]);

  const deleteOp = useCallback((id: string) => setData((d) => ({ ...d, operations: d.operations.filter((o) => o.id !== id) })), [setData]);

  const duplicateOp = useCallback((op: Operation) => {
    const copy: Operation = { ...op, id: uid(), createdAt: Date.now(), updatedAt: undefined, date: todayISO(), time: new Date().toTimeString().slice(0, 5) };
    setData((d) => ({ ...d, operations: [...d.operations, copy] }));
    toast('Operação duplicada com data/horário atuais. Abra o registro para ajustar os campos.');
  }, [setData, toast]);

  const saveStrategy = useCallback((s: Strategy) => setData((d) => ({
    ...d,
    strategies: d.strategies.some((x) => x.id === s.id)
      ? d.strategies.map((x) => (x.id === s.id ? s : x))
      : [...d.strategies, s],
  })), [setData]);

  const deleteStrategy = useCallback((id: string) => setData((d) => ({
    ...d,
    strategies: d.strategies.filter((s) => s.id !== id),
    operations: d.operations.map((o) => (o.strategyId === id ? { ...o, strategyId: '' } : o)),
  })), [setData]);

  const addLedger = useCallback((l: Omit<LedgerEntry, 'id' | 'createdAt'>) => setData((d) => ({
    ...d, ledger: [...d.ledger, { ...l, id: uid(), createdAt: Date.now() }],
  })), [setData]);

  const deleteLedger = useCallback((id: string) => setData((d) => ({ ...d, ledger: d.ledger.filter((l) => l.id !== id) })), [setData]);

  const savePlan = useCallback((p: GrowthPlan) => setData((d) => ({
    ...d,
    plans: d.plans.some((x) => x.id === p.id) ? d.plans.map((x) => (x.id === p.id ? p : x)) : [...d.plans, p],
  })), [setData]);

  const deletePlan = useCallback((id: string) => setData((d) => ({ ...d, plans: d.plans.filter((p) => p.id !== id) })), [setData]);

  const resetAll = useCallback(() => {
    wipeData();
    setDataState(defaultData());
    setIncludeDemo(false);
    toast('Todos os dados foram apagados.');
  }, [toast]);

  const restore = useCallback((raw: unknown): boolean => {
    try {
      const candidate = raw && typeof raw === 'object' && 'data' in (raw as object)
        ? (raw as { data: unknown }).data : raw;
      const restored = hydrate(candidate);
      if (!restored || !Array.isArray(restored.operations) || !restored.settings) throw new Error('estrutura inválida');
      // Nada é gravado antes da validação: o efeito de persistência salva o estado já higienizado.
      setDataState(restored);
      toast('Backup restaurado com sucesso.');
      return true;
    } catch (e) {
      toast('Arquivo de backup inválido.', 'error');
      console.error(e);
      return false;
    }
  }, [toast]);

  const loadDemo = useCallback((demoOps: Operation[]) => setData((d) => ({
    ...d, operations: [...d.operations.filter((o) => !o.demo), ...demoOps],
  })), [setData]);

  const removeDemo = useCallback(() => setData((d) => ({ ...d, operations: d.operations.filter((o) => !o.demo) })), [setData]);

  const openOpEditor = useCallback((op: Operation | 'new') => setOpEditor(op), []);
  const closeOpEditor = useCallback(() => setOpEditor(null), []);

  const value: StoreValue = {
    data, setData, ops, allOps, page, setPage, refDate, setRefDate, range, setRange,
    includeDemo, setIncludeDemo, toasts, toast, dismissToast, saveOp, deleteOp, duplicateOp,
    saveStrategy, deleteStrategy, addLedger, deleteLedger, savePlan, deletePlan,
    resetAll, restore, storageError, loadDemo, removeDemo, sidebarOpen, setSidebarOpen,
    opEditor, openOpEditor, closeOpEditor,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): StoreValue {
  const v = useContext(Ctx);
  if (!v) throw new Error('useStore deve ser usado dentro de StoreProvider');
  return v;
}
