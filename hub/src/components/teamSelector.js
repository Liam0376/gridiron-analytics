// hub/src/components/teamSelector.js — Global Team Selector Component
import { fetchRoster } from '../api.js';
import { escapeHtml } from '../lib/escape.js';
import { getLeagueId, teamStorageKey } from '../lib/league.js';

function storageKey(leagueId) {
  // why namespaced: team ids are per-league — switching leagues must never
  // restore another league's roster pick.
  return teamStorageKey(leagueId !== undefined ? leagueId : getLeagueId());
}

export function getSelectedTeamId(leagueId) {
  try {
    return localStorage.getItem(storageKey(leagueId)) || null;
  } catch (_) {
    // localStorage unavailable in private mode
    return null;
  }
}

export function setSelectedTeamId(id, leagueId) {
  try {
    localStorage.setItem(storageKey(leagueId), String(id));
  } catch (_) {
    // localStorage unavailable in private mode
  }
}

export function renderTeamSelector(leagueRosters = [], currentId = null) {
  // why no hardcoded fallback roster: team names/ids are per-league private
  // data — a static list would show the wrong league's managers. Empty state
  // invites setup instead.
  const list = (Array.isArray(leagueRosters) && leagueRosters.length) ? leagueRosters : [];
  if (!list.length) {
    return `<div class="faint" style="font-size:12px">No teams synced — <a href="#dashboard">open Dashboard</a> to set up your league.</div>`;
  }
  // Default derives from leagueRosters[0] (or fallback list[0]) — no hardcoded team id.
  const fallbackDefault = list.length && list[0]?.roster_id != null ? String(list[0].roster_id) : null;
  const stored = currentId || getSelectedTeamId();
  const selectedId = stored || fallbackDefault;

  return `
    <div class="team-selector-wrap">
      <label for="globalTeamSelect" class="sr-only">Select Team</label>
      <select id="globalTeamSelect" class="team-select-dropdown" aria-label="Select Sleeper Team">
        ${list.map(t => {
          const rId = String(t.roster_id);
          const isSel = rId === String(selectedId);
          const label = t.team_name && t.team_name !== t.display_name
            ? `${t.team_name} (${t.display_name})`
            : t.display_name;
          return `<option value="${rId}" ${isSel ? 'selected' : ''}>${escapeHtml(label)}</option>`;
        }).join('')}
      </select>
    </div>
  `;
}

export function bindTeamSelector(onSelectCallback) {
  const el = document.getElementById('globalTeamSelect');
  if (!el) return;
  el.addEventListener('change', (e) => {
    const val = e.target.value;
    setSelectedTeamId(val);
    if (typeof onSelectCallback === 'function') {
      onSelectCallback(val);
    }
  });
}
