import { fetchTrade } from '../api.js';

export async function renderTrade(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const teamA = params.get('team_a') || '';
  const teamB = params.get('team_b') || '';

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Trade Lab</h1>
      <p>Evaluates <code class="inline">team_a vs team_b</code> via <code class="inline">decision.py:evaluate_trade</code> — weekly + rest-of-season (<code class="inline">current_week=4→18</code> default). Enter roster <code class="inline">owner_id</code>s or leave blank to see the form.</p>
    </div>
    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body row" style="gap:12px">
        <label class="search-mini" style="flex:1"><span class="micro faint" style="margin-right:6px">Team A</span><input id="teamA" placeholder="owner_id (e.g. u1)" value="${escapeHtml(teamA)}" /></label>
        <label class="search-mini" style="flex:1"><span class="micro faint" style="margin-right:6px">Team B</span><input id="teamB" placeholder="owner_id" value="${escapeHtml(teamB)}" /></label>
        <button class="btn btn-primary" id="evalBtn">Evaluate</button>
      </div>
    </div>
    <div id="tradeResult" style="margin-top:16px"></div>
    <div class="faint" style="margin-top:12px; font:400 11px 'Instrument Sans', sans-serif">Tip: find <code class="inline">owner_id</code>s in <strong>Matchups</strong> or via <code class="inline">GET /hub-api/rosters</code> when <code class="inline">hub/server.py</code> is running.</div>
  `;

  const resEl = root.querySelector('#tradeResult');
  const btn = root.querySelector('#evalBtn');
  const aIn = root.querySelector('#teamA');
  const bIn = root.querySelector('#teamB');

  async function run() {
    const a = (aIn.value || '').trim();
    const b = (bIn.value || '').trim();
    if (!a || !b) { resEl.innerHTML = `<div class="alert alert-info">Enter both team IDs to evaluate.</div>`; return; }
    location.hash = `trade?team_a=${encodeURIComponent(a)}&team_b=${encodeURIComponent(b)}`;
    resEl.innerHTML = `<div class="empty">Evaluating…</div>`;
    try {
      const data = await fetchTrade(a,b);
      if (!data) { resEl.innerHTML = `<div class="alert alert-warn">No data — need <code class="inline">POST /refresh</code> first or hub fallback.</div>`; return; }
      resEl.innerHTML = `
        <div class="grid grid-2">
          <div class="card"><div class="card-header"><h3>Result</h3></div><div class="card-body">
            <div class="stat"><div class="stat-value">${escapeHtml(data.winner || data.recommendation || '—')}</div><div class="stat-label">Winner</div></div>
            <div class="divider"></div>
            <div class="row" style="gap:16px">
              <div class="stat"><div class="stat-value mono">${Number(data.team_a_weeks_value ?? data.team_a_value ?? 0).toFixed(1)}</div><div class="stat-label">Team A pts</div></div>
              <div class="stat"><div class="stat-value mono">${Number(data.team_b_weeks_value ?? data.team_b_value ?? 0).toFixed(1)}</div><div class="stat-label">Team B pts</div></div>
              <div class="stat"><div class="stat-value mono" style="color:var(--amber)">${Number(data.value_difference ?? 0).toFixed(1)}</div><div class="stat-label">Δ</div></div>
            </div>
            <div class="faint" style="font:400 12px 'Instrument Sans', sans-serif; margin-top:10px">${escapeHtml(data.recommendation || '')}</div>
          </div></div>
          <div class="card"><div class="card-header"><h3>How to read</h3></div><div class="card-body">
            <div class="alert alert-ok" style="font-size:12px">Weekly points are summed; ROS is <code class="inline">weeks_remaining × weekly</code> + decay. If bars would overlap (not shown yet), it's a fair trade regardless of the label.</div>
            <pre style="margin:12px 0 0; background:var(--surface-raised); border:1px solid var(--border); border-radius:10px; padding:12px; overflow:auto; font:500 11px 'JetBrains Mono', monospace; color:var(--text-muted)">${escapeHtml(JSON.stringify(data, null, 2)).slice(0,2000)}</pre>
          </div></div>
        </div>
      `;
    } catch (e) {
      resEl.innerHTML = `<div class="alert alert-bad">Failed: ${escapeHtml(String(e))}</div>`;
    }
  }

  btn.addEventListener('click', run);
  [aIn,bIn].forEach(el=>el.addEventListener('keydown', e=>{ if(e.key==='Enter') run(); }));
  if (teamA && teamB) run();
}
function escapeHtml(s){ return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;'); }
