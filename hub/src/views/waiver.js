import { fetchWaiver, fetchNews, fetchComparison, fetchRostersFull, fetchRoster } from '../api.js';
import { posBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';
import { escapeHtml, safeUrl } from '../lib/escape.js';
import { openPlayerModal } from '../components/playerModal.js';
import { getSelectedTeamId, setSelectedTeamId, renderTeamSelector, bindTeamSelector } from '../components/teamSelector.js';

export async function renderWaiver(root) {
  // Bulk-first, same pattern as team.js: one /rosters-full pass gets every
  // team's owner_id so the selector doesn't need a per-team fetch.
  const bulkData = await fetchRostersFull().catch(() => null);
  const leagueRosters = bulkData?.leagueRosters || bulkData?.allTeams || [];

  let selectedId = getSelectedTeamId();
  if (!selectedId && leagueRosters.length) {
    selectedId = String(leagueRosters[0].roster_id);
    setSelectedTeamId(selectedId);
  }
  const selectedTeam = leagueRosters.find(t => String(t.roster_id) === String(selectedId));
  const ownerId = selectedTeam?.owner_id || null;

  const [waiver, news, compData] = await Promise.all([
    fetchWaiver({ owner_id: ownerId }), fetchNews(), fetchComparison({ limit: 2000 }).catch(() => ({ players: [] })),
  ]);
  const recs = waiver.recommendations || [];
  // why merge (user-caught live bug, 2026-09-10): without this, opening a
  // player card here fell to playerModal.js's $1/0 honest-empty floor
  // instead of the real season-stat/auction data that already exists —
  // same fix as projections.js (93b7b91/d910ac1).
  const compById = new Map((compData.players || []).map(c => [String(c.player_id), c]));
  for (const r of recs) {
    const c = compById.get(String(r.player_id));
    if (c) {
      r.market_season_stats = c.market_season_stats || null;
      r.auction = c.auction;
      r.gridironAuction = c.auction;
      r.marketAuction = c.marketAuction;
      r.vor = c.vor;
    }
  }
  const trending = news.trending_adds || [];
  const fpNews = news.fantasypros_news || [];

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Waivers</h1>
      <p>Ranked by improvement over roster, not raw points.</p>
      ${leagueRosters.length ? `<div style="margin-top:8px; max-width:280px">${renderTeamSelector(leagueRosters, selectedId)}</div>` : ''}
      <details style="margin-top:8px" aria-label="How waiver priority works">
        <summary style="cursor:pointer; font-weight:600" title="Toggle waiver explainer">How priority works</summary>
        <p style="margin-top:8px">Ranked by <code class="inline">improvement_over_roster</code> (<code class="inline">decision.py:get_waiver_priority</code>), not raw points. A 12-pt WR who replaces your 4-pt WR is worth more than a 13-pt QB you don't need.</p>
      </details>
    </div>

    ${fpNews.length ? `
      <div class="card reveal in" style="margin-top:12px">
        <div class="card-header"><h3>Breaking News &amp; Fantasy Impact</h3><span class="kicker">from FantasyPros API</span></div>
        <div class="card-body" style="display:flex; flex-direction:column; gap:10px">
          ${fpNews.slice(0, 6).map(n => `
            <div style="padding:10px 12px; background:var(--surface-raised); border-radius:8px; border:1px solid var(--border)">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px">
                <strong style="font-size:14px; color:var(--text)">${escapeHtml(n.title || '')}</strong>
                <span class="mono" style="font-size:11px; color:var(--text-muted)">${escapeHtml(n.created_formated || '')}</span>
              </div>
              ${n.link ? (() => { const href = safeUrl(n.link); return href ? `<a href="${href}" target="_blank" rel="noopener" style="font-size:12px; color:var(--sky); text-decoration:none">Read on FantasyPros →</a>` : ''; })() : ''}
            </div>
          `).join('')}
        </div>
      </div>
    ` : ``}

    ${trending.length ? `
      <div class="card reveal in" style="margin-top:12px">
        <div class="card-header"><h3>Trending adds</h3><span class="kicker">from Sleeper — ${trending.length} players</span></div>
        <div class="card-body row" style="gap:8px; flex-wrap:wrap">
          ${trending.slice(0,12).map(t=>`<button class="badge trending-badge" data-trending-pid="${t.player_id || ''}" style="background:var(--sky-dim); color:var(--sky); border:1px solid rgba(56,189,248,0.2); display:inline-flex; align-items:center; gap:6px; cursor:pointer; font:inherit; padding:4px 8px">${t.player_id ? playerAvatar({player_id: t.player_id, player_name: t.player_name || '', position: t.position || '', team: t.team || ''}, 20) : ''}${escapeHtml(t.player_name || t.player_id || JSON.stringify(t).slice(0,24))}${t.count ? `<span class="mono" style="font-size:10px; opacity:0.7">${(t.count/1000).toFixed(1)}k</span>` : ''}</button>`).join('')}
        </div>
      </div>
    ` : ``}

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Priority board</h3><span class="kicker">${recs.length ? `${recs.length} candidates` : 'no data'}</span></div>
      <div class="card-body" style="padding:0">
        ${recs.length ? `
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th aria-sort="none">#</th><th aria-sort="none">Player</th><th aria-sort="none">Pos</th><th aria-sort="none">Proj</th><th aria-sort="none">Δ roster</th><th aria-sort="none">Replaces</th><th aria-sort="none">Conf</th></tr></thead>
              <tbody>
                ${recs.map(r=>`
                  <tr data-pid="${escapeHtml(r.player_id || '')}" data-team="${r.team || ''}" style="--team-accent:${getTeamColor((r.team||'').toUpperCase())}; cursor:pointer">
                    <td class="mono">${r.waiver_priority ?? '—'}</td>
                    <td><div class="player-cell">${playerAvatar(r, 28)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(r.player_name || r.player_id)}</div><div class="player-cell-sub">${teamLogo(r.team, 14)} ${escapeHtml(r.team || '')}</div></div></div></td>
                    <td>${posBadge(r.position)}</td>
                    <td class="mono">${Number(r.projected_points ?? 0).toFixed(1)}</td>
                    <td class="mono" style="color:var(--emerald)">+${Number(r.improvement_over_roster ?? 0).toFixed(1)}</td>
                    <td class="faint">${escapeHtml(r.replaces_player_name || r.replaces_player_id || 'open FLEX')}</td>
                    <td class="faint">${r.confidence || '—'}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table></div>
            <div class="player-cards-grid" style="padding:12px">
              ${recs.map(r=>`
                <div class="player-card" data-pid="${escapeHtml(r.player_id || '')}" style="cursor:pointer">
                  <div style="display:flex; justify-content:space-between; align-items:center">
                    <div style="display:flex; align-items:center; gap:8px">
                      ${playerAvatar(r, 32)}
                      <div>
                        <div style="font-weight:600">${escapeHtml(r.player_name || r.player_id)}</div>
                        <div style="font-size:11px; color:var(--text-muted)">${posBadge(r.position)} · ${teamLogo(r.team, 12)} ${escapeHtml(r.team||'')}</div>
                      </div>
                    </div>
                    <div style="text-align:right">
                      <div class="mono" style="color:var(--emerald); font-weight:700">+${Number(r.improvement_over_roster ?? 0).toFixed(1)}</div>
                      <div style="font-size:11px; color:var(--text-muted)">Proj ${Number(r.projected_points ?? 0).toFixed(1)}</div>
                    </div>
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        ` : `<div class="empty">No waiver recommendations yet. Trending above shows recent adds.</div>`}
      </div>
    </div>
  `;

  bindTeamSelector(() => renderWaiver(root));

  root.querySelectorAll('[data-pid]').forEach(el => {
    el.addEventListener('click', () => {
      const pid = el.getAttribute('data-pid');
      const found = recs.find(r => String(r.player_id) === String(pid));
      if (found) openPlayerModal(found, root);
    });
  });

  // Audit 22.0: make trending badges clickable — opens player modal
  root.querySelectorAll('[data-trending-pid]').forEach(el => {
    el.addEventListener('click', () => {
      const pid = el.getAttribute('data-trending-pid');
      const t = trending.find(x => String(x.player_id) === String(pid));
      if (t) {
        openPlayerModal({player_id: t.player_id, player_name: t.player_name || '', position: t.position || '', team: t.team || ''}, root);
      }
    });
  });
}
