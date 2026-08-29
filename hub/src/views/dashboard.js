import { fetchMeta, fetchRefreshLog, computeStaleness } from '../api.js';

export async function renderDashboard(root) {
  const meta = await fetchMeta();
  const log = await fetchRefreshLog();
  const stale = computeStaleness(meta.lastUpdated || meta.last_updated || log.entries?.[0]?.ran_at);
  const sources = log.entries?.slice(0,4) || [];

  const scoring = meta.scoring_settings || {};
  const rosterPos = meta.roster_positions || [];

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Command Center</h1>
      <p>Zero-token, fully local. Data comes from your daily <code class="inline">launchd → POST /refresh → SQLite WAL</code> pipeline. Hub only reads — it never writes or calls an LLM.</p>
    </div>

    <div class="grid grid-3 reveal in" style="margin-top:16px">
      <div class="card">
        <div class="card-header"><h3>Season</h3><span class="kicker">${stale.level}</span></div>
        <div class="card-body">
          <div class="row">
            <div class="stat"><div class="stat-value mono">${meta.season ?? '—'}</div><div class="stat-label">Season</div></div>
            <div class="stat"><div class="stat-value mono">${meta.week ?? '—'}</div><div class="stat-label">Week (1–18)</div></div>
            <div class="spacer"></div>
            <div class="badge" style="background:${stale.level==='fresh'?'var(--emerald-dim)':stale.level==='stale'?'var(--amber-dim)':'rgba(255,255,255,0.06)'}; color:${stale.level==='fresh'?'var(--emerald)':stale.level==='stale'?'var(--amber)':'var(--text-muted)'}; border:1px solid var(--border)">${stale.label}</div>
          </div>
          <div class="divider"></div>
          <div class="faint" style="font: 500 12px 'Fragment Mono', monospace;">${meta.lastUpdated ? `Last updated: ${new Date(meta.lastUpdated).toLocaleString()}` : 'No timestamp — cache cold or hub/server.py not running'}</div>
          <div class="faint" style="font: 400 11px 'Instrument Sans', sans-serif; margin-top:6px;">Manual refresh: <code class="inline">curl -X POST http://127.0.0.1:8000/refresh</code></div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3>League</h3><span class="kicker">Fantasy Bahamas</span></div>
        <div class="card-body">
          <div class="row" style="gap:16px">
            <div class="stat"><div class="stat-value mono">${rosterPos.length ? rosterPos.length : '16'}</div><div class="stat-label">Roster slots</div></div>
            <div class="stat"><div class="stat-value mono">${rosterPos.filter(p=>p==='FLEX').length || 2}</div><div class="stat-label">FLEX</div></div>
            <div class="stat"><div class="stat-value mono">${scoring.rec ?? 1.0}</div><div class="stat-label">PPR</div></div>
          </div>
          <div class="divider"></div>
          <div class="row" style="gap:8px; flex-wrap:wrap">
            ${(rosterPos.length?rosterPos:["QB","RB","RB","WR","WR","TE","FLEX","FLEX","K","DEF","BN","BN","BN","BN","IR","IR"]).map(p=>`<span class="badge" style="background:var(--surface-raised); border:1px solid var(--border); color:var(--text-muted)">${p}</span>`).join('')}
          </div>
          <div class="faint" style="font: 400 11px 'Instrument Sans', sans-serif; margin-top:10px;">Pulled live from Sleeper via <code class="inline">get_league_settings</code> — never hardcoded.</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h3>Refresh log</h3><span class="kicker">last 4</span></div>
        <div class="card-body" style="padding:0">
          ${sources.length ? `<table><thead><tr><th>Source</th><th>At</th><th>Status</th></tr></thead><tbody>
            ${sources.map(s=>`<tr><td class="mono" style="font-size:12px">${s.source}</td><td class="micro" style="color:var(--text-muted)">${new Date(s.ran_at).toLocaleString()}</td><td>${s.success ? `<span class="badge" style="background:var(--emerald-dim); color:var(--emerald)">ok</span>` : `<span class="badge" style="background:var(--crimson-dim); color:var(--crimson)">fail</span>`}</td></tr>`).join('')}
          </tbody></table>` : `<div class="empty">No log yet — run <code class="inline">hub/server.py</code> to enable DB fallback, or hit <code class="inline">POST /refresh</code></div>`}
        </div>
      </div>
    </div>

    <div class="grid grid-2 reveal in" style="margin-top:16px">
      <div class="card">
        <div class="card-header"><h3>Zero-token guarantee</h3></div>
        <div class="card-body">
          <div class="alert alert-ok">✓ Hub never calls an LLM. Projections are pure Python math (<code class="inline">projection.py</code> + <code class="inline">conformal.qhat</code>), tierlists are deterministic sorts, search is client-side filter.</div>
          <ul style="margin:12px 0 0; padding-left:18px; color:var(--text-muted); font:400 13px 'Instrument Sans', sans-serif; line-height:1.6">
            <li><strong style="color:var(--text)">127.0.0.1 only</strong> — model <code class="inline">:8000</code>, hub <code class="inline">:8001</code>. No <code class="inline">0.0.0.0</code>, no tunnel.</li>
            <li><strong style="color:var(--text)">Read-only DB</strong> — hub opens <code class="inline">fantasy.db?mode=ro</code>. Writes are rejected by SQLite itself.</li>
            <li><strong style="color:var(--text)">No model edits</strong> — hub vendors math; it never does <code class="inline">import ffanalytics</code> at runtime.</li>
          </ul>
        </div>
      </div>
      <div class="card">
        <div class="card-header"><h3>What to do now</h3></div>
        <div class="card-body" style="display:flex; flex-direction:column; gap:10px">
          <div class="row"><span class="badge" style="background:var(--amber-dim); color:var(--amber); border:1px solid var(--border-active)">1</span> <span>Open <a href="http://127.0.0.1:8000/docs" target="_blank">127.0.0.1:8000/docs</a> → POST /refresh (or <code class="inline">curl</code> above)</span></div>
          <div class="row"><span class="badge" style="background:var(--amber-dim); color:var(--amber); border:1px solid var(--border-active)">2</span> <span>Go to <strong>Projections</strong> — search <code class="inline">pos:WR wind>15</code> to see wind-dinged receivers</span></div>
          <div class="row"><span class="badge" style="background:var(--amber-dim); color:var(--amber); border:1px solid var(--border-active)">3</span> <span>Check <strong>My Roster</strong> — overlapping intervals = toss-up, not a confident start</span></div>
          <div class="alert alert-info" style="margin-top:6px">Weather currently shows <strong>⚠ placeholder</strong> (coords fixed to 40.0,−74.0 in <code class="inline">refresh.py:256</code>) until stadium map lands. Penalty math is still visible for audit.</div>
        </div>
      </div>
    </div>
  `;
}
