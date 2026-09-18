import { fetchMeta, fetchRefreshLog, computeStaleness, fetchRoster } from '../api.js';
import { leagueTagline } from '../lib/league.js';
import { escapeHtml } from '../lib/escape.js';
import { userAvatar } from '../components/userAvatar.js';
import { playerAvatar } from '../components/playerAvatar.js';

export async function renderDashboard(root) {
  const [meta, log, rosterData] = await Promise.all([
    fetchMeta(),
    fetchRefreshLog(),
    fetchRoster().catch(() => ({ allTeams: [] })),
  ]);

  const stale = computeStaleness(meta.lastUpdated || meta.last_updated || log.entries?.[0]?.ran_at);
  const sources = log.entries?.slice(0, 4) || [];
  const teams = rosterData?.allTeams || rosterData?.leagueRosters || [];

  const scoring = meta.scoring_settings || {};
  const rosterPos = meta.roster_positions || [];

  const dataSource = meta?.data_source ?? null;
  const weatherStatus = meta?.weather_status ?? null;
  const isDemoData = typeof dataSource === 'string' && dataSource.toLowerCase() === 'demo';
  const isWeatherPlaceholder = (typeof weatherStatus === 'string' && weatherStatus.toLowerCase() === 'placeholder')
    || meta?.weather_placeholder === true;

  const accentColor = stale.level === 'fresh' ? 'emerald' : stale.level === 'stale' ? 'amber' : 'primary';
  const staleDot = stale.level === 'fresh' ? 'var(--emerald)' : 'var(--amber)';

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Dashboard</h1>
      <p>${escapeHtml(leagueTagline(meta))}</p>
    </div>

    ${isDemoData ? `<div class="alert alert-warn reveal in" role="status">Demo data — run refresh to load live Sleeper data.</div>` : ''}
    ${isWeatherPlaceholder ? `<div class="reveal in"><span class="badge badge-faint">Weather: placeholder</span></div>` : ''}

    <div class="kpi-row reveal in reveal-delay-1">
      <div class="kpi-card" style="--kpi-accent:var(--primary)">
        <div class="kpi-label">Season</div>
        <div class="kpi-value mono">${meta.season ?? '2026'}</div>
      </div>
      <div class="kpi-card" style="--kpi-accent:var(--amber)">
        <div class="kpi-label">Week</div>
        <div class="kpi-value mono">${meta.week ?? '1'}</div>
      </div>
      <div class="kpi-card" style="--kpi-accent:var(--emerald)">
        <div class="kpi-label">PPR</div>
        <div class="kpi-value mono">${scoring.rec ?? 1.0}</div>
      </div>
      <div class="kpi-card" style="--kpi-accent:var(--sky)">
        <div class="kpi-label">FLEX Slots</div>
        <div class="kpi-value mono">${rosterPos.filter(p => p === 'FLEX').length || 2}</div>
      </div>
    </div>

    <div class="grid grid-2 reveal in reveal-delay-2">
      <div class="card card-accent-${accentColor}">
        <div class="card-header">
          <h3>League Config</h3>
          <span class="badge badge-${accentColor}" style="font-size:10px">${stale.label}</span>
        </div>
        <div class="card-body">
          <div class="row" style="gap:4px; flex-wrap:wrap; margin-bottom:8px">
            ${(rosterPos.length ? rosterPos : ["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN","IR","IR"]).map(p => {
              const pc = {QB:'pos-qb',RB:'pos-rb',WR:'pos-wr',TE:'pos-te',K:'pos-k',DEF:'pos-def'}[p];
              return pc
                ? `<span class="badge badge-pos" data-pos="${p}" style="font-size:9px">${p}</span>`
                : `<span class="badge badge-faint" style="font-size:9px">${p}</span>`;
            }).join('')}
          </div>
          <div class="micro faint" style="display:flex; align-items:center; gap:5px">
            <span class="dot ${stale.level === 'fresh' ? 'fresh' : stale.level === 'stale' ? 'stale' : 'cold'}"></span>
            ${meta.lastUpdated ? `Updated ${new Date(meta.lastUpdated).toLocaleString()}` : 'Local DB Active'}
          </div>
        </div>
      </div>

      <div class="card card-accent-sky">
        <div class="card-header"><h3>Data Pipeline</h3><span class="kicker">${sources.length ? 'SQLite WAL' : 'Scheduled snapshots'}</span></div>
        <div class="card-body" style="padding:0">
          ${sources.length ? `<table><thead><tr><th>Source</th><th>At</th><th>Status</th></tr></thead><tbody>
            ${sources.map(s => `<tr>
              <td class="mono" style="font-size:11px">${s.source}</td>
              <td class="micro faint">${new Date(s.ran_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</td>
              <td>${s.success
                ? `<span class="badge badge-emerald">ok</span>`
                : `<span class="badge badge-crimson">fail</span>`}</td>
            </tr>`).join('')}
          </tbody></table>` : `<div class="empty">No refresh history yet — data updates on schedule</div>`}
        </div>
      </div>
    </div>

    ${teams.length ? `
    <div class="card card-accent-primary reveal in reveal-delay-3">
      <div class="card-header">
        <h3>League Directory</h3>
        <span class="badge badge-sky">${teams.length} teams</span>
      </div>
      <div class="card-body" style="padding:10px">
        <div class="grid grid-3" style="gap:6px">
          ${teams.slice(0, 12).map((t, idx) => `
            <a href="#roster" class="team-dir-card" style="text-decoration:none">
              ${userAvatar(t, 34)}
              <div style="flex:1; overflow:hidden">
                <div style="font-weight:600; font-size:12px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis">
                  ${t.team_name || `Team ${t.roster_id}`}
                </div>
                <div class="micro faint">@${t.owner_name || t.display_name || `Owner ${t.roster_id}`}</div>
              </div>
              <span class="badge badge-faint" style="font-size:9px">#${idx + 1}</span>
            </a>
          `).join('')}
        </div>
      </div>
    </div>
    ` : ''}
  `;
}
