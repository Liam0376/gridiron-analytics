// hub/src/components/teamSelector.js — Global Team Selector Component
import { fetchRoster } from '../api.js';

const STORAGE_KEY = 'ffba-selected-team-id';
const DEFAULT_TEAM_ID = '7'; // lfb0376

export function getSelectedTeamId() {
  try {
    return localStorage.getItem(STORAGE_KEY) || DEFAULT_TEAM_ID;
  } catch (_) {
    return DEFAULT_TEAM_ID;
  }
}

export function setSelectedTeamId(id) {
  try {
    localStorage.setItem(STORAGE_KEY, String(id));
  } catch (_) {}
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

export function renderTeamSelector(leagueRosters = [], currentId = null) {
  const selectedId = currentId || getSelectedTeamId();
  const list = (Array.isArray(leagueRosters) && leagueRosters.length) ? leagueRosters : DEFAULT_TEAMS;

  return `
    <div class="team-selector-wrap">
      <label for="globalTeamSelect" class="sr-only">Select Team</label>
      <select id="globalTeamSelect" class="team-select-dropdown" aria-label="Select Sleeper Team">
        ${list.map(t => {
          const rId = String(t.roster_id);
          const isSel = rId === String(selectedId) || (selectedId === 'lfb0376' && rId === '7');
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

function escapeHtml(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
}
