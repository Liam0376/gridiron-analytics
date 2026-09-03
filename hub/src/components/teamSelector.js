// hub/src/components/teamSelector.js — Global Team Selector Component
import { fetchRoster } from '../api.js';
import { escapeHtml } from '../lib/escape.js';

const STORAGE_KEY = 'ffba-selected-team-id';

export function getSelectedTeamId() {
  try {
    return localStorage.getItem(STORAGE_KEY) || null;
  } catch (_) {
    // localStorage unavailable in private mode
    return null;
  }
}

export function setSelectedTeamId(id) {
  try {
    localStorage.setItem(STORAGE_KEY, String(id));
  } catch (_) {
    // localStorage unavailable in private mode
  }
}

const DEFAULT_TEAMS = [
  { roster_id: '7', display_name: 'lfb0376', team_name: 'lfb0376' },
  { roster_id: '2', display_name: 'poma12', team_name: 'felix team' },
  { roster_id: '6', display_name: 'Arguelles', team_name: 'Rebeldes de Boston' },
  { roster_id: '1', display_name: 'DGoatMx', team_name: 'DGoatMx' },
  { roster_id: '3', display_name: 'gonzazabala10', team_name: 'gonzazabala10' },
  { roster_id: '4', display_name: 'fuchsgoated', team_name: 'fuchsgoated' },
  { roster_id: '5', display_name: 'Cachitos', team_name: 'Cachitos' },
  { roster_id: '8', display_name: 'erik6782357', team_name: 'erik6782357' },
  { roster_id: '9', display_name: 'rodrigotajonar97', team_name: 'rodrigotajonar97' },
  { roster_id: '10', display_name: 'toytorres', team_name: 'toytorres' },
  { roster_id: '11', display_name: 'gonher10', team_name: 'gonher10' },
  { roster_id: '12', display_name: 'Elcojeperras', team_name: 'Elcojeperras' },
];

export function getDefaultTeamId(leagueRosters = []) {
  if (Array.isArray(leagueRosters) && leagueRosters.length && leagueRosters[0]?.roster_id != null) {
    return String(leagueRosters[0].roster_id);
  }
  return null;
}

export function resolveSelectedTeamId(leagueRosters = [], currentId = null) {
  const stored = currentId || getSelectedTeamId();
  if (stored) {
    if (Array.isArray(leagueRosters) && leagueRosters.length) {
      const match = leagueRosters.some(t => String(t.roster_id) === String(stored));
      if (match) return String(stored);
    } else {
      return String(stored);
    }
  }
  return getDefaultTeamId(leagueRosters);
}

export function renderTeamSelector(leagueRosters = [], currentId = null) {
  const list = (Array.isArray(leagueRosters) && leagueRosters.length) ? leagueRosters : DEFAULT_TEAMS;
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
