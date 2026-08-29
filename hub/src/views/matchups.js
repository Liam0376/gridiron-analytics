import { fetchMatchups } from '../api.js';
import { windBadge } from '../components/badges.js';

export async function renderMatchups(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const week = params.get('week') ? Number(params.get('week')) : null;
  const data = await fetchMatchups({ week });

  const currentWeek = data.week ?? week ?? '';
  const league = data.leagueMatchups || [];
  const slate = data.nflSlate || [];

  const weekPicker = `
    <div class="row" style="gap:8px">
      <span class="kicker">Week</span>
      <div class="filters">
        ${Array.from({length:18},(_,i)=>i+1).map(w=>`<button class="chip ${String(w)===String(currentWeek)?'active':''}" data-week="${w}">${w}</button>`).join('')}
        <button class="chip" data-week="">All</button>
      </div>
      <span class="faint" style="font:400 11px 'Instrument Sans', sans-serif; margin-left:8px">Default is <code class="inline">_compute_nfl_week()</code> — preseason returns 0.</span>
    </div>
  `;

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Matchups</h1>
      <p>Your league's head-to-heads and the full NFL slate for the selected week, with wind-aware badges. Weather is read from <code class="inline">weather</code> table — currently <strong>⚠ placeholder coords</strong> until stadium mapping lands.</p>
    </div>
    <div class="card reveal in" style="margin-top:12px"><div class="card-body">${weekPicker}</div></div>

    <div class="grid grid-2" style="margin-top:16px">
      <div class="card reveal in">
        <div class="card-header"><h3>Your league</h3><span class="kicker">${league.length ? `${league.length} rosters` : 'no data'}</span></div>
        <div class="card-body" style="padding:0">
          ${league.length ? `
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th>Roster</th><th>Matchup</th><th>Pts</th><th>Starters</th></tr></thead>
              <tbody>
                ${league.map(m=>`
                  <tr>
                    <td class="mono">${m.roster_id}</td>
                    <td><span class="badge" style="background:var(--surface-raised); border:1px solid var(--border)">${m.matchup_id ?? '—'}</span></td>
                    <td class="mono">${m.points != null ? Number(m.points).toFixed(1) : '—'}</td>
                    <td class="faint" style="max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${Array.isArray(m.starters) ? m.starters.slice(0,6).join(', ') : (m.starters || '—')}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table></div>
          ` : `<div class="empty">No <code class="inline">sleeper_matchups</code> for week ${currentWeek || '—'}. Run <code class="inline">POST /refresh</code> in-season, or check <code class="inline">hub/server.py</code> fallback.</div>`}
        </div>
      </div>

      <div class="card reveal in">
        <div class="card-header"><h3>NFL slate</h3><span class="kicker">${slate.length ? `${slate.length} games` : 'no data'}</span></div>
        <div class="card-body" style="padding:0">
          ${slate.length ? `
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th>Game</th><th>Stadium</th><th>Time</th><th>Wind</th><th>Precip</th></tr></thead>
              <tbody>
                ${slate.map(g=>`
                  <tr>
                    <td><span class="mono">${g.away_team || g.away || '—'}</span> <span class="faint">@</span> <span class="mono">${g.home_team || g.home || '—'}</span></td>
                    <td class="faint">${g.stadium || '—'}</td>
                    <td class="micro" style="color:var(--text-muted)">${g.gameday || ''} ${g.gametime || ''}</td>
                    <td>${windBadge(g.wind_mph)}</td>
                    <td class="mono" style="font-size:12px">${g.precip_prob != null ? `${g.precip_prob}%` : '—'} ${g.placeholder ? '<span class="badge" style="background:var(--amber-dim); color:var(--amber); margin-left:6px">⚠ placeholder</span>' : ''}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table></div>
          ` : `<div class="empty">No schedule for week ${currentWeek || '—'}. Via <code class="inline">adapters/schedule.py:get_schedule</code> (hub proxy). Preseason (<code class="inline">week 0</code>) has no games.</div>`}
        </div>
      </div>
    </div>
  `;

  root.querySelectorAll('[data-week]').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const w = btn.getAttribute('data-week');
      location.hash = `matchups${w ? `?week=${w}` : ''}`;
    });
  });
}
