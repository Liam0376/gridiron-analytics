// hub/src/lib/slots.js — canonical starter slot assignment.
// Canonical order: QB, RB1, RB2, WR1, WR2, TE, FLEX1, FLEX2, K, DEF
// Returns { starters, bench } where bench is labeled BN1..BNn.
// Extra starters beyond the 10 canonical slots spill into FLEX3, FLEX4, ...

import { enrichPlayer } from './enrichPlayer.js';

const STARTER_LABELS = ['QB', 'RB1', 'RB2', 'WR1', 'WR2', 'TE', 'FLEX1', 'FLEX2', 'K', 'DEF'];

export function assignStarterSlots(rawStarters, rawBench, opts = {}) {
  const enrichOpts = {
    compPlayers: opts.compPlayers || null,
    vbdParams: opts.vbdParams || null,
  };
  const posCounts = { QB: 0, RB: 0, WR: 0, TE: 0, FLEX: 0, K: 0, DEF: 0 };

  const starters = (rawStarters || []).map((p, idx) => {
    const pos = (p.position || 'UNK').toUpperCase();
    let slot = STARTER_LABELS[idx] || `S${idx + 1}`;
    if (pos === 'QB') {
      posCounts.QB++;
      slot = posCounts.QB === 1 ? 'QB' : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'RB') {
      posCounts.RB++;
      slot = posCounts.RB <= 2 ? `RB${posCounts.RB}` : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'WR') {
      posCounts.WR++;
      slot = posCounts.WR <= 2 ? `WR${posCounts.WR}` : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'TE') {
      posCounts.TE++;
      slot = posCounts.TE === 1 ? 'TE' : `FLEX${++posCounts.FLEX}`;
    } else if (pos === 'K') {
      slot = 'K';
    } else if (pos === 'DEF') {
      slot = 'DEF';
    }
    return enrichPlayer({ ...p, slot }, null, { ...enrichOpts, defaultSlot: slot });
  });

  const bench = (rawBench || []).map((p, i) =>
    enrichPlayer({ ...p, slot: `BN${i + 1}` }, null, { ...enrichOpts, defaultSlot: `BN${i + 1}` })
  );

  return { starters, bench };
}