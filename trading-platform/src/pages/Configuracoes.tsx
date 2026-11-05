import React from 'react';
import {
  Palette, Coins, LayoutGrid, ShieldCheck, ArrowUp, ArrowDown, Eye, EyeOff,
  RotateCcw, Wallet, SlidersHorizontal, Target, Layers3, Database, Sun, Moon, Monitor,
} from 'lucide-react';
import { useStore } from '../state/store';
import { PageHeader, Card, CardHead, Field, Segmented, Notice, Toggle } from '../components/ui';
import { money, formatDate } from '../lib/format';
import { DASHBOARD_CARDS, OP_COLUMNS, defaultSettings } from '../lib/defaults';
import type { DashboardCardDef } from '../types';

const CURRENCIES = [
  { code: 'BRL', symbol: 'R$', locale: 'pt-BR', label: 'Real brasileiro (BRL)' },
  { code: 'USD', symbol: '$', locale: 'en-US', label: 'Dólar americano (USD)' },
  { code: 'EUR', symbol: '€', locale: 'de-DE', label: 'Euro (EUR)' },
  { code: 'GBP', symbol: '£', locale: 'en-GB', label: 'Libra esterlina (GBP)' },
  { code: 'ARS', symbol: 'AR$', locale: 'es-AR', label: 'Peso argentino (ARS)' },
  { code: 'JPY', symbol: '¥', locale: 'ja-JP', label: 'Iene (JPY)' },
];
const ACCENTS = ['#21d4a8', '#38bdf8', '#8b5cf6', '#f59e0b', '#f43f5e', '#34d399', '#fb7185', '#60a5fa'];

export function ConfiguracoesPage() {
  const { data, setData, setPage, setRange, toast } = useStore();
  const s = data.settings;
  const set = <K extends keyof typeof s>(k: K, v: typeof s[K]) => setData((d) => ({ ...d, settings: { ...d.settings, [k]: v } }));

  const setCards = (cards: DashboardCardDef[]) => set('dashboardCards', cards);
  const moveCard = (id: string, dir: -1 | 1) => {
    const list = [...s.dashboardCards];
    const i = list.findIndex((c) => c.id === id);
    const j = i + dir;
    if (j < 0 || j >= list.length) return;
    [list[i], list[j]] = [list[j], list[i]];
    setCards(list);
  };

  return (
    <>
      <PageHeader title="Personalização completa" description="Praticamente todos os elementos são configuráveis: identidade, tema, cores, moeda, formato de datas, cards, colunas e campos. As preferências são salvas automaticamente e permanecem após atualizar ou fechar a página." />

      <div className="grid grid-2">
        <Card>
          <CardHead title="Identidade & aparência" sub="Nome, tema e paleta de cores" right={<Palette size={15} className="muted" />} />
          <div className="form-grid">
            <Field label="Nome da plataforma"><input className="input" value={s.platformName} onChange={(e) => set('platformName', e.target.value)} /></Field>
            <Field label="Subtítulo"><input className="input" value={s.platformSubtitle} onChange={(e) => set('platformSubtitle', e.target.value)} /></Field>
          </div>
          <div className="divider" />
          <Field label="Tema">
            <div className="row wrap" style={{ gap: 8 }}>
              {([['dark', 'Escuro', <Moon size={14} key="m" />], ['light', 'Claro', <Sun size={14} key="s" />]] as const).map(([v, label, icon]) => (
                <button key={v} className={`btn ${s.theme === v ? 'primary' : ''}`} onClick={() => set('theme', v)}>{icon} {label}</button>
              ))}
              <span className="tiny muted" style={{ alignSelf: 'center' }}><Monitor size={12} style={{ verticalAlign: 'middle' }} /> alternância rápida também no topo</span>
            </div>
          </Field>
          <div className="divider" />
          <div className="form-grid cols-3">
            <Field label="Cor de destaque"><input type="color" className="input" value={s.accent} onChange={(e) => set('accent', e.target.value)} /></Field>
            <Field label="Cor positiva"><input type="color" className="input" value={s.positive} onChange={(e) => set('positive', e.target.value)} /></Field>
            <Field label="Cor negativa"><input type="color" className="input" value={s.negative} onChange={(e) => set('negative', e.target.value)} /></Field>
          </div>
          <Field label="Paletas rápidas" hint="Clique para aplicar a cor de destaque">
            <div className="btn-row mt-8">{ACCENTS.map((c) => (
              <button key={c} className="icon-btn" style={{ background: c, border: s.accent === c ? '2px solid var(--text)' : '2px solid transparent', width: 30, height: 30 }} onClick={() => set('accent', c)} aria-label={`Cor ${c}`} />
            ))}</div>
          </Field>
          <div className="divider" />
          <div className="row wrap" style={{ gap: 10 }}>
            <span className="badge badge-accent">Destaque</span><span className="badge badge-win">Positivo</span><span className="badge badge-loss">Negativo</span>
            <span className="small muted">Pré-visualização: <b className="value-pos">{money(1234.56, s)}</b> / <b className="value-neg">{money(-1234.56, s)}</b></span>
          </div>
        </Card>

        <Card>
          <CardHead title="Moeda, idioma e formatação" sub="Aplicados a todos os valores e datas" right={<Coins size={15} className="muted" />} />
          <div className="form-grid">
            <Field label="Moeda">
              <select className="select" value={s.currency} onChange={(e) => {
                const c = CURRENCIES.find((x) => x.code === e.target.value) || CURRENCIES[0];
                setData((d) => ({ ...d, settings: { ...d.settings, currency: c.code, currencySymbol: c.symbol, locale: c.locale } }));
              }}>{CURRENCIES.map((c) => <option key={c.code} value={c.code}>{c.label}</option>)}</select>
            </Field>
            <Field label="Símbolo" hint="Editável para moedas personalizadas"><input className="input" value={s.currencySymbol} onChange={(e) => set('currencySymbol', e.target.value)} /></Field>
            <Field label="Localidade (formato numérico)">
              <select className="select" value={s.locale} onChange={(e) => set('locale', e.target.value)}>
                {['pt-BR', 'en-US', 'de-DE', 'es-ES', 'fr-FR', 'ja-JP'].map((l) => <option key={l}>{l}</option>)}
              </select>
            </Field>
            <Field label="Formato de datas">
              <select className="select" value={s.dateFormat} onChange={(e) => set('dateFormat', e.target.value)}>
                <option value="dd/MM/yyyy">dd/MM/yyyy</option><option value="MM/dd/yyyy">MM/dd/yyyy</option><option value="yyyy-MM-dd">yyyy-MM-dd</option>
              </select>
            </Field>
          </div>
          <div className="divider" />
          <div className="metric-line"><span className="label">Exemplo de valor</span><span className="val">{money(1234567.89, s)}</span></div>
          <div className="metric-line"><span className="label">Exemplo de data</span><span className="val">{formatDate('2026-11-05', s)}</span></div>
          <div className="divider" />
          <Toggle checked={s.compactNumbers} onChange={(v) => set('compactNumbers', v)} label="Usar números compactos em gráficos" />
          <div className="mt-8"><Toggle checked={s.showDemoBanner} onChange={(v) => set('showDemoBanner', v)} label="Exibir aviso quando simulações estiverem ativas" /></div>
        </Card>
      </div>

      <div className="section-title">Cards do dashboard</div>
      <Card>
        <CardHead title="Organização, visibilidade e largura" sub="Reordene com as setas, oculte/exiba e defina quantas colunas cada card ocupa" right={<LayoutGrid size={15} className="muted" />} />
        <div className="grid grid-2">
          {s.dashboardCards.map((c, i) => {
            const meta = DASHBOARD_CARDS.find((x) => x.id === c.id);
            return (
              <div className="card-order" key={c.id}>
                <span className="tiny mono muted">{String(i + 1).padStart(2, '0')}</span>
                <span className="name">{meta?.label || c.id}<div className="tiny muted">{meta?.group}</div></span>
                <div className="mode-toggle">
                  {([1, 2, 3, 4] as const).map((n) => <button key={n} className={c.span === n ? 'on' : ''} onClick={() => setCards(s.dashboardCards.map((x) => x.id === c.id ? { ...x, span: n } : x))}>{n}</button>)}
                </div>
                <button className="icon-btn" title="Subir" disabled={i === 0} onClick={() => moveCard(c.id, -1)}><ArrowUp size={13} /></button>
                <button className="icon-btn" title="Descer" disabled={i === s.dashboardCards.length - 1} onClick={() => moveCard(c.id, 1)}><ArrowDown size={13} /></button>
                <button className="icon-btn" title={c.visible ? 'Ocultar' : 'Exibir'} onClick={() => setCards(s.dashboardCards.map((x) => x.id === c.id ? { ...x, visible: !x.visible } : x))}>
                  {c.visible ? <Eye size={13} /> : <EyeOff size={13} />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="btn-row mt-14"><button className="btn" onClick={() => { setCards(DASHBOARD_CARDS.map((c) => ({ id: c.id, visible: true, span: c.defaultSpan }))); toast('Layout do dashboard restaurado.', 'info'); }}><RotateCcw size={14} /> Restaurar layout padrão</button></div>
      </Card>

      <div className="section-title">Colunas e campos</div>
      <div className="grid grid-2">
        <Card>
          <CardHead title="Colunas das tabelas de operações" sub="Preferência aplicada a todas as tabelas" />
          <div className="grid grid-2">
            {OP_COLUMNS.map((c) => (
              <label key={c.id} className="check-row">
                <input type="checkbox" checked={s.visibleColumns.includes(c.id)} onChange={(e) => set('visibleColumns', e.target.checked
                  ? OP_COLUMNS.map((x) => x.id).filter((id) => s.visibleColumns.includes(id) || id === c.id)
                  : s.visibleColumns.filter((id) => id !== c.id))} />
                {c.label}
              </label>
            ))}
          </div>
        </Card>
        <Card>
          <CardHead title="Campos opcionais do formulário" sub="Personalize o registro de operações" />
          <div className="grid grid-2">
            {Object.keys(s.opFields).map((k) => ({
              k, label: ({
                market: 'Tipo de mercado', direction: 'Direção CALL/PUT', strategy: 'Estratégia',
                timeframe: 'Timeframe', expiry: 'Tempo de expiração', notes: 'Observações',
                screenshot: 'Screenshot', series: 'Micro série',
              } as Record<string, string>)[k] || k,
            })).map((f) => (
              <label key={f.k} className="check-row">
                <input type="checkbox" checked={s.opFields[f.k] !== false}
                  onChange={(e) => set('opFields', { ...s.opFields, [f.k]: e.target.checked })} />
                {f.label}
              </label>
            ))}
          </div>
          <div className="divider" />
          <div className="small muted">Campos essenciais (data, horário, ativo, entrada, payout e resultado) são permanentes para garantir a consistência dos cálculos.</div>
        </Card>
      </div>

      <div className="section-title">Gráficos e filtros</div>
      <Card>
        <CardHead title="Preferências analíticas" sub="Aplicadas aos gráficos de todo o sistema" />
        <div className="grid grid-3">
          <div className="field"><label className="field-label">Linhas de grade</label>
            <div style={{ paddingTop: 6 }}><Toggle checked={s.charts.grid} onChange={(v) => set('charts', { ...s.charts, grid: v })} label="Exibir grade nos gráficos" /></div>
          </div>
          <div className="field"><label className="field-label">Animações</label>
            <div style={{ paddingTop: 6 }}><Toggle checked={s.charts.animations} onChange={(v) => set('charts', { ...s.charts, animations: v })} label="Animar séries" /></div>
          </div>
          <div className="field"><label className="field-label">Período padrão dos filtros</label>
            <div className="inline-value">
              <input className="input mono" type="number" min={1} max={730} value={s.charts.defaultRangeDays}
                onChange={(e) => set('charts', { ...s.charts, defaultRangeDays: Math.max(1, Number(e.target.value)) })} />
              <button className="btn" onClick={() => {
                const end = new Date(); const start = new Date(); start.setDate(start.getDate() - s.charts.defaultRangeDays);
                setRange({ from: start.toISOString().slice(0, 10), to: end.toISOString().slice(0, 10) });
                toast('Período padrão aplicado aos relatórios.', 'info');
              }}>Aplicar</button>
            </div>
            <span className="field-hint">Intervalo inicial usado em Relatórios & estatísticas (dias).</span>
          </div>
        </div>
        <div className="divider" />
        <div className="small muted">Números compactos nos eixos, cores de positivo/negativo e demais preferências visuais também afetam todos os gráficos.</div>
      </Card>

      <div className="section-title">Outras configurações</div>
      <div className="grid grid-4">
        {([
          { page: 'banca', label: 'Banca & limites de risco', desc: 'Capital, metas, stops e exposição', icon: <Wallet size={18} /> },
          { page: 'gerenciamento', label: 'Gerenciamento', desc: '7 modalidades independentes', icon: <SlidersHorizontal size={18} /> },
          { page: 'metas', label: 'Metas & planos', desc: 'Objetivos e projeções', icon: <Target size={18} /> },
          { page: 'estrategias', label: 'Estratégias', desc: 'Cadastro e ranking', icon: <Layers3 size={18} /> },
          { page: 'relatorios', label: 'Filtros e gráficos', desc: 'Intervalos de data e análises', icon: <LayoutGrid size={18} /> },
          { page: 'historico', label: 'Backup & dados', desc: 'Exportação e restauração', icon: <Database size={18} /> },
        ] as const).map((x) => (
          <button key={x.page} className="card stat-card" style={{ textAlign: 'left', minHeight: 116 }} onClick={() => setPage(x.page)}>
            <div className="stat-top" style={{ color: 'var(--accent)' }}>{x.icon}</div>
            <div><div className="strong" style={{ fontSize: 13, marginTop: 10 }}>{x.label}</div><div className="tiny muted mt-8">{x.desc}</div></div>
          </button>
        ))}
      </div>

      <div className="section-title">Preferências & dados</div>
      <Card>
        <div className="row between wrap" style={{ gap: 12 }}>
          <div className="small muted" style={{ maxWidth: 620, lineHeight: 1.7 }}>
            <ShieldCheck size={14} style={{ verticalAlign: 'middle', color: 'var(--accent)' }} /> Todas as configurações e registros são gravados no armazenamento local deste navegador.
            Para conservar seus dados em outro dispositivo, exporte um backup em <b>Histórico & dados</b>.
            Restaurar configurações de fábrica abaixo afeta <b>apenas a aparência e preferências</b> — nenhuma operação é apagada.
          </div>
          <button className="btn danger" onClick={() => {
            const fresh = defaultSettings();
            setData((d) => ({ ...d, settings: { ...d.settings,
              platformName: fresh.platformName, platformSubtitle: fresh.platformSubtitle, theme: fresh.theme,
              accent: fresh.accent, positive: fresh.positive, negative: fresh.negative,
              currency: fresh.currency, currencySymbol: fresh.currencySymbol, locale: fresh.locale,
              dateFormat: fresh.dateFormat, dashboardCards: fresh.dashboardCards,
              visibleColumns: fresh.visibleColumns, opFields: fresh.opFields,
            } }));
            toast('Preferências visuais restauradas. Operações preservadas.', 'info');
          }}><RotateCcw size={14} /> Restaurar preferências visuais</button>
        </div>
      </Card>
      <div className="mt-14"><Notice>Esta plataforma é uma ferramenta de registro e controle, não uma corretora. Ela não executa operações, não se conecta a mercados e não fornece recomendações de investimento.</Notice></div>
    </>
  );
}
