import React, { useMemo, useState } from 'react';
import { Wallet, Plus, ArrowDownToLine, ArrowUpFromLine, PiggyBank, Shield, Trash2, RefreshCw, Info } from 'lucide-react';
import { useStore } from '../state/store';
import { Card, CardHead, Field, NumberField, ModeValueField, PageHeader, Notice, StatCard, Toggle, Modal } from '../components/ui';
import { currentBalance, dashboardMetrics } from '../lib/calc';
import { money, formatDate, pct } from '../lib/format';
import { todayISO, uid } from '../lib/defaults';
import type { LedgerEntry } from '../types';

export function BancaPage() {
  const { data, setData, ops, refDate, addLedger, deleteLedger, toast } = useStore();
  const s = data.settings;
  const [movement, setMovement] = useState<{ type: LedgerEntry['type']; amount: string; note: string; date: string }>({ type: 'deposit', amount: '', note: '', date: todayISO() });
  const [confirmAdjust, setConfirmAdjust] = useState<number | null>(null);
  const [desiredBalance, setDesiredBalance] = useState('');

  const setSetting = <K extends keyof typeof s>(k: K, v: typeof s[K]) => setData((d) => ({ ...d, settings: { ...d.settings, [k]: v } }));

  const balance = useMemo(() => currentBalance(data, ops), [data, ops]);
  const m = useMemo(() => dashboardMetrics(data, ops, refDate), [data, ops, refDate]);
  const deposits = data.ledger.filter((l) => l.type === 'deposit').reduce((a, b) => a + b.amount, 0);
  const withdrawals = data.ledger.filter((l) => l.type === 'withdraw').reduce((a, b) => a + Math.abs(b.amount), 0);
  const adjustments = data.ledger.filter((l) => l.type === 'adjust').reduce((a, b) => a + b.amount, 0);
  const pnl = m.totalNet;
  const totalProfit = ops.reduce((a, b) => a + b.profit, 0);
  const reserved = Math.max(0, totalProfit) * (s.profitReservePercent / 100);

  const addMovement = () => {
    const value = Number(movement.amount);
    if (!Number.isFinite(value) || value <= 0) { toast('Informe um valor positivo.', 'error'); return; }
    addLedger({
      date: movement.date || todayISO(),
      type: movement.type,
      amount: movement.type === 'withdraw' ? -value : value,
      note: movement.note || (movement.type === 'deposit' ? 'Depósito adicional' : movement.type === 'withdraw' ? 'Retirada de lucros' : 'Ajuste manual de saldo'),
    });
    toast(movement.type === 'deposit' ? 'Depósito registrado.' : 'Retirada registrada.');
    setMovement({ ...movement, amount: '', note: '' });
  };

  return (
    <>
      <PageHeader title="Gerenciamento de banca" description="Todos os parâmetros de capital e risco são configuráveis e afetam imediatamente os cálculos, sugestões de entrada e alertas. O saldo é sempre derivado dos registros reais + movimentações." />

      <div className="grid grid-4 mb-14">
        <StatCard label="Saldo atual (calculado)" icon={<Wallet size={14} />} value={money(balance, s)} tone="accent" foot="Banca inicial + movimentações + resultados" />
        <StatCard label="Banca inicial" value={money(s.initialBalance, s)} foot={`${pct(s.initialBalance ? ((balance - s.initialBalance) / s.initialBalance) * 100 : 0, 2, true)} de variação`} />
        <StatCard label="Lucro reservado" value={money(reserved, s)} foot={`${s.profitReservePercent}% dos lucros (parâmetro configurável)`} />
        <StatCard label="Exposição / risco por entrada" value={money((balance * s.riskPercent) / 100, s)} foot={`${s.riskPercent}% · teto ${money(s.maxEntry, s)}`} />
      </div>

      <div className="section-title">Composição do saldo</div>
      <Card className="mb-14">
        <div className="grid grid-4">
          {[
            ['Banca inicial', s.initialBalance], ['Depósitos', deposits], ['Retiradas', -withdrawals],
            ['Ajustes', adjustments], ['Resultado das operações', pnl], ['= Saldo atual', balance],
          ].map(([label, v], i) => (
            <div key={String(label)}>
              <div className="field-label">{label}</div>
              <div className={`mono mt-8 ${Number(v) >= 0 ? '' : 'value-neg'} ${i === 5 ? 'value-accent' : ''}`} style={{ fontSize: 17, fontWeight: 700 }}>
                {money(Number(v), s, { signed: i > 0 && i < 5 })}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid grid-2">
        <Card>
          <CardHead title="Parâmetros da banca" sub="Capital, entradas e reservas" />
          <div className="form-grid">
            <NumberField label="Banca inicial" value={s.initialBalance} onChange={(v) => setSetting('initialBalance', v)} step={0.01} prefix={s.currencySymbol} hint="Base para metas em % e rentabilidade" />
            <NumberField label="Valor base das entradas" value={s.baseEntry} onChange={(v) => setSetting('baseEntry', v)} step={0.01} prefix={s.currencySymbol} hint="Usado como ponto de partida dos ciclos" />
            <NumberField label="Valor mínimo por operação" value={s.minEntry} onChange={(v) => setSetting('minEntry', v)} step={0.01} prefix={s.currencySymbol} />
            <NumberField label="Valor máximo por operação" value={s.maxEntry} onChange={(v) => setSetting('maxEntry', v)} step={0.01} prefix={s.currencySymbol} />
            <NumberField label="Risco por operação" value={s.riskPercent} onChange={(v) => setSetting('riskPercent', v)} step={0.1} suffix="%" hint={`Equivale a ${money((balance * s.riskPercent) / 100, s)} atualmente`} />
            <NumberField label="Exposição máxima da banca" value={s.maxExposurePercent} onChange={(v) => setSetting('maxExposurePercent', v)} step={1} suffix="%" hint="Soma das entradas do dia / saldo de abertura" />
            <NumberField label="Reserva de lucro" value={s.profitReservePercent} onChange={(v) => setSetting('profitReservePercent', v)} step={1} suffix="%" hint="Percentual do lucro separado para saque" />
            <div className="field">
              <label className="field-label">Confirmação de limites</label>
              <div style={{ paddingTop: 6 }}><Toggle checked={s.requireLimitConfirmation} onChange={(v) => setSetting('requireLimitConfirmation', v)} label="Exigir autorização explícita para ultrapassar limites" /></div>
              <span className="field-hint">Quando ativo, o formulário bloqueia registros fora das regras até o usuário confirmar.</span>
            </div>
          </div>
        </Card>

        <Card>
          <CardHead title="Metas e limites diários" sub="Aplicados automaticamente a cada dia" />
          <div className="form-grid">
            <ModeValueField label="Meta diária" value={s.dailyGoal} onChange={(v) => setSetting('dailyGoal', v)} hint={`Hoje: ${money(m.goalValue, s)} · progresso ${m.goalProgress.toFixed(0)}%`} />
            <ModeValueField label="Stop Loss diário" value={s.stopLoss} onChange={(v) => setSetting('stopLoss', v)} hint={`Hoje: ${money(m.stopLossValue, s)}`} />
            <ModeValueField label="Stop Gain diário" value={s.stopGain} onChange={(v) => setSetting('stopGain', v)} hint={`Hoje: ${money(m.stopGainValue, s)}`} />
            <NumberField label="Máximo de operações / dia" value={s.maxOpsPerDay} onChange={(v) => setSetting('maxOpsPerDay', v)} suffix="ops" hint="0 = sem limite" />
            <NumberField label="Limite consecutivo de LOSS" value={s.maxConsecutiveLoss} onChange={(v) => setSetting('maxConsecutiveLoss', v)} hint="0 = sem limite" />
            <NumberField label="Limite consecutivo de WIN" value={s.maxConsecutiveWin} onChange={(v) => setSetting('maxConsecutiveWin', v)} hint="0 = sem limite" />
          </div>
          <div className="divider" />
          <Notice><Info size={14} /> Metas em percentual são calculadas sobre o saldo de abertura do dia. Alterar parâmetros não apaga nem altera operações já registradas — apenas recalcula metas, limites e sugestões.</Notice>
        </Card>
      </div>

      <div className="section-title">Definir saldo atual / movimentações</div>
      <div className="grid grid-2">
        <Card>
          <CardHead title="Ajustar saldo atual" sub="Cria uma movimentação de ajuste auditável" right={<RefreshCw size={15} className="muted" />} />
          <div className="row wrap">
            <div className="field" style={{ flex: 1, minWidth: 160 }}>
              <label className="field-label">Novo saldo desejado</label>
              <input className="input mono" type="number" step="0.01" placeholder={String(balance)} value={desiredBalance} onChange={(e) => setDesiredBalance(e.target.value)} />
            </div>
            <button className="btn primary" style={{ alignSelf: 'flex-end' }} disabled={!desiredBalance || !Number.isFinite(Number(desiredBalance))}
              onClick={() => setConfirmAdjust(Number(desiredBalance) - balance)}>
              Aplicar ajuste
            </button>
          </div>
          <div className="small muted mt-8">Diferença em relação ao saldo calculado: <b className="mono">{desiredBalance ? money(Number(desiredBalance) - balance, s, { signed: true }) : '—'}</b></div>
          <div className="divider" />
          <Notice kind="warn">O saldo nunca é sobrescrito silenciosamente: qualquer ajuste gera um registro datado no histórico de movimentações, preservando a consistência dos cálculos.</Notice>
        </Card>

        <Card>
          <CardHead title="Depósitos, retiradas e reserva" sub="Movimentações de capital" />
          <div className="form-grid">
            <Field label="Tipo">
              <select className="select" value={movement.type} onChange={(e) => setMovement({ ...movement, type: e.target.value as LedgerEntry['type'] })}>
                <option value="deposit">Depósito adicional</option>
                <option value="withdraw">Retirada de lucros</option>
                <option value="adjust">Ajuste manual</option>
              </select>
            </Field>
            <Field label="Valor"><input className="input mono" type="number" step="0.01" value={movement.amount} placeholder="0,00" onChange={(e) => setMovement({ ...movement, amount: e.target.value })} /></Field>
            <Field label="Data"><input className="input" type="date" value={movement.date} onChange={(e) => setMovement({ ...movement, date: e.target.value })} /></Field>
            <Field label="Observação"><input className="input" placeholder="Opcional" value={movement.note} onChange={(e) => setMovement({ ...movement, note: e.target.value })} /></Field>
          </div>
          <div className="btn-row mt-14">
            <button className="btn primary" onClick={addMovement}><Plus size={14} /> Registrar movimentação</button>
            <button className="btn" onClick={() => { setMovement({ ...movement, type: 'withdraw', amount: String(reserved) }); }}><PiggyBank size={14} /> Usar lucro reservado ({money(reserved, s)})</button>
          </div>
        </Card>
      </div>

      <div className="section-title">Histórico de movimentações</div>
      <Card className="pad-0">
        <div className="table-wrap" style={{ border: 0 }}>
          <table className="table">
            <thead><tr><th>Data</th><th>Tipo</th><th>Observação</th><th className="num">Valor</th><th /></tr></thead>
            <tbody>
              {data.ledger.length === 0 && <tr><td colSpan={5} className="center muted" style={{ padding: 26 }}>Nenhuma movimentação registrada</td></tr>}
              {[...data.ledger].sort((a, b) => b.date.localeCompare(a.date)).map((l) => (
                <tr key={l.id}>
                  <td>{formatDate(l.date, s)}</td>
                  <td><span className={`badge ${l.type === 'deposit' ? 'badge-win' : l.type === 'withdraw' ? 'badge-loss' : 'badge-draw'}`}>
                    {l.type === 'deposit' ? <><ArrowDownToLine size={11} /> Depósito</> : l.type === 'withdraw' ? <><ArrowUpFromLine size={11} /> Retirada</> : <><Shield size={11} /> Ajuste</>}
                  </span></td>
                  <td className="muted">{l.note || '—'}</td>
                  <td className={`num ${l.amount >= 0 ? 'value-pos' : 'value-neg'}`}>{money(l.amount, s, { signed: true })}</td>
                  <td className="right"><button className="btn xs danger" onClick={() => { deleteLedger(l.id); toast('Movimentação excluída.'); }}><Trash2 size={12} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {confirmAdjust !== null && (
        <Modal title="Confirmar ajuste de saldo" narrow onClose={() => setConfirmAdjust(null)}
          footer={<><button className="btn" onClick={() => setConfirmAdjust(null)}>Cancelar</button>
            <button className="btn primary" onClick={() => {
              addLedger({ date: todayISO(), type: 'adjust', amount: confirmAdjust, note: `Ajuste manual: saldo definido em ${money(Number(desiredBalance), s)}` });
              setConfirmAdjust(null); setDesiredBalance('');
              toast('Saldo ajustado. Movimentação registrada no histórico.');
            }}>Confirmar ajuste</button></>}>
          <div className="confirm-text">
            Isso criará uma movimentação de <b className={confirmAdjust >= 0 ? 'value-pos' : 'value-neg'}>{money(confirmAdjust, s, { signed: true })}</b> em {formatDate(todayISO(), s)},
            alterando o saldo de <b>{money(balance, s)}</b> para <b>{money(Number(desiredBalance), s)}</b>.<br /><br />
            O ajuste fica registrado no histórico e não modifica nenhuma operação.
          </div>
        </Modal>
      )}
    </>
  );
}
