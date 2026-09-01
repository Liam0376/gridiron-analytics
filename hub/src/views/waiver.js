import { fetchWaiver, fetchNews } from '../api.js';
import { posBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { getTeamColor } from '../components/teamColors.js';

export async function renderWaiver(root) {
  const [waiver, news] = await Promise.all([fetchWaiver(), fetchNews()]);
  const recs = waiver.recommendations || [];
  const trending = news.trending_adds || [];
  const fpNews = news.fantasypros_news || [];

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Waiver Wire</h1>
      <p>Ranked by <code class="inline">improvement_over_roster</code> (<code class="inline">decision.py:get_waiver_priority</code>), not raw points. A 12-pt WR who replaces your 4-pt WR is worth more than a 13-pt QB you don't need.</p>
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
              ${n.link ? `<a href="${n.link}" target="_blank" rel="noopener" style="font-size:12px; color:var(--sky); text-decoration:none">Read on FantasyPros →</a>` : ''}
            </div>
          `).join('')}
        </div>
      </div>
    ` : ``}

    ${trending.length ? `
      <div class="card reveal in" style="margin-top:12px">
        <div class="card-header"><h3>Trending adds</h3><span class="kicker">from Sleeper</span></div>
        <div class="card-body row" style="gap:8px; flex-wrap:wrap">
          ${trending.slice(0,12).map(t=>`<span class="badge trending-badge" style="background:var(--sky-dim); color:var(--sky); border:1px solid rgba(56,189,248,0.2); display:inline-flex; align-items:center; gap:6px">${t.player_id ? playerAvatar({player_id: t.player_id, player_name: t.player_name || '', position: t.position || '', team: t.team || ''}, 20) : ''}${escapeHtml(t.player_name || t.player_id || JSON.stringify(t).slice(0,24))}</span>`).join('')}
        </div>
      </div>
    ` : ``}

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Priority board</h3><span class="kicker">${recs.length ? `${recs.length} candidates` : 'no data'}</span></div>
      <div class="card-body" style="padding:0">
        ${recs.length ? `
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Proj</th><th>Δ roster</th><th>Replaces</th><th>Conf</th></tr></thead>
              <tbody>
                ${recs.map(r=>`
                  <tr data-team="${r.team || ''}" style="--team-accent:${getTeamColor((r.team||'').toUpperCase())}">
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
                <div class="player-card">
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
        ` : `<div class="empty">No waiver recs — needs <code class="inline">/recommendations/waiver</code> (cache warm) or <code class="inline">hub/server.py</code> fallback. Trending above still shows who the league is adding.</div>`}
      </div>
    </div>
  `;
}
function escapeHtml(s){ return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
