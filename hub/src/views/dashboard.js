import { fetchMeta, fetchRefreshLog, fetchRostersFull, fetchNews, fetchWaiver, fetchComparison, computeStaleness } from '../api.js';
import { leagueTagline } from '../lib/league.js';
import { escapeHtml } from '../lib/escape.js';
import { userAvatar } from '../components/userAvatar.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { posBadge, injuryBadge } from '../components/badges.js';
import { teamLogo } from '../components/teamLogo.js';

export async function renderDashboard(root) {
  const [meta, log, bulk, news, waiver, buys, sells] = await Promise.all([
    fetchMeta(),
    fetchRefreshLog(),
    fetchRostersFull().catch(() => null),
    fetchNews().catch(() => ({ trending_adds: [] })),
    fetchWaiver({}).catch(() => ({ recommendations: [] })),
    fetchComparison({ edge: 'BUY', limit: 3 }).catch(() => ({ players: [] })),
    fetchComparison({ edge: 'SELL', limit: 3 }).catch(() => ({ players: [] })),
  ]);

  const stale = computeStaleness(meta.lastUpdated || meta.last_updated || log.entries?.[0]?.ran_at);
  const leagueName = meta.leagueName || 'Dashboard';
  const week = meta.week ?? bulk?.week ?? null;

  // ---- Playoff race (record, tiebreak PF) ----
  const leagueTeams = [...(bulk?.leagueRosters || [])].sort(
    (a, b) => (b.wins ?? 0) - (a.wins ?? 0) || (b.fpts ?? 0) - (a.fpts ?? 0)
  );
  const cutLine = bulk?.playoff_teams ?? 6;

  // ---- Status report: rostered players carrying an injury tag ----
  const hurt = [];
  for (const [rid, r] of Object.entries(bulk?.rosters || {})) {
    const info = r.teamMeta || r.team_info || {};
    const owner = info.display_name || info.team_name || `Team ${rid}`;
    for (const p of [...(r.starters || []), ...(r.bench || [])]) {
      const st = p.injury_status;
      if (st && st !== 'Healthy' && st !== 'Active') hurt.push({ ...p, owner });
    }
  }
  hurt.sort((a, b) => severityRank(b.injury_status) - severityRank(a.injury_status));

  const trending = (news.trending_adds || []).slice(0, 4);
  const targets = [...(waiver.recommendations || [])]
    .sort((a, b) => (b.improvement_over_roster ?? -99) - (a.improvement_over_roster ?? -99))
    .slice(0, 5);

  const scoring = meta.scoring_settings || {};
  const rec = Number(scoring.rec ?? 1.0);
  const scoringLabel = rec === 1 ? 'Full PPR' : rec === 0.5 ? 'Half PPR' : rec === 0 ? 'Non-PPR' : `${rec} PPR`;

  root.innerHTML = `
    <div class="dash-band reveal in">
      <div class="dash-band-main">
        <div class="kicker">${escapeHtml([meta.season ? `${meta.season} Season` : '', week != null ? `Week ${week}` : '', stale.label].filter(Boolean).join(' · '))}</div>
        <h1>${escapeHtml(leagueName)}</h1>
        <p>${escapeHtml(leagueTagline(meta))} · ${escapeHtml(scoringLabel)}</p>
      </div>
      <div class="dash-band-side">
        <div class="dash-week">${week != null ? `W${week}` : '—'}</div>
        <div class="micro faint">${escapeHtml(leagueTeams.length ? `${leagueTeams.length} teams` : 'league')}</div>
      </div>
    </div>

    ${isDemoData(meta) ? `<div class="alert alert-warn reveal in" role="status">Demo data — run refresh to load live Sleeper data.</div>` : ''}

    <div class="dash-grid reveal in reveal-delay-1">
      <div class="card dash-span-4">
        <div class="card-header"><h3>Playoff Race</h3><span class="kicker">top ${cutLine} · tiebreak PF</span></div>
        <div class="card-body" style="padding:6px 12px">
          ${leagueTeams.length ? leagueTeams.map((t, i) => `
            ${i === cutLine ? `<div class="cut-line"><span>playoff cut</span></div>` : ''}
            <div class="stand-row">
              <span class="mono faint" style="width:18px">${i + 1}</span>
              ${userAvatar(t, 24)}
              <span class="stand-name">${escapeHtml(t.team_name || t.display_name || `Team ${t.roster_id}`)}</span>
              <span class="spacer"></span>
              <span class="mono" style="font-weight:700">${t.wins ?? 0}–${t.losses ?? 0}${t.ties ? `–${t.ties}` : ''}</span>
              <span class="mono faint" style="font-size:11px; width:52px; text-align:right">${Number(t.starter_pts ?? 0).toFixed(1)}/wk</span>
            </div>
          `).join('') : `<div class="empty">No standings yet</div>`}
        </div>
      </div>

      <div class="card dash-span-4">
        <div class="card-header"><h3>Status Report</h3><span class="kicker">rostered · ${hurt.length}</span></div>
        <div class="card-body" style="padding:6px 12px">
          ${hurt.length ? hurt.slice(0, 6).map(p => `
            <div class="mini-row" data-pid="${escapeHtml(p.player_id || '')}" style="cursor:pointer">
              ${playerAvatar(p, 26)}
              <div style="flex:1; min-width:0">
                <div class="mini-name">${escapeHtml(p.player_name || p.player_id)}</div>
                <div class="micro faint">${posBadge(p.position)} ${teamLogo(p.team, 12)} · @${escapeHtml(p.owner)}</div>
              </div>
              ${injuryBadge(p.injury_status)}
            </div>
          `).join('') : `<div class="empty">No injury tags on rosters</div>`}
          ${trending.length ? `
            <div class="kicker" style="margin:10px 0 4px">Trending adds</div>
            ${trending.map(t => `
              <div class="mini-row">
                ${t.player_id ? playerAvatar({ player_id: t.player_id, player_name: t.player_name || '', position: t.position || '', team: t.team || '' }, 26) : ''}
                <div style="flex:1; min-width:0"><div class="mini-name">${escapeHtml(t.player_name || t.player_id)}</div></div>
                ${t.count ? `<span class="mono faint" style="font-size:11px">+${(t.count / 1000).toFixed(1)}k</span>` : ''}
              </div>
            `).join('')}` : ''}
        </div>
      </div>

      <div class="card dash-span-4">
        <div class="card-header"><h3>Waiver Targets</h3><a href="#waiver" class="kicker" style="color:var(--flag)">all →</a></div>
        <div class="card-body" style="padding:6px 12px">
          ${targets.length ? targets.map(r => `
            <div class="mini-row" data-pid="${escapeHtml(r.player_id || '')}" style="cursor:pointer">
              ${playerAvatar(r, 26)}
              <div style="flex:1; min-width:0">
                <div class="mini-name">${escapeHtml(r.player_name || r.player_id)}</div>
                <div class="micro faint">${posBadge(r.position)} ${teamLogo(r.team, 12)} ${escapeHtml(r.team || '')}</div>
              </div>
              <div style="text-align:right">
                <div class="mono" style="font-weight:700; color:var(--emerald); font-size:12px">+${Number(r.improvement_over_roster ?? 0).toFixed(1)}</div>
                <div class="micro faint">${Number(r.projected_points ?? 0).toFixed(1)} proj</div>
              </div>
            </div>
          `).join('') : `<div class="empty">No waiver candidates</div>`}
        </div>
      </div>

      <div class="card dash-span-7">
        <div class="card-header"><h3>Trade Signals</h3><a href="#auction" class="kicker" style="color:var(--flag)">values →</a></div>
        <div class="card-body">
          <div class="signal-cols">
            <div>
              <div class="kicker good" style="margin-bottom:6px">▲ Buy — model over market</div>
              ${(buys.players || []).map(p => signalRow(p)).join('') || `<div class="empty">—</div>`}
            </div>
            <div>
              <div class="kicker bad" style="margin-bottom:6px">▼ Sell — market over model</div>
              ${(sells.players || []).map(p => signalRow(p)).join('') || `<div class="empty">—</div>`}
            </div>
          </div>
        </div>
      </div>

      <div class="card dash-span-5">
        <div class="card-header"><h3>Sync</h3><span class="row" style="gap:5px"><span class="dot ${stale.level === 'fresh' ? 'fresh' : stale.level === 'stale' ? 'stale' : 'cold'}"></span><span class="kicker">${escapeHtml(stale.label)}</span></span></div>
        <div class="card-body" style="padding:10px 12px">
          <div class="micro faint">${meta.lastUpdated ? `Updated ${new Date(meta.lastUpdated).toLocaleString()}` : 'Local DB Active'}</div>
          ${(log.entries || []).slice(0, 3).map(s => `
            <div class="sync-row">
              <span class="dot ${s.success ? 'fresh' : 'stale'}" style="flex-shrink:0"></span>
              <span class="mono" style="font-size:11px">${escapeHtml(s.source)}</span>
              <span class="spacer"></span>
              <span class="micro faint">${new Date(s.ran_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
            </div>
          `).join('')}
        </div>
      </div>
    </div>
  `;

  // Player cards open from any row carrying a pid.
  root.querySelectorAll('[data-pid]').forEach(el => {
    el.addEventListener('click', async () => {
      const pid = el.getAttribute('data-pid');
      const found = [...(waiver.recommendations || []), ...hurt].find(x => String(x.player_id) === String(pid));
      if (found) {
        const { openPlayerModal } = await import('../components/playerModal.js');
        openPlayerModal(found, root);
      }
    });
  });
}

function signalRow(p) {
  return `
    <div class="mini-row">
      ${playerAvatar(p, 26)}
      <div style="flex:1; min-width:0">
        <div class="mini-name">${escapeHtml(p.player_name || p.player_id)}</div>
        <div class="micro faint">${posBadge(p.position)} ${teamLogo(p.team, 12)} ${escapeHtml(p.team || '')}</div>
      </div>
      <div style="text-align:right">
        <div class="mono" style="font-weight:700; font-size:12px">$${Number(p.auction ?? 0)}</div>
        <div class="micro faint">${Number(p.weekly ?? p.projected_points ?? 0).toFixed(1)}/wk</div>
      </div>
    </div>`;
}

function severityRank(s) {
  const v = String(s || '').toLowerCase();
  if (/out|ir|injured reserve|pup/.test(v)) return 3;
  if (/doubtful/.test(v)) return 2;
  if (/questionable|limited|dnp/.test(v)) return 1;
  return 0;
}

function isDemoData(meta) {
  const ds = meta?.data_source ?? null;
  return typeof ds === 'string' && ds.toLowerCase() === 'demo';
}
