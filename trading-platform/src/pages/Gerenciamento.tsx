import React, { useMemo, useState } from 'react';
import {
  Layers, Percent, Repeat2, StepForward, GitBranch, FlaskConical, Wand2,
  ShieldCheck, AlertTriangle, CircleDollarSign, Info,
} from 'lucide-react';
import { useStore } from '../state/store';
import { Card, CardHead, Field, NumberField, PageHeader, Notice, StatCard, Toggle, ResultBadge } from '../components/ui';
import { suggestEntry } from '../lib/calc';
import { money, pct } from '../lib/format';
import { todayISO, uid, calcProfit } from '../lib/defaults';
import type { ManagementMode, ManagementConfig, Operation, TradeResult, AppData } from '../types';

const MODES: { id: ManagementMode; label: string; desc: string; icon: React.ReactNode }[] = [
  { id: 'fixed', label: 'Valor fixo', desc: 'Mesmo valor em todas as entradas.', icon: <CircleDollarSign size={17} /> },
  { id: 'percent', label: '% da banca', desc: 'Percentual do saldo de abertura.', icon: <Percent size={17} /> },
  { id: 'sorosN1', label: 'Soros N1', desc: 'Reinveste o lucro por 1 nível.', icon: <Repeat2 size={17} /> },
  { id: 'sorosN2', label: 'Soros N2', desc: 'Reinveste o lucro por 2 níveis.', icon: <Repeat2 size={17} /> },
  { id: 'sorosCustom', label: 'Soros personalizado', desc: 'Níveis e % de reinvestimento livres.', icon: <GitBranch size={17} /> },
  { id: 'martingale', label: 'Martingale', desc: 'Multiplica após LOSS, com teto de níveis.', icon: <StepForward size={17} /> },
  { id: 'custom', label: 'Personalizado', desc: 'Sequência própria de multiplicadores ou valores.', icon: <Layers size={17} /> },
];

export function GerenciamentoPage() {
  const { data, setData, ops, refDate, toast } = useStore();
  const s = data.settings;
  const active = s.activeManagement;
  const cfg = s.management[active];
  const [sequence, setSequence] = useState('W W L W W L W');

  const setMode = (mode: ManagementMode) => setData((d) => ({ ...d, settings: { ...d.settings, activeManagement: mode } }));
  const setCfg = (patch: Partial<ManagementConfig>) => setData((d) => {
    const management = { ...d.settings.management, [active]: { ...d.settings.management[active], ...patch } };
    return { ...d, settings: { ...d.settings, management } };
  });

  const suggestion = useMemo(() => suggestEntry(data, ops, refDate), [data, ops, refDate]);
  const dayOpen = suggestion.value; // apenas para manter memo estável

  const simulation = useMemo(() => {
    const seq: TradeResult[] = sequence.toUpperCase().split(/[\s,;\-]+/).filter(Boolean)
      .map((c) => c.startsWith('W') ? 'WIN' : c.startsWith('L') ? 'LOSS' : 'DRAW');
    const fake: Operation[] = [];
    const temp: AppData = { ...data, operations: fake, ledger: [], settings: { ...s, activeManagement: active } };
    const rows: { i: number; result: TradeResult; stake: number; profit: number; balance: number; note: string }[] = [];
    let balance = s.initialBalance;
    for (let i = 0; i < seq.length; i++) {
      const sg = suggestEntry(temp, fake, todayISO());
      const stake = sg.value;
      const profit = calcProfit(stake, 85, seq[i]);
      balance += profit;
      rows.push({ i: i + 1, result: seq[i], stake, profit, balance, note: sg.explanation });
      fake.push({
        id: uid(), date: todayISO(), time: String(10 + i).padStart(2, '0') + ':00', asset: 'SIMULAÇÃO',
        market: 'Normal', direction: 'CALL', strategyId: '', timeframe: 'M1', expiry: '1m',
        entry: stake, payout: 85, result: seq[i], profit, notes: '', demo: true,
        createdAt: Date.now() + i, seriesId: 'simulação',
      });
    }
    return rows;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence, data.settings.initialBalance, data.settings.baseEntry, data.settings.maxEntry, data.settings.minEntry, data.settings.riskPercent, data.settings.management, active, s]);

  const renderConfig = () => {
    switch (active) {
      case 'fixed': return <>
        <NumberField label="Valor fixo por entrada" value={cfg.fixedValue} onChange={(v) => setCfg({ fixedValue: v })} step={0.01} prefix={s.currencySymbol} hint="Será limitado pelo teto e pelo risco por operação." />
        <div className="field"><label className="field-label">Comportamento</label><div className="notice"><Info size={14} /><div>Cada operação usa exatamente o valor configurado, independentemente do resultado anterior.</div></div></div>
      </>;
      case 'percent': return <>
        <NumberField label="Percentual da banca" value={cfg.percentValue} onChange={(v) => setCfg({ percentValue: v })} step={0.1} suffix="%" hint={`Sobre ${money(s.initialBalance, s)} = ${money((s.initialBalance * cfg.percentValue) / 100, s)}`} />
        <div className="field"><label className="field-label">Base de cálculo</label><div className="notice"><Info size={14} /><div>Saldo de abertura do dia (banca inicial + movimentações + resultados até o dia anterior). O valor se ajusta automaticamente à evolução da banca.</div></div></div>
      </>;
      case 'sorosN1': case 'sorosN2': case 'sorosCustom': return <>
        <NumberField label="Níveis antes de resetar" value={active === 'sorosN1' ? 1 : active === 'sorosN2' ? 2 : cfg.sorosLevels}
          onChange={(v) => setCfg({ sorosLevels: v })} disabled={active !== 'sorosCustom'} hint={active === 'sorosCustom' ? 'Soros personalizado: quantidade de vitórias por ciclo' : 'Nível fixo desta modalidade pré-definida'} />
        <NumberField label="% do lucro reinvestido" value={cfg.sorosUsePercent} onChange={(v) => setCfg({ sorosUsePercent: v })} step={5} suffix="%" hint="100% = valor base + todo o lucro do ciclo" />
        <div className="field"><label className="field-label">Reiniciar ciclo após LOSS</label><div style={{ paddingTop: 4 }}><Toggle checked={cfg.sorosResetOnLoss} onChange={(v) => setCfg({ sorosResetOnLoss: v })} label="Voltar ao valor base" /></div></div>
        <div className="field"><label className="field-label">Regra</label><div className="notice"><Info size={14} /><div>Após um WIN, o lucro é somado ao valor base. Ao atingir o número de níveis (ou sofrer um LOSS), o ciclo reinicia no valor base.</div></div></div>
      </>;
      case 'martingale': return <>
        <NumberField label="Multiplicador" value={cfg.martingaleMultiplier} onChange={(v) => setCfg({ martingaleMultiplier: v })} step={0.1} hint="Aplicado a cada LOSS consecutivo" />
        <NumberField label="Máximo de níveis" value={cfg.martingaleMaxLevels} onChange={(v) => setCfg({ martingaleMaxLevels: v })} hint="Ao atingir, o ciclo volta ao valor base" />
        <div className="field"><label className="field-label">Reiniciar após WIN</label><div style={{ paddingTop: 4 }}><Toggle checked={cfg.martingaleResetOnWin} onChange={(v) => setCfg({ martingaleResetOnWin: v })} label="Voltar ao valor base depois de um WIN" /></div></div>
        <div className="field"><label className="field-label">Atenção</label><div className="notice warn"><AlertTriangle size={14} /><div>Martingale cresce exponencialmente. O sistema aplica o teto por operação e o risco máximo antes de sugerir qualquer valor.</div></div></div>
      </>;
      case 'custom': return <>
        <Field label="Sequência de passos" hint="Separe por vírgula. Ex.: 1,1.5,2,3 ou 10,20,35">
          <input className="input mono" value={cfg.customSteps} onChange={(e) => setCfg({ customSteps: e.target.value })} />
        </Field>
        <div className="field"><label className="field-label">Interpretar como</label>
          <div className="mode-toggle">
            <button type="button" className={!cfg.customStepsAreValues ? 'on' : ''} onClick={() => setCfg({ customStepsAreValues: false })}>Multiplicadores da base</button>
            <button type="button" className={cfg.customStepsAreValues ? 'on' : ''} onClick={() => setCfg({ customStepsAreValues: true })}>Valores absolutos</button>
          </div>
          <span className="field-hint">O passo avança a cada operação e volta ao primeiro quando o ciclo reinicia (LOSS).</span>
        </div>
      </>;
    }
  };

  return (
    <>
      <PageHeader title="Gerenciamento de entradas" description="Escolha uma modalidade, configure-a de forma independente e acompanhe o cálculo automático da próxima entrada. Todos os limites de risco são respeitados antes de qualquer sugestão." />

      <div className="section-title">Modalidades — cada uma com configuração própria</div>
      <div className="grid grid-4 mb-14">
        {MODES.map((mo) => (
          <button key={mo.id} className={`card stat-card ${active === mo.id ? 'value-accent' : ''}`}
            style={{ textAlign: 'left', borderColor: active === mo.id ? 'var(--accent)' : undefined, minHeight: 118, background: active === mo.id ? 'var(--accent-soft)' : undefined }}
            onClick={() => setMode(mo.id)}>
            <div className="stat-top" style={{ color: active === mo.id ? 'var(--accent)' : undefined }}>{mo.icon}{mo.label}</div>
            <div className="small muted" style={{ lineHeight: 1.5, marginTop: 8 }}>{mo.desc}</div>
            {active === mo.id && <div className="badge badge-accent mt-8" style={{ alignSelf: 'flex-start' }}>Ativa</div>}
          </button>
        ))}
      </div>

      <div className="grid grid-2">
        <Card>
          <CardHead title={`Configuração · ${MODES.find((x) => x.id === active)?.label}`} sub="Alterações salvas automaticamente e isoladas das outras modalidades" />
          <div className="form-grid">{renderConfig()}</div>
          <div className="divider" />
          <div className="small muted">Parâmetros globais (em Banca): valor base <b className="mono">{money(s.baseEntry, s)}</b>, mínimo <b className="mono">{money(s.minEntry, s)}</b>, máximo <b className="mono">{money(s.maxEntry, s)}</b>, risco <b>{s.riskPercent}%</b>.</div>
        </Card>

        <Card>
          <CardHead title="Próxima entrada sugerida" sub={`Calculada a partir de ${ops.length} operação(ões) registrada(s)`} right={<Wand2 size={16} className="value-accent" />} />
          <div className="grid grid-2">
            <StatCard label="Valor sugerido" value={money(suggestion.value, s)} tone="accent" foot={`Bruto: ${money(suggestion.rawValue, s)} (antes dos limites)`} />
            <StatCard label="Posição no ciclo" value={suggestion.cycleLength + 1} foot={`Modalidade: ${MODES.find((x) => x.id === active)?.label}`} />
          </div>
          <div className="mt-14"><div className="field-label mb-8">Como o valor foi calculado</div>
            <div className="notice"><Info size={14} /><div>{suggestion.explanation}</div></div>
          </div>
          <div className="divider" />
          <div className="field-label mb-8">Limites aplicados</div>
          {suggestion.limits.warnings.length === 0
            ? <div className="notice"><ShieldCheck size={14} /><div>Nenhum limite violado. A entrada sugerida respeita risco, teto, exposição, stops e limites de sequência.</div></div>
            : <div className="notice warn"><AlertTriangle size={14} /><div><ul style={{ margin: 0, paddingLeft: 16, lineHeight: 1.8 }}>{suggestion.limits.warnings.map((w, i) => <li key={i}>{w.label} <span className="tag">{w.level === 'block' ? 'bloqueio' : 'ajuste'}</span></li>)}</ul></div></div>}
          <div className="divider" />
          <Toggle checked={s.requireLimitConfirmation} onChange={(v) => setData((d) => ({ ...d, settings: { ...d.settings, requireLimitConfirmation: v } }))}
            label="Exigir confirmação explícita para ultrapassar limites" />
          <div className="field-hint mt-8">Quando ativo, o registro de uma operação fora das regras só é aceito após o usuário marcar a autorização no formulário.</div>
        </Card>
      </div>

      <div className="section-title">Simulador de ciclo</div>
      <Card>
        <div className="row wrap mb-14">
          <div className="field" style={{ flex: 1, minWidth: 260 }}>
            <label className="field-label">Sequência hipotética de resultados (W / L / D)</label>
            <input className="input mono" value={sequence} onChange={(e) => setSequence(e.target.value)} placeholder="Ex.: W W L W W L W" />
          </div>
          <button className="btn" onClick={() => setSequence('W W W W W')}>5 WIN</button>
          <button className="btn" onClick={() => setSequence('L L L W L')}>LOSS seguidos</button>
          <button className="btn" onClick={() => toast('Simulação recalculada com a configuração atual.', 'info')}><FlaskConical size={14} /> Recalcular</button>
        </div>
        <Notice kind="warn"><b>Simulação matemática.</b> Esta tabela usa payout hipotético de 85% e resultados inventados apenas para demonstrar o comportamento da modalidade. Nenhum valor aqui é registrado como operação real e isto não representa garantia de resultados futuros.</Notice>
        <div className="table-wrap mt-14">
          <table className="table">
            <thead><tr><th>#</th><th>Resultado hipotético</th><th className="num">Entrada sugerida</th><th className="num">Resultado financeiro</th><th className="num">Saldo simulado</th><th>Regra aplicada</th></tr></thead>
            <tbody>
              {simulation.length === 0 && <tr><td colSpan={6} className="center muted" style={{ padding: 20 }}>Digite uma sequência acima</td></tr>}
              {simulation.map((r) => (
                <tr key={r.i}>
                  <td className="mono">{r.i}</td><td><ResultBadge result={r.result} /></td>
                  <td className="num strong">{money(r.stake, s)}</td>
                  <td className={`num ${r.profit >= 0 ? 'value-pos' : 'value-neg'}`}>{money(r.profit, s, { signed: true })}</td>
                  <td className="num">{money(r.balance, s)}</td>
                  <td className="muted small" style={{ whiteSpace: 'normal', maxWidth: 340 }}>{r.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
