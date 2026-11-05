import React, { useMemo, useState } from 'react';
import {
  LayoutDashboard, Wallet, SlidersHorizontal, ListOrdered, CalendarDays,
  BarChart3, Target, Layers3, History, Settings2, Table2, Plus, Sun, Moon,
  Menu, FlaskConical, TrendingUp, ShieldCheck, ChevronLeft, ChevronRight,
} from 'lucide-react';
import { StoreProvider, useStore, type PageId } from './state/store';
import { OperationEditor } from './components/OperationForm';
import { Toasts } from './components/ui';
import { money, formatDate, addDays } from './lib/format';
import { currentBalance } from './lib/calc';
import { todayISO } from './lib/defaults';

import { DashboardPage } from './pages/Dashboard';
import { BancaPage } from './pages/Banca';
import { GerenciamentoPage } from './pages/Gerenciamento';
import { OperacoesPage } from './pages/Operacoes';
import { DiarioPage } from './pages/Diario';
import { RelatoriosPage } from './pages/Relatorios';
import { EstrategiasPage } from './pages/Estrategias';
import { MetasPage } from './pages/Metas';
import { HistoricoPage } from './pages/Historico';
import { SeriesPage } from './pages/Series';
import { ConfiguracoesPage } from './pages/Configuracoes';

const NAV: { group: string; items: { id: PageId; label: string; icon: React.ReactNode }[] }[] = [
  {
    group: 'Visão geral', items: [
      { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard size={16} /> },
      { id: 'diario', label: 'Resultados diários', icon: <CalendarDays size={16} /> },
      { id: 'relatorios', label: 'Relatórios & estatísticas', icon: <BarChart3 size={16} /> },
      { id: 'series', label: 'Planilha / Micro séries', icon: <Table2 size={16} /> },
    ],
  },
  {
    group: 'Gestão', items: [
      { id: 'banca', label: 'Gerenciamento de banca', icon: <Wallet size={16} /> },
      { id: 'gerenciamento', label: 'Gerenciamento de entradas', icon: <SlidersHorizontal size={16} /> },
      { id: 'estrategias', label: 'Estratégias', icon: <Layers3 size={16} /> },
      { id: 'metas', label: 'Metas & planejamento', icon: <Target size={16} /> },
    ],
  },
  {
    group: 'Registros', items: [
      { id: 'operacoes', label: 'Registro de operações', icon: <ListOrdered size={16} /> },
      { id: 'historico', label: 'Histórico & dados', icon: <History size={16} /> },
      { id: 'configuracoes', label: 'Personalização', icon: <Settings2 size={16} /> },
    ],
  },
];

const TITLES: Record<PageId, { t: string; s: string }> = {
  dashboard: { t: 'Dashboard', s: 'Indicadores financeiros e operacionais em tempo real' },
  banca: { t: 'Gerenciamento de banca', s: 'Capital, limites de risco e movimentações' },
  gerenciamento: { t: 'Gerenciamento de entradas', s: 'Modalidades, ciclos e cálculo da próxima entrada' },
  operacoes: { t: 'Registro de operações', s: 'Cadastro, edição e correção de cada operação' },
  diario: { t: 'Resultados diários', s: 'Calendário interativo e desempenho por dia' },
  relatorios: { t: 'Relatórios & estatísticas', s: 'Análise interativa por período, ativo e estratégia' },
  estrategias: { t: 'Estratégias', s: 'Cadastro, desempenho e ranking por histórico real' },
  metas: { t: 'Metas & planejamento', s: 'Objetivos, progresso e projeções de crescimento' },
  historico: { t: 'Histórico & segurança dos dados', s: 'Filtros, exportação, backup e restauração' },
  series: { t: 'Planilha / Micro séries', s: 'Visão em planilha inspirada no modelo enviado' },
  configuracoes: { t: 'Personalização completa', s: 'Aparência, moeda, cards e preferências' },
};

function Shell() {
  const store = useStore();
  const { data, setData, page, setPage, ops, openOpEditor, refDate, setRefDate, includeDemo, setIncludeDemo, sidebarOpen, setSidebarOpen, storageError } = store;
  const balance = useMemo(() => currentBalance(data, ops), [data, ops]);
  const demoCount = data.operations.filter((o) => o.demo).length;
  const [showDate, setShowDate] = useState(false);

  const go = (p: PageId) => { setPage(p); setSidebarOpen(false); window.scrollTo({ top: 0, behavior: 'smooth' }); };

  const toggleTheme = () => setData((d) => ({ ...d, settings: { ...d.settings, theme: d.settings.theme === 'dark' ? 'light' : 'dark' } }));

  return (
    <div className="app-shell">
      <div className={`sidebar-overlay ${sidebarOpen ? 'show' : ''}`} onClick={() => setSidebarOpen(false)} />
      <aside className={`sidebar ${sidebarOpen ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark"><TrendingUp size={20} strokeWidth={2.6} /></div>
          <div style={{ minWidth: 0 }}>
            <div className="brand-name" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{data.settings.platformName}</div>
            <div className="brand-sub">{data.settings.platformSubtitle}</div>
          </div>
        </div>
        <div className="sidebar-scroll">
          {NAV.map((g) => (
            <React.Fragment key={g.group}>
              <div className="nav-group-label">{g.group}</div>
              {g.items.map((item) => (
                <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => go(item.id)}>
                  {item.icon}<span>{item.label}</span>
                  {item.id === 'operacoes' && ops.length > 0 && <span className="nav-count">{ops.length}</span>}
                </button>
              ))}
            </React.Fragment>
          ))}
          <div className="nav-group-label">Atalhos</div>
          <button className="nav-item" onClick={() => { openOpEditor('new'); setSidebarOpen(false); }}>
            <Plus size={16} /><span>Nova operação</span>
          </button>
          <button className="nav-item" onClick={() => go('configuracoes')}>
            <ShieldCheck size={16} /><span>Backup & segurança</span>
          </button>
        </div>
        <div className="sidebar-foot">
          <div className="storage-chip"><span className="dot" style={{ background: storageError ? 'var(--neg)' : 'var(--pos)' }} />
            {storageError ? 'Armazenamento cheio' : 'Dados salvos localmente'}
          </div>
          <div className="tiny muted mt-8">v1.0 · sem servidor · 100% local</div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <button className="icon-btn mobile-menu" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Menu"><Menu size={17} /></button>
          <div>
            <h1>{TITLES[page].t}</h1>
            <div className="topbar-sub">{TITLES[page].s}</div>
          </div>
          <div className="topbar-spacer" />

          <div className="row" style={{ gap: 5 }}>
            <button className="icon-btn" title="Dia anterior" onClick={() => setRefDate(addDays(refDate, -1))}><ChevronLeft size={15} /></button>
            <button className="btn sm" onClick={() => setShowDate(!showDate)} title="Selecionar data de referência">
              <CalendarDays size={13} /> {formatDate(refDate, data.settings)}
            </button>
            <button className="icon-btn" title="Próximo dia" onClick={() => setRefDate(addDays(refDate, 1))}><ChevronRight size={15} /></button>
            {showDate && <input type="date" className="input" style={{ width: 155 }} value={refDate} onChange={(e) => { setRefDate(e.target.value || todayISO()); setShowDate(false); }} />}
          </div>

          <div className="pill" title="Saldo calculado a partir dos registros reais">
            Banca <strong className={balance >= data.settings.initialBalance ? 'value-pos' : 'value-neg'}>{money(balance, data.settings)}</strong>
          </div>

          <button className={`icon-btn ${includeDemo ? 'active' : ''}`} title={includeDemo ? 'Ocultar simulações' : 'Incluir simulações'} onClick={() => setIncludeDemo(!includeDemo)}>
            <FlaskConical size={16} />
          </button>
          {demoCount > 0 && includeDemo && <span className="badge badge-demo">SIMULAÇÃO ATIVA</span>}
          <button className="icon-btn" title={data.settings.theme === 'dark' ? 'Tema claro' : 'Tema escuro'} onClick={toggleTheme}>
            {data.settings.theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button className="btn primary sm" onClick={() => openOpEditor('new')}><Plus size={15} /> Nova operação</button>
        </header>

        <main className="content">
          {data.settings.showDemoBanner && demoCount > 0 && includeDemo && (
            <div className="demo-banner">
              <FlaskConical size={17} color="#a78bfa" />
              <div><strong>Modo de demonstração ativo.</strong> Os {demoCount} registros com selo SIMULAÇÃO estão incluídos nos cálculos desta sessão de visualização. Desative o ícone de laboratório no topo para ver apenas dados reais.</div>
            </div>
          )}
          {storageError && (
            <div className="notice danger mb-14"><ShieldCheck size={15} /><div><b>Atenção:</b> não foi possível salvar os dados ({storageError}). Exporte um backup em Histórico & dados antes de fechar a página.</div></div>
          )}
          {page === 'dashboard' && <DashboardPage />}
          {page === 'banca' && <BancaPage />}
          {page === 'gerenciamento' && <GerenciamentoPage />}
          {page === 'operacoes' && <OperacoesPage />}
          {page === 'diario' && <DiarioPage />}
          {page === 'relatorios' && <RelatoriosPage />}
          {page === 'estrategias' && <EstrategiasPage />}
          {page === 'metas' && <MetasPage />}
          {page === 'historico' && <HistoricoPage />}
          {page === 'series' && <SeriesPage />}
          {page === 'configuracoes' && <ConfiguracoesPage />}
        </main>
      </div>

      <OperationEditor />
      <Toasts />
    </div>
  );
}

export default function App() {
  return <StoreProvider><Shell /></StoreProvider>;
}
