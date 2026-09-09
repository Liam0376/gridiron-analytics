// hub/src/views/props.js — Player props: model fair lines vs manual book lines.
// Read-only reads (GET /props/edges on :8000); manual entry POSTs to the
// MODEL directly (hub proxy never writes — isolation contract). Never shows
// "LOCK" — chips read VALUE / TRACKING / NO EDGE (RG copy rule).
import { fetchPropEdges, postPropLine } from '../api.js';
import { posBadge } from '../components/badges.js';
import { escapeHtml } from '../lib/escape.js';

const MARKETS = [
  'passing_yards', 'passing_tds', 'rushing_yards',
  'receiving_yards', 'receptions', 'anytime_td',
];
const SIDES = ['over', 'under', 'yes', 'no'];

function edgeChip(decision) {
  const d = String(decision || 'NO EDGE');
  const kind = d === 'VALUE' ? 'value' : d.startsWith('NO EDGE (unknown)') ? 'unknown' : 'none';
  const bg = kind === 'value' ? 'var(--emerald-dim)' : kind === 'unknown' ? 'var(--amber-dim)' : 'rgba(0,0,0,0.05)';
  const fg = kind === 'value' ? 'var(--emerald)' : kind === 'unknown' ? 'var(--amber)' : 'var(--text-muted)';
  return `<span class="badge" style="background:${bg}; color:${fg}; border:1px solid var(--border)">${escapeHtml(d)}</span>`;
}

function shadowChip(status, calibration) {
  const label = status === 'trusted' ? 'shadow ✓' : 'tracking';
  const cal = calibration && calibration !== 'edges_on' ? ` · cal: ${calibration}` : '';
  return `<span class="mono" style="font-size:11px; color:var(--text-faint)">${escapeHtml(label)}${escapeHtml(cal)}</span>`;
}

function fmtLine(e) {
  if (e.side === 'yes' || e.side === 'no') return escapeHtml(e.side.toUpperCase());
  const line = e.book_line == null ? '—' : Number(e.book_line).toFixed(1);
  return `${escapeHtml(e.side)} ${line}`;
}

function fmtPrice(p) {
  if (p == null) return '—';
  const n = Number(p);
  return n > 0 ? `+${n}` : `${n}`;
}

export async function renderProps(root) {
  let payload;
  try {
    payload = await fetchPropEdges({});
  } catch (_) {
    payload = { edges: [], meta: { cold: true } };
  }
  const edges = payload.edges || [];
  const cold = Boolean(payload.meta && payload.meta.cold);
  const needsCalibrationNote = edges.some(e => e.calibration_verdict !== 'edges_on')
    || edges.some(e => e.shadow_status !== 'trusted');

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Props</h1>
      <p>Model fair lines vs your book lines. Edges are tracked estimates, not tips.</p>
      <details style="margin-top:8px" aria-label="How props edges work">
        <summary style="cursor:pointer; font-weight:600" title="Toggle props explainer">How edges work</summary>
        <p style="margin-top:8px">Fair line = stat-projection median (<code class="inline">stat_projector.py</code>). Edge needs model−book ≥ 5pp <em>and</em> EV ≥ +4%/unit, non-empty history, and is labeled by shadow state (20 resolved) + 2025 calibration. Only <code class="inline">passing_yards</code> earned edge labels in calibration — the rest stay tracking.</p>
      </details>
    </div>

    <div class="card reveal in" role="note" aria-label="Responsible gambling notice"
         style="margin-top:12px; border-left:4px solid var(--amber)">
      <div class="card-body" style="font-size:13px; color:var(--text)">
        <strong>Entertainment only.</strong> Props carry vig — books price both sides below fair.
        Model edges are uncertain estimates from heuristic sigmas, not predictions of profit.
        Never bet more than you can afford to lose.
      </div>
    </div>

    ${needsCalibrationNote && !cold ? `
    <div class="card reveal in" style="margin-top:12px">
      <div class="card-body" style="font-size:12px; color:var(--text-muted)">
        Model-implied, partially uncalibrated — some markets are below 20 resolved shadow samples
        or failed 2025 calibration gates. Those rows read TRACKING until they earn it.
        Kicker props excluded v1 (thinnest coverage).
      </div>
    </div>` : ``}

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Edge board</h3><span class="kicker">${edges.length ? `${edges.length} lines` : cold ? 'model cold' : 'no lines'}</span></div>
      <div class="card-body" style="padding:0">
        ${cold ? `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            Model cache is cold — run <code class="inline">POST /refresh</code> (Dashboard → Sync),
            then enter book lines below. Lines can be stored while cold; edges compute after refresh.
          </div>` : edges.length ? `
          <div class="responsive-view">
            <div class="table-wrap" style="border:0; border-radius:0"><table>
              <thead><tr><th aria-sort="none">Player</th><th aria-sort="none">Market</th><th aria-sort="none">Fair</th><th aria-sort="none">Book</th><th aria-sort="none">P(model)</th><th aria-sort="none">Edge</th><th aria-sort="none">EV/u</th><th aria-sort="none">Status</th></tr></thead>
              <tbody>
                ${edges.map(e => `
                  <tr>
                    <td><span class="mono" style="font-weight:700">${escapeHtml(e.player_name || e.player_id || '')}</span> ${posBadge(e.position)}<br><span class="mono" style="font-size:11px; color:var(--text-faint)">${escapeHtml(e.team || '')} · ${escapeHtml(e.book || 'manual')}</span></td>
                    <td class="mono" style="font-size:12px">${escapeHtml(e.market || '')}</td>
                    <td class="mono">${e.fair_line == null ? '—' : Number(e.fair_line).toFixed(1)}${e.sigma == null ? '' : `<br><span style="font-size:11px; color:var(--text-faint)">±${Number(e.sigma).toFixed(1)}</span>`}</td>
                    <td class="mono">${fmtLine(e)} @ ${fmtPrice(e.book_price)}</td>
                    <td class="mono">${e.p_model == null ? '—' : Number(e.p_model).toFixed(3)}</td>
                    <td class="mono">${e.edge_pp == null ? '—' : (Number(e.edge_pp) >= 0 ? '+' : '') + (Number(e.edge_pp) * 100).toFixed(1) + 'pp'}</td>
                    <td class="mono">${e.ev_per_unit == null ? '—' : (Number(e.ev_per_unit) >= 0 ? '+' : '') + (Number(e.ev_per_unit) * 100).toFixed(1) + '%'}</td>
                    <td>${edgeChip(e.decision)}<br>${shadowChip(e.shadow_status, e.calibration_verdict)}</td>
                  </tr>`).join('')}
              </tbody>
            </table></div>
          </div>` : `
          <div style="padding:20px; font-size:13px; color:var(--text-muted)">
            No book lines stored yet — add your first line below. Lines are manual-only (no odds feed, $0 rule).
          </div>`}
      </div>
    </div>

    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Add a book line</h3><span class="kicker">manual entry → model :8000</span></div>
      <div class="card-body">
        <form id="props-form" style="display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:10px" aria-label="Add a book line">
          <label style="font-size:12px">Player ID <input name="player_id" required maxlength="64" placeholder="2544" style="width:100%"></label>
          <label style="font-size:12px">Market <select name="market" style="width:100%">${MARKETS.map(m => `<option value="${m}">${m}</option>`).join('')}</select></label>
          <label style="font-size:12px">Side <select name="side" style="width:100%">${SIDES.map(s => `<option value="${s}">${s}</option>`).join('')}</select></label>
          <label style="font-size:12px">Line <input name="line" type="number" step="0.5" placeholder="over/under only" style="width:100%"></label>
          <label style="font-size:12px">Price <input name="price" type="number" step="1" required placeholder="-110" style="width:100%"></label>
          <label style="font-size:12px">Book <input name="book" maxlength="32" placeholder="manual" style="width:100%"></label>
          <label style="font-size:12px">Week <input name="week" type="number" min="1" max="18" required placeholder="5" style="width:100%"></label>
          <div style="grid-column:1/-1; display:flex; gap:10px; align-items:center">
            <button type="submit" class="sidebar-tab" style="border:1px solid var(--border-active); padding:8px 16px">Store line</button>
            <span id="props-form-msg" class="mono" style="font-size:12px" role="status" aria-live="polite"></span>
          </div>
        </form>
      </div>
    </div>`;
  bindPropsForm(root);
}

function bindPropsForm(root) {
  const form = root.querySelector('#props-form');
  if (!form) return;
  const msg = root.querySelector('#props-form-msg');
  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const fd = new FormData(form);
    const market = String(fd.get('market') || '');
    const side = String(fd.get('side') || '');
    const lineRaw = String(fd.get('line') || '').trim();
    const isPoisson = market === 'anytime_td';
    // why mirror API validation client-side: instant feedback, but the
    // server re-validates (422) — client checks are convenience, not trust.
    if (!isPoisson && (side === 'yes' || side === 'no')) {
      msg.textContent = 'Over/under markets take side over/under.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    if (isPoisson && (side === 'over' || side === 'under')) {
      msg.textContent = 'anytime_td takes side yes/no.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    if (!isPoisson && !lineRaw) {
      msg.textContent = 'Over/under requires a line.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    if (isPoisson && lineRaw) {
      msg.textContent = 'anytime_td takes no line.';
      msg.style.color = 'var(--crimson)';
      return;
    }
    const body = {
      player_id: String(fd.get('player_id') || '').trim(),
      market, side,
      price: Number(fd.get('price')),
      book: String(fd.get('book') || '').trim() || 'manual',
      week: Number(fd.get('week')),
    };
    if (lineRaw) body.line = Number(lineRaw);
    msg.textContent = 'Storing…';
    msg.style.color = 'var(--text-muted)';
    try {
      const res = await postPropLine(body);
      const edge = res.edge;
      msg.textContent = edge
        ? `Stored. Edge: ${edge.decision} (P=${Number(edge.p_model).toFixed(3)}, EV=${(Number(edge.ev_per_unit) * 100).toFixed(1)}%/u).`
        : `Stored. ${(res.note || 'Edge computes after refresh.').replace(/</g, '')}`;
      msg.style.color = 'var(--emerald)';
      // Simplest honest refresh: re-render the tab (edges cache was invalidated).
      renderProps(root);
    } catch (err) {
      msg.textContent = `Not stored: ${String(err && err.message || err).slice(0, 160)}`;
      msg.style.color = 'var(--crimson)';
    }
  });
}
