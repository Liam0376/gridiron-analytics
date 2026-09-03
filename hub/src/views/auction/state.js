// hub/src/views/auction/state.js — auction draft tracker persistence.
// Stored under 'ffba-auction-draft' as { drafted: {pid:{by,price}}, myRoster:[pid], myBudget, nominations }.

import { BUDGET } from '../../lib/auctionMath.js';

export const STORE_KEY = 'ffba-auction-draft';

export function loadDraftState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (_) {
    // localStorage unavailable in private mode
  }
  return { drafted: {}, myRoster: [], myBudget: BUDGET, nominations: [] };
}

export function saveDraftState(state) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(state));
  } catch (_) {
    // localStorage unavailable in private mode
  }
}

export function resetDraftState() {
  try {
    localStorage.removeItem(STORE_KEY);
  } catch (_) {
    // localStorage unavailable in private mode
  }
}