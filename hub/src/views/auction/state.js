// hub/src/views/auction/state.js — auction draft tracker persistence.
// Stored per league under 'ffba-auction-draft:<leagueId>' as
// { drafted: {pid:{by,price}}, myRoster:[pid], myBudget, nominations }.
// why namespaced: draft boards are per-league — switching leagues must never
// restore another league's picks. Legacy un-namespaced key migrates once.

import { BUDGET } from '../../lib/auctionMath.js';
import { getLeagueId } from '../../lib/league.js';

export const STORE_KEY = 'ffba-auction-draft';

function storeKey(leagueId) {
  const id = leagueId !== undefined ? leagueId : getLeagueId();
  return id ? `${STORE_KEY}:${id}` : STORE_KEY;
}

export function loadDraftState(leagueId) {
  const key = storeKey(leagueId);
  try {
    const raw = localStorage.getItem(key);
    if (raw) return JSON.parse(raw);
    // why one-time legacy fallback: pre-multi-league installs stored under
    // the bare key — adopt it into the namespaced key on next save.
    if (key !== STORE_KEY) {
      const legacy = localStorage.getItem(STORE_KEY);
      if (legacy) return JSON.parse(legacy);
    }
  } catch (_) {
    // localStorage unavailable in private mode
  }
  return { drafted: {}, myRoster: [], myBudget: BUDGET, nominations: [] };
}

export function saveDraftState(state, leagueId) {
  try {
    localStorage.setItem(storeKey(leagueId), JSON.stringify(state));
  } catch (_) {
    // localStorage unavailable in private mode
  }
}

export function resetDraftState(leagueId) {
  try {
    localStorage.removeItem(storeKey(leagueId));
  } catch (_) {
    // localStorage unavailable in private mode
  }
}
