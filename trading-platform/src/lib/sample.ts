import type { Operation, TradeResult } from '../types';
import { uid, todayISO, calcProfit } from './defaults';
import { addDays } from './format';

/**
 * Gerador de dados EXCLUSIVAMENTE demonstrativos.
 * Toda operação criada aqui recebe `demo: true` e só aparece quando o usuário
 * habilita "Incluir simulações". Nunca é tratada como operação real.
 */
export function makeDemoOperations(): Operation[] {
  let seed = 20261105;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  const assets = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/CAD', 'EUR/GBP', 'BTC/USD'];
  const timeframes = ['M1', 'M5', 'M15'];
  const expiries = ['1m', '2m', '5m'];
  const results: TradeResult[] = ['WIN', 'WIN', 'WIN', 'WIN', 'LOSS', 'WIN', 'LOSS', 'DRAW'];
  const ops: Operation[] = [];
  const today = todayISO();

  for (let d = 27; d >= 0; d--) {
    // ~2 dias sem operações para o calendário ficar realista
    if (d % 11 === 4 || d % 13 === 7) continue;
    const date = addDays(today, -d);
    const count = 3 + Math.floor(rand() * 5);
    const seriesId = `demo-serie-${Math.floor((27 - d) / 4)}`;
    for (let i = 0; i < count; i++) {
      const hour = 9 + Math.floor(rand() * 10);
      const minute = Math.floor(rand() * 12) * 5;
      const time = `${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
      const result = results[Math.floor(rand() * results.length)];
      const payout = [80, 85, 87, 90, 92][Math.floor(rand() * 5)];
      const entry = Math.round((15 + rand() * 45) * 100) / 100;
      ops.push({
        id: uid(), date, time,
        asset: assets[Math.floor(rand() * assets.length)],
        market: rand() > 0.78 ? 'OTC' : 'Normal',
        direction: rand() > 0.5 ? 'CALL' : 'PUT',
        strategyId: '',
        timeframe: timeframes[Math.floor(rand() * timeframes.length)],
        expiry: expiries[Math.floor(rand() * expiries.length)],
        entry, payout, result,
        profit: calcProfit(entry, payout, result),
        notes: rand() > 0.85 ? 'Exemplo: entrada após confirmação de tendência.' : '',
        seriesId,
        demo: true,
        createdAt: Date.now() - d * 86400000 + i * 60000,
      });
    }
  }
  return ops;
}
