import { fetchMeta, fetchRefreshLog, computeStaleness, fetchRoster } from '../api.js';
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

  // Trust banners: consume /hub-api/meta data_source + weather_status (server crew names).
  // Defensive: hide gracefully if fields absent (older server).
  const dataSource = meta?.data_source ?? null;
  const weatherStatus = meta?.weather_status ?? null;
  const isDemoData = typeof dataSource === 'string' && dataSource.toLowerCase() === 'demo';
  const isWeatherPlaceholder = (typeof weatherStatus === 'string' && weatherStatus.toLowerCase() === 'placeholder')
    || meta?.weather_placeholder === true;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Dashboard</h1>
      <p>12-team analytical hub powered by local SQLite WAL &amp; Sleeper API projections.</p>
    </div>

    ${isDemoData ? `<div class="alert alert-warn reveal in" role="status" style="margin-top:12px">Demo data — run refresh to load live Sleeper data.</div>` : ''}
    ${isWeatherPlaceholder ? `<div class="reveal in" style="margin-top:8px"><span class="badge badge-faint">Weather placeholder — forecast not yet live</span></div>` : ''}

    <div class="grid grid-3 reveal in" style="margin-top:16px">
      <div class="card">
        <div class="card-header"><h3>Season</h3><span class="kicker">${stale.level}</span></div>
        <div class="card-body">
          <div class="row">
            <div class="stat"><div class="stat-value mono">${meta.season ?? '2026'}</div><div class="stat-label">Season</div></div>
            <div class="stat"><div class="stat-value mono">${meta.week ?? '1'}</div><div class="stat-label">Week (1–18)</div></div>
            <div class="spacer"></div>
            <div class="badge" style="background:${stale.level==='fresh'?'var(--emerald-dim)':stale.level==='stale'?'var(--amber-dim)':'rgba(0,0,0,0.05)'}; color:${stale.level==='fresh'?'var(--emerald)':stale.level==='stale'?'var(--amber)':'var(--text-muted)'}; border:1px solid var(--border)">${stale.label}</div>
          </div>
          <div class="divider"></div>
          <div class="faint" style="font: 500 12px ui-monospace, SFMono-Regular, monospace;">${meta.lastUpdated ? `Last updated: ${new Date(meta.lastUpdated).toLocaleString()}` : 'Local DB Active'}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3>League Settings</h3><span class="kicker">12-Team League</span></div>
        <div class="card-body">
          <div class="row" style="gap:16px">
            <div class="stat"><div class="stat-value mono">${rosterPos.length ? rosterPos.length : '16'}</div><div class="stat-label">Roster slots</div></div>
            <div class="stat"><div class="stat-value mono">${rosterPos.filter(p=>p==='FLEX').length || 2}</div><div class="stat-label">FLEX</div></div>
            <div class="stat"><div class="stat-value mono">${scoring.rec ?? 1.0}</div><div class="stat-label">PPR</div></div>
          </div>
          <div class="divider"></div>
          <div class="row" style="gap:6px; flex-wrap:wrap">
            ${(rosterPos.length?rosterPos:["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN","IR","IR"]).map(p=>`<span class="badge" style="background:var(--surface-raised); border:1px solid var(--border); color:var(--text-muted); font-size:10px">${p}</span>`).join('')}
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3>Data Pipeline Status</h3><span class="kicker">SQLite WAL</span></div>
        <div class="card-body" style="padding:0">
          ${sources.length ? `<table><thead><tr><th>Source</th><th>At</th><th>Status</th></tr></thead><tbody>
            ${sources.map(s=>`<tr><td class="mono" style="font-size:12px">${s.source}</td><td class="micro" style="color:var(--text-muted)">${new Date(s.ran_at).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</td><td>${s.success ? `<span class="badge" style="background:var(--emerald-dim); color:var(--emerald)">ok</span>` : `<span class="badge" style="background:var(--crimson-dim); color:var(--crimson)">fail</span>`}</td></tr>`).join('')}
          </tbody></table>` : `<div class="empty">Local DB active &amp; ready</div>`}
        </div>
      </div>
    </div>

    <!-- 12-Team League Showcase Card -->
    ${teams.length ? `
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header row align-between">
        <h3>12-Team League — League Directory</h3>
        <span class="badge badge-amber mono">${teams.length} Teams</span>
      </div>
      <div class="card-body" style="padding:12px">
        <div class="grid grid-3" style="gap:10px">
          ${teams.slice(0, 12).map((t, idx) => `
            <a href="#roster" class="card" style="padding:10px; text-decoration:none; background:var(--surface-raised); border:1px solid var(--border); display:flex; align-items:center; gap:12px; transition:transform 0.15s ease">
              ${userAvatar(t, 36)}
              <div style="flex:1; overflow:hidden">
                <div style="font-weight:700; font-size:13px; color:var(--text); white-space:nowrap; overflow:hidden; text-overflow:ellipsis">
                  ${t.team_name || `Team ${t.roster_id}`}
                </div>
                <div class="micro faint">@${t.owner_name || t.display_name || `Owner ${t.roster_id}`}</div>
              </div>
              <span class="badge badge-faint mono" style="font-size:11px">#${idx + 1}</span>
            </a>
          `).join('')}
        </div>
      </div>
    </div>
    ` : ''}
  `;
}
