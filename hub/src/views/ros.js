import { fetchRosProjections, fetchMeta } from '../api.js';

export async function renderRos(root) {
  root.innerHTML = '<div class="card"><div class="card-body">Loading RoS projections…</div></div>';

  const [rosData, meta] = await Promise.all([
    fetchRosProjections({ limit: 300 }),
    fetchMeta().catch(() => ({})),
  ]);

  const players = rosData.players || [];
  const leagueName = meta.leagueName || 'Fantasy Bahamas';

  if (!players.length) {
    root.innerHTML = `
      <div class="card">
        <div class="card-header"><h2>Rest-of-Season Projections</h2></div>
        <div class="card-body">
          <div class="empty">No RoS projections available. Run a refresh to generate them.</div>
        </div>
      </div>`;
    return;
  }

  const rows = players.map((p, i) => `
    <tr>
      <td class="rank">${i + 1}</td>
      <td class="player-name">${esc(p.player_name)}</td>
      <td class="pos-badge pos-${(p.position || '').toLowerCase()}">${esc(p.position)}</td>
      <td class="team">${esc(p.team)}</td>
      <td class="num">${p.per_game_neutral.toFixed(1)}</td>
      <td class="num">${p.remaining_games}</td>
      <td class="num strong">${p.ros_points.toFixed(1)}</td>
    </tr>
  `).join('');

  root.innerHTML = `
    <div class="card">
      <div class="card-header">
        <h2>Rest-of-Season Projections</h2>
        <span class="subtitle">${esc(leagueName)} · neutral per-game × remaining games</span>
      </div>
      <div class="card-body" style="overflow-x:auto">
        <table class="data-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Pos</th>
              <th>Team</th>
              <th class="num">Per Game</th>
              <th class="num">Remaining</th>
              <th class="num">RoS Total</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

function esc(s) { return String(s || '').replace(/</g, '&lt;'); }
