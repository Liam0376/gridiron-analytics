import { fetchRoster } from '../api.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { intervalBar } from '../components/intervalBar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';

export async function renderRoster(root) {
  const data = await fetchRoster();
  const starters = data.starters || data.roster || [];
  const bench = data.bench || [];
  const myRoster = data.myRoster || starters;
  const leagueNote = data.meta || {};

  const hasData = starters.length || bench.length || myRoster.length;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>My Roster</h1>
      <p>Start/sit with <strong>interval overlap</strong> — the core idea (intervals are estimated ranges, not formal confidence bounds). If your starter's bar overlaps your bench's bar, it's a toss-up, not a confident start. Click a bench player to preview the swap.</p>
    </div>
    ${!hasData ? `<div class="card reveal in" style="margin-top:12px"><div class="empty">No roster loaded. Need <code class="inline">rosters.data</code> + <code class="inline">player_stats.data</code> from <code class="inline">POST /refresh</code> or <code class="inline">hub/server.py</code>.</div></div>` : `
      <div class="card reveal in" style="margin-top:12px">
        <div class="card-header"><h3>Starters</h3><span class="kicker">${starters.length} slots · ${leagueNote.scoring || 'PPR'}</span></div>
        <div class="card-body" style="padding:0">
          <div class="table-wrap" style="border:0; border-radius:0"><table>
            <thead><tr><th>Slot</th><th>Player</th><th>Pos</th><th>Proj</th><th>Interval</th><th>Conf</th><th>Status</th><th>Action</th></tr></thead>
            <tbody>
              ${myRoster.map((p,i)=>`
                <tr>
                  <td class="micro faint">${p.slot || `SLOT ${i+1}`}</td>
                  <td><div class="player-cell">${playerAvatar(p, 32)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name || p.player_id)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team||'')} vs ${escapeHtml(p.opponent_team||'')}</div></div></div></td>
                  <td>${posBadge(p.position || p.position_group)}</td>
                  <td class="mono">${Number(p.projected_points ?? 0).toFixed(1)}</td>
                  <td>${intervalBar({ point: Number(p.projected_points ?? 0), low: Number(p.projection_lower ?? p.projected_points - 2.5), high: Number(p.projection_upper ?? p.projected_points + 2.5), width: Number(p.width ?? 5), min: 0, max: 35 })}</td>
                  <td>${p.width < 3 ? '<span class="badge" style="background:var(--emerald-dim); color:var(--emerald)">HIGH</span>' : p.width < 6 ? '<span class="badge" style="background:var(--amber-dim); color:var(--amber)">MED</span>' : '<span class="badge" style="background:rgba(255,255,255,0.06); color:var(--text-muted)">WIDE</span>'}</td>
                  <td>${injuryBadge(p.injury_status)}</td>
                  <td><span class="faint" style="font:500 11px 'Fragment Mono', monospace">${p.recommendation || '—'}</span></td>
                </tr>
              `).join('')}
            </tbody>
          </table></div>
        </div>
      </div>

      <div class="card reveal in" style="margin-top:12px">
        <div class="card-header"><h3>Bench</h3><span class="kicker">${bench.length} players</span></div>
        <div class="card-body" style="padding:0">
          <div class="table-wrap" style="border:0; border-radius:0"><table>
            <thead><tr><th>Player</th><th>Pos</th><th>Proj</th><th>Interval</th><th>Status</th></tr></thead>
            <tbody>
              ${bench.map(p=>`
                <tr>
                  <td><div class="player-cell">${playerAvatar(p, 32)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name || p.player_id)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team||'')}</div></div></div></td>
                  <td>${posBadge(p.position || p.position_group)}</td>
                  <td class="mono">${Number(p.projected_points ?? 0).toFixed(1)}</td>
                  <td>${intervalBar({ point: Number(p.projected_points ?? 0), low: Number(p.projection_lower ?? 0), high: Number(p.projection_upper ?? 0), width: Number(p.width ?? 5), min: 0, max: 35 })}</td>
                  <td>${injuryBadge(p.injury_status)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table></div>
        </div>
      </div>
    `}
    <div class="faint" style="margin-top:12px; font:400 11px 'Instrument Sans', sans-serif">Logic mirrors <code class="inline">decision.py:get_start_sit_recommendations</code> but rendered with intervals so you see overlap. No writes — swap is preview only.</div>
  `;
}
function escapeHtml(s){ return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
