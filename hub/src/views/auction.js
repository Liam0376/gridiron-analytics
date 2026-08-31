import { fetchProjections, fetchComparison } from '../api.js';
import { posBadge } from '../components/badges.js';
import { playerAvatar } from '../components/playerAvatar.js';
import { teamLogo } from '../components/teamLogo.js';
import { playerCard } from '../components/playerCard.js';
import { getTeamColor } from '../components/teamColors.js';

const BUDGET = 200;
const TEAMS = 12;
const ROSTER_SIZE = 14; // 10 starters + 4 bench
const SEASON_GAMES = 17;
const STORE_KEY = 'ffba-auction-draft';

function loadDraftState() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return { drafted: {}, myRoster: [], myBudget: BUDGET, nominations: [] };
}

function saveDraftState(state) {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch (_) {}
}

function edgeBadgeAuction(edge) {
  if (edge === 'BUY') return `<span class="badge" style="background:var(--emerald-dim); color:var(--emerald); border:1px solid rgba(16,185,129,0.22); font-size:10px">▲ BUY</span>`;
  if (edge === 'SELL') return `<span class="badge" style="background:var(--crimson-dim); color:var(--crimson); border:1px solid rgba(239,68,68,0.22); font-size:10px">▼ SELL</span>`;
  return `<span class="badge" style="background:rgba(255,255,255,0.06); color:var(--text-faint); border:1px solid var(--border); font-size:10px">—</span>`;
}
function deltaSeasonBadge(d) {
  if (d == null) return `<span class="mono" style="color:var(--text-faint)">—</span>`;
  const v = Number(d);
  const color = v > 8 ? 'var(--emerald)' : v < -8 ? 'var(--crimson)' : 'var(--text-muted)';
  const arrow = v > 8 ? '↑' : v < -8 ? '↓' : '·';
  const sign = v > 0 ? '+' : '';
  return `<span class="mono" style="color:${color}; font-weight:700; font-size:11px">${arrow} ${sign}${v.toFixed(0)}</span>`;
}

export async function renderAuction(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const budget = Number(params.get('budget') || BUDGET);

  const [data, compRaw] = await Promise.all([
    fetchProjections({}),
    fetchComparison({ limit: 800 }).catch(() => ({ players: [], count: 0, fetched_at: null, meta: {} })),
  ]);
  let players = data.players || [];
  if (!players.length) {
    root.innerHTML = `
      <div class="hero reveal in"><h1>Auction Draft</h1><p>No projection data. Run <code class="inline">bash hub/start.sh --auto</code> first.</p></div>`;
    return;
  }

  const compById = new Map((compRaw.players || []).map(c => [String(c.player_id), c]));
  const hasComparison = compById.size > 0;
  let compareAuctionEnabled = hasComparison;
  // allow toggle via localStorage
  try { const v = localStorage.getItem('ffba-auction-compare'); if (v === '0') compareAuctionEnabled = false; if (v === '1' && hasComparison) compareAuctionEnabled = true; } catch {}

  const state = loadDraftState();

  // Full-season ROS (17 games for pre-draft)
  const remaining = SEASON_GAMES;
  const rosPlayers = players.map(p => {
    const pid = String(p.player_id);
    const c = compById.get(pid);
    // Prefer comparison model_points (weekly projection from stat_projector wk10) if available
    const weeklyModel = c && c.model_points != null ? Number(c.model_points) : Number(p.projected_points ?? p.point_estimate ?? 0);
    const weeklyMarket = c && c.market_points != null ? Number(c.market_points) : null;
    const ros = weeklyModel * remaining;
    // Prefer FantasyPros season total (596 full stat season) over Sleeper weekly×17 (98 starters only)
    const seasonMarketFromFP = c && c.market_season_points != null ? Number(c.market_season_points) : null;
    const marketRos = seasonMarketFromFP != null ? seasonMarketFromFP : (weeklyMarket != null ? weeklyMarket * remaining : null);
    const deltaRos = marketRos != null ? +(ros - marketRos).toFixed(1) : null;
    // Season stat deltas — prefer FP season totals (full) over weekly×17 proxy
    let seasonStatDeltas = null;
    if (c && Array.isArray(c.season_stat_deltas) && c.season_stat_deltas.length) {
      seasonStatDeltas = c.season_stat_deltas;
    } else if (c && Array.isArray(c.stat_deltas) && c.stat_deltas.length) {
      seasonStatDeltas = c.stat_deltas.map(s => ({
        ...s,
        modelSeason: s.model != null ? +(s.model * remaining).toFixed(1) : null,
        marketSeason: s.market != null ? +(s.market * remaining).toFixed(1) : null,
        deltaSeason: s.delta != null ? +(s.delta * remaining).toFixed(1) : null,
      }));
    }
    return {
      ...p,
      // overwrite weekly with comparison model weekly for consistency
      weekly: weeklyModel,
      ros,
      marketWeekly: weeklyMarket,
      marketRos,
      deltaRos,
      seasonStatDeltas,
      widthRos: Number(p.width ?? c?.width ?? 5) * Math.sqrt(remaining),
      fp_ecr: c?.fp_ecr ?? null,
      fp_ecr_pos: c?.fp_ecr_pos ?? null,
      fp_adp: c?.fp_adp ?? null,
      fp_tier: c?.fp_tier ?? null,
      delta_rank: c?.delta_rank ?? null,
      edge: c?.edge || 'NEUTRAL',
      edge_score: c?.edge_score ?? 0,
      isDrafted: !!state.drafted[p.player_id],
      draftedBy: state.drafted[p.player_id]?.by || null,
      draftedPrice: state.drafted[p.player_id]?.price || null,
    };
  });

  // Position buckets
  const byPos = { QB:[], RB:[], WR:[], TE:[], K:[], DEF:[] };
  rosPlayers.forEach(p => {
    const pos = (p.position || 'UNK').toUpperCase();
    if (byPos[pos]) byPos[pos].push(p);
    else byPos[pos] = [p];
  });
  Object.values(byPos).forEach(arr => arr.sort((a, b) => b.ros - a.ros));

  // Replacement levels (last starter per position, 12 teams)
  // Roster: 1 QB, 2 RB, 2 WR, 1 TE, 2 FLEX, 1 K, 1 DEF
  const replIdx = { QB: 12-1, RB: 24-1, WR: 24-1, TE: 12-1, K: 12-1, DEF: 12-1 };
  const replPts = {};
  for (const pos of Object.keys(byPos)) {
    const arr = byPos[pos];
    const idx = replIdx[pos] ?? 0;
    replPts[pos] = arr[idx]?.ros ?? (arr[arr.length - 1]?.ros ?? 0);
  }

  // FLEX pool: remaining RB/WR/TE after positional starters
  const flexPool = [
    ...(byPos.RB.slice(24)),
    ...(byPos.WR.slice(24)),
    ...(byPos.TE.slice(12)),
  ].sort((a, b) => b.ros - a.ros);
  const flexRepl = flexPool[24 - 1]?.ros ?? 0; // 2 FLEX * 12 teams

  // Compute VOR
  rosPlayers.forEach(p => {
    const pos = (p.position || '').toUpperCase();
    let baseRepl = replPts[pos] ?? 0;
    if (['RB', 'WR', 'TE'].includes(pos)) baseRepl = Math.max(baseRepl, flexRepl);
    p.repl = baseRepl;
    p.vor = Math.max(0, p.ros - baseRepl);
  });

  // Auction pricing
  const benchSlots = TEAMS * 4;
  const totalStarterBudget = TEAMS * budget - benchSlots * 1;
  const starters = rosPlayers.filter(p => p.vor > 0).sort((a, b) => b.vor - a.vor).slice(0, TEAMS * 10);
  const totalVor = starters.reduce((s, p) => s + p.vor, 0) || 1;
  starters.forEach(p => { p.auction = Math.max(1, Math.round((p.vor / totalVor) * totalStarterBudget)); });
  const benchPlayers = rosPlayers.filter(p => !starters.includes(p));
  benchPlayers.forEach(p => p.auction = 1);
  const allRanked = [...starters, ...benchPlayers].sort((a, b) => b.auction - a.auction || b.ros - a.ros);

  // Assign tiers
  allRanked.forEach((p, i) => {
    if (i < 8) p.tier = 1;
    else if (i < 20) p.tier = 2;
    else if (i < 40) p.tier = 3;
    else if (i < 70) p.tier = 4;
    else p.tier = 5;
  });

  // Positional budget allocation (recommended spend per position)
  const posGroups = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];
  const posBudget = {};
  for (const pos of posGroups) {
    const posStarters = starters.filter(p => (p.position || '').toUpperCase() === pos);
    const posVor = posStarters.reduce((s, p) => s + p.vor, 0);
    const share = posVor / totalVor;
    const posSlots = pos === 'QB' ? 1 : pos === 'RB' ? 2 : pos === 'WR' ? 2 : pos === 'TE' ? 1 : 1;
    posBudget[pos] = {
      recommended: Math.round(share * budget),
      slots: posSlots,
      perSlot: Math.round(share * budget / posSlots),
    };
  }
  // FLEX budget is shared across RB/WR/TE
  const flexBudget = Math.round((budget - Object.values(posBudget).reduce((s, v) => s + v.recommended, 0)));

  // Nomination strategy: players to nominate that drain opponents
  const myRosterPositions = state.myRoster.map(id => {
    const p = rosPlayers.find(x => x.player_id === id);
    return p ? (p.position || '').toUpperCase() : '';
  });
  const myNeeds = {};
  const targetSlots = { QB: 1, RB: 4, WR: 4, TE: 2, K: 1, DEF: 1 }; // starters + depth
  for (const pos of posGroups) {
    const have = myRosterPositions.filter(p => p === pos).length;
    myNeeds[pos] = Math.max(0, (targetSlots[pos] || 1) - have);
  }

  const nominationTargets = allRanked
    .filter(p => !p.isDrafted && p.auction >= 5)
    .filter(p => {
      const pos = (p.position || '').toUpperCase();
      return myNeeds[pos] === 0 || p.tier >= 3;
    })
    .slice(0, 10);

  // Draft tracker stats
  const draftedCount = Object.keys(state.drafted).length;
  const availablePlayers = allRanked.filter(p => !p.isDrafted);
  const myRosterPlayers = state.myRoster.map(id => allRanked.find(p => p.player_id === id)).filter(Boolean);
  const mySpent = myRosterPlayers.reduce((s, p) => s + (state.drafted[p.player_id]?.price || 0), 0);
  const myRemaining = budget - mySpent;
  const myRosterCount = state.myRoster.length;
  const slotsLeft = ROSTER_SIZE - myRosterCount;
  const maxBid = slotsLeft > 1 ? myRemaining - (slotsLeft - 1) : myRemaining;

  // Comparison counts for header — season market is primary (FP CSV 596) with Sleeper weekly fallback
  const buyCount = [...compById.values()].filter(c => c.edge === 'BUY').length;
  const sellCount = [...compById.values()].filter(c => c.edge === 'SELL').length;
  const marketCovered = [...compById.values()].filter(c => c.market_season_points != null || c.market_points != null).length;
  // Filters
  const activePos = params.get('pos') || 'ALL';
  const auctionEdge = params.get('edge') || 'ALL';
  // Sorting: ?sort=auction&dir=-1  (default auction descending = highest to lowest)
  const allowedSort = new Set(['player_name','position','weekly','ros','marketRos','deltaRos','fp_ecr','fp_adp','vor','auction','edge_score','tier']);
  const auctionSortKey = allowedSort.has(params.get('sort')) ? params.get('sort') : 'auction';
  const auctionSortDir = params.get('dir') === '1' ? 1 : -1;

  let filteredPlayers = activePos === 'ALL'
    ? [...availablePlayers]
    : availablePlayers.filter(p => (p.position || '').toUpperCase() === activePos);
  if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') {
    filteredPlayers = filteredPlayers.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
  }
  // Sort: numeric descending is highest to lowest; ascending is lowest to highest
  filteredPlayers.sort((a,b)=>{
    const av = a[auctionSortKey];
    const bv = b[auctionSortKey];
    // handle string vs number, nulls last
    if (av == null && bv == null) return 0;
    if (av == null) return 1;
    if (bv == null) return -1;
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * auctionSortDir;
    if (typeof av === 'string' && typeof bv === 'string') return av.localeCompare(bv) * auctionSortDir;
    return String(av).localeCompare(String(bv)) * auctionSortDir;
  });

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Auction Draft <span class="badge" style="background:var(--color-accent,#16A34A); color:white; margin-left:8px; vertical-align:middle">$${budget}</span></h1>
      <p>Full-season VOR (${SEASON_GAMES}g) → auction $. 2-FLEX league inflates RB/WR/TE. Season totals = <span class="mono" style="color:var(--amber)">Gridiron wk×17</span> vs <span class="mono" style="color:var(--sky)">Market Season — FantasyPros projections (596 players, full stat season)</span> + <span class="mono" style="color:var(--violet)">FP ECR/ADP Tiers</span>. Use Market Δ &amp; Edge to find <strong>$ value leaks</strong> — BUY where Gridiron &gt; Market.</p>
    </div>

    ${hasComparison ? `
    <div class="kpi-row reveal in" style="margin-top:12px">
      <div class="kpi-card" style="border-left:3px solid var(--emerald)">
        <div class="kpi-label">BUY edges — season</div>
        <div class="kpi-value" style="color:var(--emerald)">${buyCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill good" style="width:${Math.min(100, Math.round((buyCount/Math.max(1, Math.min(40, compById.size/6)))*100))}%"></div></div>
        <div class="micro faint" style="font-size:11px; margin-top:6px">Model season ≥ +51 pts vs FantasyPros season (or rank ≥12 better than ECR)</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--crimson)">
        <div class="kpi-label">SELL flags — overpriced</div>
        <div class="kpi-value" style="color:var(--crimson)">${sellCount}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill bad" style="width:${Math.min(100, Math.round((sellCount/Math.max(1, Math.min(40, compById.size/6)))*100))}%"></div></div>
        <div class="micro faint" style="font-size:11px; margin-top:6px">FantasyPros season ≥ +51 pts vs Model · avoid paying sticker</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--sky)">
        <div class="kpi-label">Market coverage (season)</div>
        <div class="kpi-value" style="color:var(--sky)">${marketCovered} / ${compById.size}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill" style="background:var(--sky); width:${Math.round((marketCovered/Math.max(1, compById.size))*100)}%"></div></div>
        <div class="micro faint" style="font-size:11px; margin-top:6px">FantasyPros season projections (596, YDS/TDS) + ECR 519/ADP 695 CSVs · Sleeper weekly fallback 98 starters</div>
      </div>
      <div class="kpi-card" style="border-left:3px solid var(--amber)">
        <div class="kpi-label">Auction vs Market</div>
        <div class="kpi-value" style="font-size:14px; line-height:1.2">VOR $ from Model<br><span style="font:600 11px 'Fira Sans',sans-serif; color:var(--text-muted); letter-spacing:0.04em; text-transform:uppercase">$${budget} × ${TEAMS} teams · ${compareAuctionEnabled ? 'Market Δ shown' : 'toggle Market to see Δ'}</span></div>
        <div style="display:flex; gap:6px; margin-top:8px"><button class="chip ${compareAuctionEnabled ? 'active' : ''}" id="toggleAuctionCompare" style="font-size:11px">${compareAuctionEnabled ? '✓ Market + ECR on' : 'Show Market + ECR'}</button><button class="chip" id="copyModelVsMarketCsv" style="font-size:11px">Copy Model vs Market CSV</button></div>
      </div>
    </div>
    ` : `<div class="alert alert-info reveal in" style="margin-top:12px">Market comparison warming up — run refresh to populate Sleeper season (wk×17) + FP ECR/ADP. Auction currently shows Model only. Free sources: Sleeper <code class="inline">/projections</code> + FantasyPros limited (DST-only free) — Market_pts primary for season edges.</div>`}

    <!-- My Draft Tracker -->
    <div class="kpi-row reveal in" style="margin-top:12px">
      <div class="kpi-card">
        <div class="kpi-label">My Budget</div>
        <div class="kpi-value mono" style="color:${myRemaining > 50 ? 'var(--color-accent)' : myRemaining > 20 ? 'var(--amber)' : 'var(--crimson)'}">$${myRemaining}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill ${myRemaining > 100 ? 'good' : myRemaining > 30 ? 'ok' : 'bad'}" style="width:${(myRemaining / budget * 100).toFixed(0)}%"></div></div>
        <div class="micro faint">spent $${mySpent} / $${budget}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Max Bid</div>
        <div class="kpi-value mono">$${Math.max(0, maxBid)}</div>
        <div class="micro faint">${slotsLeft} roster slots left</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">My Roster</div>
        <div class="kpi-value mono">${myRosterCount}/${ROSTER_SIZE}</div>
        <div class="micro faint">${myRosterPlayers.map(p => (p.position || '').toUpperCase()).join(', ') || 'empty'}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Draft Progress</div>
        <div class="kpi-value mono">${draftedCount}/${TEAMS * ROSTER_SIZE}</div>
        <div class="kpi-bar"><div class="kpi-bar-fill ok" style="width:${(draftedCount / (TEAMS * ROSTER_SIZE) * 100).toFixed(0)}%"></div></div>
        <div class="micro faint">${availablePlayers.length} available</div>
      </div>
    </div>

    <!-- Positional Budget Guide -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Budget Allocation</h3><span class="kicker">recommended spend by position</span></div>
      <div class="card-body" style="display:flex; gap:12px; flex-wrap:wrap">
        ${posGroups.map(pos => {
          const b = posBudget[pos];
          const spent = myRosterPlayers.filter(p => (p.position || '').toUpperCase() === pos).reduce((s, p) => s + (state.drafted[p.player_id]?.price || 0), 0);
          return `<div style="flex:1; min-width:100px; text-align:center; padding:8px; background:var(--surface-raised); border-radius:8px; border:1px solid var(--border)">
            ${posBadge(pos)}
            <div class="mono" style="font-size:18px; margin:4px 0; color:${pos === 'K' || pos === 'DEF' ? 'var(--text-muted)' : 'var(--text)'}">$${b.recommended}</div>
            <div class="micro faint">${b.slots} slot${b.slots > 1 ? 's' : ''} @ ~$${b.perSlot}/ea</div>
            ${spent > 0 ? `<div class="micro" style="color:var(--amber)">spent $${spent}</div>` : ''}
          </div>`;
        }).join('')}
        <div style="flex:1; min-width:100px; text-align:center; padding:8px; background:var(--surface-raised); border-radius:8px; border:1px solid var(--border)">
          <span class="badge" style="background:var(--amber-dim); color:var(--amber)">FLEX</span>
          <div class="mono" style="font-size:18px; margin:4px 0">$${Math.max(0, flexBudget)}</div>
          <div class="micro faint">2 slots, split RB/WR/TE</div>
        </div>
      </div>
    </div>

    <!-- Nomination Strategy -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Nomination Strategy</h3><span class="kicker">nominate these to drain opponents</span></div>
      <div class="card-body" style="font:400 13px 'Fira Sans',sans-serif; color:var(--text-muted); line-height:1.6">
        <div class="alert alert-ok" style="margin-bottom:12px">Nominate players at positions you've filled (or don't need yet). Force opponents to spend early while you save budget for YOUR targets. <strong>Prefer high Market $ but lower Model $</strong> — let others overpay where Market is hot but Gridiron is cool (SELL).</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap">
          ${nominationTargets.map(p => `
            <div style="padding:6px 10px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; display:flex; align-items:center; gap:6px; ${p.edge==='BUY' ? 'border-left:3px solid var(--emerald)' : p.edge==='SELL' ? 'border-left:3px solid var(--crimson)' : ''}">
              ${playerAvatar(p, 24)}
              ${posBadge(p.position)}
              <strong style="font:600 12px 'Fira Sans',sans-serif">${escapeHtml(p.player_name)}</strong>
              ${teamLogo(p.team, 14)}
              <span class="badge" style="background:var(--amber-dim); color:var(--amber)">$${p.auction}</span>
              ${compareAuctionEnabled && hasComparison ? edgeBadgeAuction(p.edge) : ''}
              ${compareAuctionEnabled && p.marketRos != null ? `<span class="mono" style="font-size:10px; color:var(--text-faint)">mkt ${(Number(p.marketRos)).toFixed(0)}</span>` : ''}
            </div>
          `).join('')}
        </div>
        ${nominationTargets.length === 0 ? '<div class="micro faint">Fill some roster spots first to generate nomination targets.</div>' : ''}
      </div>
    </div>

    <!-- Draft Strategy -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Draft Strategy</h3><span class="kicker">Fantasy Bahamas $200 auction</span></div>
      <div class="card-body" style="font:400 13px 'Fira Sans',sans-serif; color:var(--text-muted); line-height:1.6">
        <ol style="margin:0; padding-left:18px">
          <li><strong>Stars & Scrubs:</strong> Spend 60-70% ($150-175) on 4-5 elite starters. Your 2-FLEX league means 7 RB/WR/TE start — premium on volume backs and target hogs.</li>
          <li><strong>Gridiron > Market = value:</strong> Filter <code class="inline">BUY</code> in Auction to see where Model season total beats Market season by ≥51 pts — bid up to Model $ there.</li>
          <li><strong>K/DEF = $1 always.</strong> MAE on kickers is 4+ pts — pure noise. Stream them.</li>
          <li><strong>$1 bench:</strong> Fill bench last at $1. Waiver wire value > draft bench value in 12-team.</li>
          <li><strong>Nominate positions you've filled</strong> — prefer SELL-flagged players so opponents burn cash where you’re cold.</li>
        </ol>
      </div>
    </div>

    <!-- My Roster -->
    ${myRosterCount > 0 ? `
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>My Drafted Players</h3>
        <button class="btn btn-ghost btn-sm" id="clearDraft" style="color:var(--crimson)">Reset Draft</button>
      </div>
      <div class="table-wrap" style="border:0; border-radius:0">
        <table>
          <thead><tr><th>Player</th><th>Pos</th><th>Paid</th><th>Value</th><th>+/-</th>${compareAuctionEnabled && hasComparison ? '<th>Season Δ</th><th>Edge</th>' : ''}</tr></thead>
          <tbody>
            ${myRosterPlayers.map(p => {
              const paid = state.drafted[p.player_id]?.price || 0;
              const diff = p.auction - paid;
              return `<tr style="--team-accent:${getTeamColor((p.team||'').toUpperCase())}; ${p.edge==='BUY' ? 'background:rgba(16,185,129,0.06)' : p.edge==='SELL' ? 'background:rgba(239,68,68,0.06)' : ''}">
                <td><div class="player-cell">${playerAvatar(p, 28)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '')}</div></div></div></td>
                <td>${posBadge(p.position)}</td>
                <td class="mono">$${paid}</td>
                <td class="mono">$${p.auction}</td>
                <td class="mono" style="color:${diff > 0 ? '#10B981' : diff < 0 ? 'var(--crimson)' : 'var(--text-muted)'}">${diff > 0 ? '+' : ''}${diff}</td>
                ${compareAuctionEnabled && hasComparison ? `<td>${deltaSeasonBadge(p.deltaRos)}</td><td>${edgeBadgeAuction(p.edge)}</td>` : ''}
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>` : ''}

    <!-- Position Filter -->
    <div class="responsive-view">
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <h3>Auction Board — ${activePos === 'ALL' ? 'All Positions' : activePos} ${auctionEdge !== 'ALL' ? `· ${auctionEdge}` : ''}</h3>
        <div class="row" style="gap:8px; flex-wrap:wrap">
          ${['ALL', ...posGroups].map(pos => `
            <button class="btn btn-sm ${activePos === pos ? '' : 'btn-ghost'} posFilter" data-pos="${pos}" style="${activePos === pos ? 'background:var(--color-accent); color:white' : ''}">${pos}</button>
          `).join('')}
          ${hasComparison ? `
            <span style="border-left:1px solid var(--border); margin:0 4px"></span>
            ${['ALL','BUY','SELL'].map(e=>`<button class="btn btn-sm ${auctionEdge===e ? '' : 'btn-ghost'} edgeFilter" data-edge="${e}" style="${auctionEdge===e ? (e==='BUY' ? 'background:var(--emerald); color:white' : e==='SELL' ? 'background:var(--crimson); color:white' : 'background:var(--color-accent); color:white') : ''}">${e==='ALL' ? 'All' : e==='BUY' ? '▲ BUY' : '▼ SELL'}</button>`).join('')}
          ` : ''}
          <span style="border-left:1px solid var(--border); margin:0 4px"></span>
          <button class="btn btn-ghost btn-sm" id="copyAuction">Copy CSV</button>
          <label class="faint" style="font:500 12px 'Fira Sans',sans-serif">
            <input type="checkbox" id="hideDrafted" ${params.get('hide') === '1' ? 'checked' : ''}> hide drafted
          </label>
        </div>
      </div>
      ${compareAuctionEnabled && hasComparison ? `
      <div style="display:flex; gap:12px; flex-wrap:wrap; align-items:center; padding:8px 12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; margin-bottom:10px; font:500 11px 'Fira Sans',sans-serif; line-height:1.4">
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--amber); border-radius:2px; display:inline-block"></span> <strong style="color:var(--amber)">Gridiron</strong> Model · Wk ×17 = season</span>
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--sky); border-radius:2px; display:inline-block"></span> <strong style="color:var(--sky)">Market</strong> · FantasyPros season projections (596, full YDS/TDS) + Sleeper weekly fallback</span>
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--emerald); border-radius:2px; display:inline-block"></span> BUY = Model ≥ +51 pts vs Market (3/wk)</span>
        <span style="display:flex; align-items:center; gap:6px"><span style="width:10px; height:10px; background:var(--crimson); border-radius:2px; display:inline-block"></span> SELL = Market ≥ +51 pts vs Model</span>
        <span class="mono" style="color:var(--text-faint); margin-left:auto">ECR 519 / ADP 695 via CSVs — full, not sparse</span>
      </div>
      ` : ''}
      <div class="card" style="padding:8px 12px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; display:flex; gap:8px; flex-wrap:wrap; align-items:center">
        <span class="kicker">Sort</span>
        <span class="mono" style="font-size:11px; color:var(--text-muted)">Click any header to sort — </span>
        <button class="chip ${auctionSortKey==='auction' ? 'active' : ''}" data-sort="auction" title="Sort by Auction $">Auction $ ${auctionSortKey==='auction' ? (auctionSortDir===-1 ? '▼ Highest → Lowest' : '▲ Lowest → Highest') : '↕'}</button>
        <button class="chip ${auctionSortKey==='ros' ? 'active' : ''}" data-sort="ros">Gridiron Season ${auctionSortKey==='ros' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</button>
        ${compareAuctionEnabled && hasComparison ? `<button class="chip ${auctionSortKey==='marketRos' ? 'active' : ''}" data-sort="marketRos">Market Season ${auctionSortKey==='marketRos' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</button><button class="chip ${auctionSortKey==='deltaRos' ? 'active' : ''}" data-sort="deltaRos">Δ ${auctionSortKey==='deltaRos' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</button>` : ''}
        <button class="chip" id="toggleSortDir" title="Flip highest↔lowest">↕ ${auctionSortDir===-1 ? 'Highest → Lowest' : 'Lowest → Highest'}</button>
        <span class="mono" style="font-size:11px; color:var(--text-faint); margin-left:auto">Tip: click headers to sort any column both ways</span>
      </div>
      <div class="table-wrap" style="border:0; border-radius:0; overflow-x:auto; margin-top:10px">
        <table style="min-width:${compareAuctionEnabled && hasComparison ? '1180px' : '720px'}">
          <thead>
            <tr>
              <th style="width:32px">#</th>
              <th data-sort="player_name" tabindex="0" role="button" aria-label="Sort by Player" style="cursor:pointer">Player ${auctionSortKey==='player_name' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>
              <th data-sort="position" tabindex="0" role="button" aria-label="Sort by Pos" style="cursor:pointer">Pos ${auctionSortKey==='position' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>
              ${compareAuctionEnabled && hasComparison ? `
              <th data-sort="weekly" tabindex="0" role="button" aria-label="Sort by Gridiron Wk" style="color:var(--amber); border-bottom:2px solid var(--amber); cursor:pointer" title="Gridiron weekly projection (stat_projector)">Gridiron Wk ${auctionSortKey==='weekly' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}<br><span style="font:600 10px 'Fira Sans',sans-serif; color:var(--amber); opacity:0.7">Season 17g</span></th>
              <th data-sort="ros" tabindex="0" role="button" aria-label="Sort by Gridiron Season" style="color:var(--amber); border-bottom:2px solid var(--amber); cursor:pointer" title="Gridiron season = weekly ×17">Gridiron<br><span style="font:600 10px 'Fira Sans',sans-serif; color:var(--amber); opacity:0.7">Season 17g ${auctionSortKey==='ros' ? (auctionSortDir===-1 ? '▼' : '▲') : ''}</span></th>
              <th data-sort="marketRos" tabindex="0" role="button" aria-label="Sort by Market Season" style="color:var(--sky); border-bottom:2px solid var(--sky); cursor:pointer" title="Market season — FantasyPros season projections (596, full YDS/TDS) — fallback Sleeper weekly ×17">Market<br><span style="font:600 10px 'Fira Sans',sans-serif; color:var(--sky); opacity:0.7">Season 17g ${auctionSortKey==='marketRos' ? (auctionSortDir===-1 ? '▼' : '▲') : ''}</span></th>
              <th data-sort="deltaRos" tabindex="0" role="button" aria-label="Sort by Season Δ" style="border-bottom:2px solid var(--border); cursor:pointer" title="Season Δ = Gridiron Season − Market Season">Season Δ<br><span style="font:600 10px 'Fira Sans',sans-serif; color:var(--text-faint)">Grid−Mkt ${auctionSortKey==='deltaRos' ? (auctionSortDir===-1 ? '▼' : '▲') : ''}</span></th>
              <th data-sort="fp_ecr" tabindex="0" role="button" aria-label="Sort by ECR" style="cursor:pointer" title="FantasyPros ECR 519 + Tiers via CSV">ECR ${auctionSortKey==='fp_ecr' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>
              <th data-sort="fp_adp" tabindex="0" role="button" aria-label="Sort by ADP" style="cursor:pointer" title="FantasyPros ADP 695 via CSV">ADP ${auctionSortKey==='fp_adp' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>
              ` : `<th data-sort="weekly" tabindex="0" role="button" style="cursor:pointer">Model Wk ${auctionSortKey==='weekly' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th><th data-sort="ros" tabindex="0" role="button" style="cursor:pointer">Season (17g) ${auctionSortKey==='ros' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>`}
              <th data-sort="vor" tabindex="0" role="button" aria-label="Sort by VOR" style="cursor:pointer">VOR ${auctionSortKey==='vor' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>
              <th data-sort="auction" tabindex="0" role="button" aria-label="Sort by Auction $" style="cursor:pointer">Auction $ ${auctionSortKey==='auction' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th>
              ${compareAuctionEnabled && hasComparison ? '<th data-sort="edge_score" tabindex="0" role="button" aria-label="Sort by Edge" style="cursor:pointer">Edge ↕</th>' : ''}
              <th>Interval</th><th data-sort="tier" tabindex="0" role="button" style="cursor:pointer">T ${auctionSortKey==='tier' ? (auctionSortDir===-1 ? '▼' : '▲') : '↕'}</th><th>Draft</th>
            </tr>
          </thead>
          <tbody>
            ${(() => {
              let list = filteredPlayers;
              if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') {
                list = list.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
              }
              return list.slice(0, 120).map((p, i) => `
              <tr style="${p.isDrafted ? 'opacity:0.35; text-decoration:line-through' : ''};--team-accent:${getTeamColor((p.team||'').toUpperCase())}; ${p.edge==='BUY' ? 'background:rgba(16,185,129,0.06)' : p.edge==='SELL' ? 'background:rgba(239,68,68,0.06)' : ''}" data-pid="${p.player_id}" data-team="${p.team || ''}">
                <td class="mono-muted" style="font-size:11px">${i + 1}</td>
                <td>
                  <div class="player-cell">${playerAvatar(p, 28)}<div class="player-cell-info"><div class="player-cell-name">${escapeHtml(p.player_name)}</div><div class="player-cell-sub">${teamLogo(p.team, 14)} ${escapeHtml(p.team || '')}${p.opponent_team ? ' vs ' + escapeHtml(p.opponent_team) : ''}</div></div></div>
                </td>
                <td>${posBadge(p.position)}</td>
                <td class="mono" style="color:var(--amber)">${p.weekly.toFixed(1)}</td>
                <td class="mono" style="font-weight:700">${p.ros.toFixed(0)}</td>
                ${compareAuctionEnabled && hasComparison ? `
                <td class="mono" style="color:var(--sky)">${p.marketRos != null ? p.marketRos.toFixed(0) : '—'}</td>
                <td>${deltaSeasonBadge(p.deltaRos)}</td>
                <td class="mono" style="font-size:11px; color:var(--text-muted)">${p.fp_ecr != null ? `#${p.fp_ecr}${p.fp_tier ? ` <span style="background:var(--violet-dim); color:var(--violet); border:1px solid rgba(168,85,247,0.18); border-radius:999px; padding:1px 5px; font:700 10px 'JetBrains Mono',monospace">T${p.fp_tier}</span>` : ''}` : '—'}</td>
                <td class="mono" style="font-size:11px; color:var(--text-muted)">${p.fp_adp != null ? '#'+p.fp_adp : '—'}</td>
                ` : ''}
                <td class="mono" style="color:${p.vor > 30 ? '#10B981' : p.vor > 15 ? 'var(--amber)' : 'var(--text-muted)'}">+${p.vor.toFixed(0)}</td>
                <td><span class="badge" style="background:${p.auction >= 15 ? '#16A34A' : p.auction >= 5 ? 'var(--amber-dim)' : 'var(--surface-raised)'}; color:${p.auction >= 15 ? 'white' : p.auction >= 5 ? 'var(--amber)' : 'var(--text-muted)'}; border:1px solid ${p.auction >= 15 ? '#16A34A' : 'var(--border)'}">$${p.auction}</span></td>
                ${compareAuctionEnabled && hasComparison ? `<td>${edgeBadgeAuction(p.edge)}</td>` : ''}
                <td class="mono-muted" style="font-size:11px">${(p.ros - p.widthRos).toFixed(0)}–${(p.ros + p.widthRos).toFixed(0)}</td>
                <td class="faint" style="font:600 11px 'Fira Sans',sans-serif">T${p.tier}</td>
                <td>
                  ${p.isDrafted
                    ? `<span class="micro faint">${p.draftedBy === 'me' ? 'MINE' : 'gone'}${p.draftedPrice ? ' $' + p.draftedPrice : ''}</span>`
                    : `<button class="btn btn-ghost btn-sm draftBtn" data-pid="${p.player_id}" data-name="${escapeHtml(p.player_name)}" data-val="${p.auction}" style="font-size:11px; padding:2px 8px">Draft</button>`
                  }
                </td>
              </tr>
            `).join('');
            })()}
          </tbody>
        </table>
      </div>
    </div>
    <div class="player-cards-grid">
      ${(() => {
        let list = filteredPlayers.filter(p => !p.isDrafted);
        if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') list = list.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
        return list.slice(0, 50).map(p => {
          const base = playerCard(p, { showDraftBtn: true, showTeamLogo: true });
          if (!compareAuctionEnabled || !hasComparison) return base;
          // inject auction + market footer
          const seasonDelta = p.deltaRos != null ? `<span class="mono" style="font-size:10px; color:${Number(p.deltaRos) > 8 ? 'var(--emerald)' : Number(p.deltaRos) < -8 ? 'var(--crimson)' : 'var(--text-faint)'}">${Number(p.deltaRos)>0?'+':''}${Number(p.deltaRos).toFixed(0)} season Δ</span>` : `<span class="mono" style="font-size:10px; color:var(--text-faint)">season Δ —</span>`;
          return base.replace('</div>\\n', `  <div style="margin-top:8px; display:flex; gap:6px; align-items:center; flex-wrap:wrap; padding-top:8px; border-top:1px solid var(--border)"><span class="mono" style="font-size:10px; color:var(--text-muted)">Mkt ${p.marketRos != null ? p.marketRos.toFixed(0) : '—'}</span>${seasonDelta}<span class="spacer"></span>${edgeBadgeAuction(p.edge)}</div></div>\\n`);
        }).join('');
      })()}
    </div>
    </div>
  `;

  // --- Event handlers ---

  // Toggle auction compare
  root.querySelector('#toggleAuctionCompare')?.addEventListener('click', () => {
    const next = !compareAuctionEnabled;
    try { localStorage.setItem('ffba-auction-compare', next ? '1' : '0'); } catch {}
    renderAuction(root);
  });
  root.querySelector('#copyModelVsMarketCsv')?.addEventListener('click', () => {
    let list = filteredPlayers;
    if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') list = list.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
    const rows = [['rank','player','pos','team','model_wk','model_season','market_season','season_delta','fp_ecr','fp_adp','vor','auction','edge']];
    list.slice(0,150).forEach((p,i)=>{
      rows.push([i+1, `"${p.player_name}"`, p.position, p.team, p.weekly.toFixed(1), p.ros.toFixed(1), p.marketRos != null ? p.marketRos.toFixed(1) : '', p.deltaRos != null ? p.deltaRos.toFixed(1) : '', p.fp_ecr ?? '', p.fp_adp ?? '', p.vor.toFixed(1), p.auction, p.edge]);
    });
    const csv = rows.map(r=>r.join(',')).join('\n');
    navigator.clipboard.writeText(csv);
    const b = root.querySelector('#copyModelVsMarketCsv');
    if (b) { const t=b.textContent; b.textContent='Copied ✓'; setTimeout(()=>b.textContent=t,1200); }
  });

  // Position filter buttons
  root.querySelectorAll('.posFilter').forEach(btn => {
    btn.addEventListener('click', () => {
      const pos = btn.dataset.pos;
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      if (pos === 'ALL') p.delete('pos');
      else p.set('pos', pos);
      location.hash = 'auction?' + p.toString();
    });
  });
  // Edge filter
  root.querySelectorAll('.edgeFilter').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const e = btn.dataset.edge;
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      if (e === 'ALL') p.delete('edge');
      else p.set('edge', e);
      location.hash = 'auction?' + p.toString();
    });
  });

  // Hide drafted toggle
  root.querySelector('#hideDrafted')?.addEventListener('change', e => {
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    if (e.target.checked) p.set('hide', '1');
    else p.delete('hide');
    location.hash = 'auction?' + p.toString();
  });

  // Sort: click header or sort chips to order highest↔lowest
  root.querySelectorAll('[data-sort]').forEach(th=>{
    th.addEventListener('click', ()=>{
      const key = th.getAttribute('data-sort');
      const p = new URLSearchParams(location.hash.split('?')[1] || '');
      const curKey = p.get('sort') || 'auction';
      const curDir = p.get('dir') === '1' ? 1 : -1;
      let nextDir = -1;
      if (curKey === key) nextDir = curDir * -1;
      else nextDir = (key === 'player_name' ? 1 : -1);
      p.set('sort', key);
      p.set('dir', String(nextDir));
      location.hash = 'auction?' + p.toString();
    });
    th.addEventListener('keydown', e=>{ if(e.key==='Enter' || e.key===' ') { e.preventDefault(); th.click(); }});
  });
  root.querySelector('#toggleSortDir')?.addEventListener('click', ()=>{
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    const curDir = p.get('dir') === '1' ? 1 : -1;
    p.set('sort', p.get('sort') || 'auction');
    p.set('dir', String(curDir * -1));
    location.hash = 'auction?' + p.toString();
  });

  // Draft buttons
  root.querySelectorAll('.draftBtn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pid = btn.dataset.pid;
      const name = btn.dataset.name;
      const suggestedVal = btn.dataset.val;
      showDraftModal(root, pid, name, suggestedVal, state, allRanked);
    });
  });

  // Copy CSV (original)
  root.querySelector('#copyAuction')?.addEventListener('click', () => {
    let list = filteredPlayers;
    if (hasComparison && compareAuctionEnabled && auctionEdge !== 'ALL') list = list.filter(p => (p.edge || 'NEUTRAL') === auctionEdge);
    const csvPlayers = list.filter(p => !p.isDrafted);
    const csv = ['rank,player,pos,team,weekly,ros,vor,auction,market_season,season_delta,fp_ecr,fp_adp,edge,interval,tier']
      .concat(csvPlayers.slice(0, 120).map((p, i) =>
        `${i + 1},"${p.player_name}",${p.position},${p.team},${p.weekly.toFixed(1)},${p.ros.toFixed(1)},${p.vor.toFixed(1)},${p.auction},${p.marketRos != null ? p.marketRos.toFixed(0) : ''},${p.deltaRos != null ? p.deltaRos.toFixed(0) : ''},${p.fp_ecr ?? ''},${p.fp_adp ?? ''},${p.edge},${(p.ros - p.widthRos).toFixed(0)}-${(p.ros + p.widthRos).toFixed(0)},T${p.tier}`
      )).join('\n');
    navigator.clipboard.writeText(csv);
    const b = root.querySelector('#copyAuction');
    if (b) { b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy CSV', 1200); }
  });

  // Reset draft
  root.querySelector('#clearDraft')?.addEventListener('click', () => {
    if (confirm('Reset entire draft tracker? This clears all drafted players and your roster.')) {
      localStorage.removeItem(STORE_KEY);
      location.hash = 'auction';
    }
  });
}

function showDraftModal(root, pid, name, suggestedVal, state, allRanked) {
  const existing = root.querySelector('#draftModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'draftModal';
  modal.style.cssText = 'position:fixed; inset:0; z-index:1000; display:flex; align-items:center; justify-content:center; background:rgba(0,0,0,0.6)';
  modal.innerHTML = `
    <div style="background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:24px; min-width:300px; max-width:400px">
      <h3 style="margin:0 0 16px 0">${name}</h3>
      <div style="margin-bottom:12px">
        <label style="font:500 13px 'Fira Sans',sans-serif; color:var(--text-muted)">Price paid</label>
        <input type="number" id="draftPrice" value="${suggestedVal}" min="1" max="200" style="width:100%; background:var(--surface-raised); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:8px; font-size:16px; margin-top:4px">
      </div>
      <div style="margin-bottom:16px">
        <label style="font:500 13px 'Fira Sans',sans-serif; color:var(--text-muted)">Who got them?</label>
        <div style="display:flex; gap:8px; margin-top:8px">
          <button class="btn btn-sm draftWho" data-who="me" style="flex:1; background:var(--color-accent); color:white">ME</button>
          <button class="btn btn-sm btn-ghost draftWho" data-who="other" style="flex:1">Other team</button>
        </div>
      </div>
      <div style="display:flex; gap:8px; justify-content:flex-end">
        <button class="btn btn-ghost btn-sm" id="draftCancel">Cancel</button>
      </div>
    </div>
  `;
  root.appendChild(modal);

  modal.querySelector('#draftCancel').addEventListener('click', () => modal.remove());
  modal.addEventListener('click', e => { if (e.target === modal) modal.remove(); });

  modal.querySelectorAll('.draftWho').forEach(btn => {
    btn.addEventListener('click', () => {
      const who = btn.dataset.who;
      const price = Number(modal.querySelector('#draftPrice').value) || 1;
      state.drafted[pid] = { by: who, price };
      if (who === 'me') {
        if (!state.myRoster.includes(pid)) state.myRoster.push(pid);
      }
      saveDraftState(state);
      modal.remove();
      renderAuction(root);
    });
  });
}

function escapeHtml(s) {
  return String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}
