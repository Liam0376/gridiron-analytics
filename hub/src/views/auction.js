import { fetchProjections } from '../api.js';
import { posBadge } from '../components/badges.js';

const BUDGET = 250;
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

export async function renderAuction(root) {
  const params = new URLSearchParams(location.hash.split('?')[1] || '');
  const budget = Number(params.get('budget') || BUDGET);

  const data = await fetchProjections({});
  let players = data.players || [];
  if (!players.length) {
    root.innerHTML = `
      <div class="hero reveal in"><h1>Auction Draft</h1><p>No projection data. Run <code class="inline">bash hub/start.sh --auto</code> first.</p></div>`;
    return;
  }

  const state = loadDraftState();

  // Full-season ROS (17 games for pre-draft)
  const remaining = SEASON_GAMES;
  const rosPlayers = players.map(p => ({
    ...p,
    ros: Number(p.projected_points ?? p.point_estimate ?? 0) * remaining,
    weekly: Number(p.projected_points ?? 0),
    widthRos: Number(p.width ?? 5) * Math.sqrt(remaining),
    isDrafted: !!state.drafted[p.player_id],
    draftedBy: state.drafted[p.player_id]?.by || null,
    draftedPrice: state.drafted[p.player_id]?.price || null,
  }));

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
  // Nominate high-value players at positions YOU don't need early
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
  const draftedPlayers = allRanked.filter(p => p.isDrafted);
  const availablePlayers = allRanked.filter(p => !p.isDrafted);
  const myRosterPlayers = state.myRoster.map(id => allRanked.find(p => p.player_id === id)).filter(Boolean);
  const mySpent = myRosterPlayers.reduce((s, p) => s + (state.drafted[p.player_id]?.price || 0), 0);
  const myRemaining = budget - mySpent;
  const myRosterCount = state.myRoster.length;
  const slotsLeft = ROSTER_SIZE - myRosterCount;
  const maxBid = slotsLeft > 1 ? myRemaining - (slotsLeft - 1) : myRemaining;

  // Position filter
  const activePos = params.get('pos') || 'ALL';

  const filteredPlayers = activePos === 'ALL'
    ? availablePlayers
    : availablePlayers.filter(p => (p.position || '').toUpperCase() === activePos);

  root.innerHTML = `
    <div class="hero reveal in">
      <h1>Auction Draft <span class="badge" style="background:var(--color-accent,#16A34A); color:white; margin-left:8px; vertical-align:middle">$${budget}</span></h1>
      <p>Full-season VOR (${SEASON_GAMES}g) → auction $. 2-FLEX league inflates RB/WR/TE. Draft is <strong>Sunday night</strong>.</p>
    </div>

    <!-- My Draft Tracker -->
    <div class="kpi-row reveal in" style="margin-top:12px">
      <div class="kpi-card">
        <div class="kpi-label">My Budget</div>
        <div class="kpi-value mono" style="color:${myRemaining > 50 ? 'var(--color-accent)' : myRemaining > 20 ? 'var(--amber)' : 'var(--danger)'}">$${myRemaining}</div>
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
        <div class="alert alert-ok" style="margin-bottom:12px">Nominate players at positions you've filled (or don't need yet). Force opponents to spend early while you save budget for YOUR targets.</div>
        <div style="display:flex; gap:8px; flex-wrap:wrap">
          ${nominationTargets.map(p => `
            <div style="padding:6px 10px; background:var(--surface-raised); border:1px solid var(--border); border-radius:8px; display:flex; align-items:center; gap:6px">
              ${posBadge(p.position)}
              <strong style="font:600 12px 'Fira Sans',sans-serif">${escapeHtml(p.player_name)}</strong>
              <span class="badge" style="background:var(--amber-dim); color:var(--amber)">$${p.auction}</span>
            </div>
          `).join('')}
        </div>
        ${nominationTargets.length === 0 ? '<div class="micro faint">Fill some roster spots first to generate nomination targets.</div>' : ''}
      </div>
    </div>

    <!-- Draft Strategy -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>Draft Strategy</h3><span class="kicker">Fantasy Bahamas $250 auction</span></div>
      <div class="card-body" style="font:400 13px 'Fira Sans',sans-serif; color:var(--text-muted); line-height:1.6">
        <ol style="margin:0; padding-left:18px">
          <li><strong>Stars & Scrubs:</strong> Spend 60-70% ($150-175) on 4-5 elite starters. Your 2-FLEX league means 7 RB/WR/TE start — premium on volume backs and target hogs.</li>
          <li><strong>Floor early, ceiling late:</strong> Target <strong>high VOR + narrow interval</strong> first (reliable). Late-round take shots on <strong>wide interval</strong> guys (upside lottery).</li>
          <li><strong>K/DEF = $1 always.</strong> MAE on kickers is 4+ pts — pure noise. Stream them.</li>
          <li><strong>$1 bench:</strong> Fill bench last at $1. Waiver wire value > draft bench value in 12-team.</li>
          <li><strong>Nominate positions you've filled</strong> to force opponents into bidding wars. Nominate RBs if you already got yours.</li>
        </ol>
      </div>
    </div>

    <!-- My Roster -->
    ${myRosterCount > 0 ? `
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header"><h3>My Drafted Players</h3>
        <button class="btn btn-ghost btn-sm" id="clearDraft" style="color:var(--danger)">Reset Draft</button>
      </div>
      <div class="table-wrap" style="border:0; border-radius:0">
        <table>
          <thead><tr><th>Player</th><th>Pos</th><th>Paid</th><th>Value</th><th>+/-</th></tr></thead>
          <tbody>
            ${myRosterPlayers.map(p => {
              const paid = state.drafted[p.player_id]?.price || 0;
              const diff = p.auction - paid;
              return `<tr>
                <td><strong style="font:600 12px 'Fira Sans',sans-serif">${escapeHtml(p.player_name)}</strong></td>
                <td>${posBadge(p.position)}</td>
                <td class="mono">$${paid}</td>
                <td class="mono">$${p.auction}</td>
                <td class="mono" style="color:${diff > 0 ? 'var(--color-accent)' : diff < 0 ? 'var(--danger)' : 'var(--text-muted)'}">${diff > 0 ? '+' : ''}${diff}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>` : ''}

    <!-- Position Filter -->
    <div class="card reveal in" style="margin-top:16px">
      <div class="card-header">
        <h3>Auction Board — ${activePos === 'ALL' ? 'All Positions' : activePos}</h3>
        <div class="row" style="gap:8px; flex-wrap:wrap">
          ${['ALL', ...posGroups].map(pos => `
            <button class="btn btn-sm ${activePos === pos ? '' : 'btn-ghost'} posFilter" data-pos="${pos}" style="${activePos === pos ? 'background:var(--color-accent); color:white' : ''}">${pos}</button>
          `).join('')}
          <span style="border-left:1px solid var(--border); margin:0 4px"></span>
          <button class="btn btn-ghost btn-sm" id="copyAuction">Copy CSV</button>
          <label class="faint" style="font:500 12px 'Fira Sans',sans-serif">
            <input type="checkbox" id="hideDrafted" ${params.get('hide') === '1' ? 'checked' : ''}> hide drafted
          </label>
        </div>
      </div>
      <div class="table-wrap" style="border:0; border-radius:0">
        <table>
          <thead><tr><th>#</th><th>Player</th><th>Pos</th><th>Wk Avg</th><th>ROS (${SEASON_GAMES}g)</th><th>VOR</th><th>Auction $</th><th>Interval</th><th>T</th><th>Draft</th></tr></thead>
          <tbody>
            ${filteredPlayers.slice(0, 120).map((p, i) => `
              <tr style="${p.isDrafted ? 'opacity:0.35; text-decoration:line-through' : ''}" data-pid="${p.player_id}">
                <td class="mono-muted" style="font-size:11px">${i + 1}</td>
                <td>
                  <strong style="font:600 12px 'Fira Sans',sans-serif">${escapeHtml(p.player_name)}</strong>
                  <div class="micro faint">${escapeHtml(p.team)}${p.opponent_team ? ' vs ' + escapeHtml(p.opponent_team) : ''}</div>
                </td>
                <td>${posBadge(p.position)}</td>
                <td class="mono">${p.weekly.toFixed(1)}</td>
                <td class="mono">${p.ros.toFixed(1)}</td>
                <td class="mono" style="color:${p.vor > 30 ? 'var(--color-accent)' : p.vor > 15 ? 'var(--amber)' : 'var(--text-muted)'}">+${p.vor.toFixed(1)}</td>
                <td><span class="badge" style="background:${p.auction >= 15 ? 'var(--color-accent)' : p.auction >= 5 ? 'var(--amber-dim)' : 'var(--surface-raised)'}; color:${p.auction >= 15 ? 'white' : p.auction >= 5 ? 'var(--amber)' : 'var(--text-muted)'}; border:1px solid ${p.auction >= 15 ? 'var(--color-accent)' : 'var(--border)'}">$${p.auction}</span></td>
                <td class="mono-muted" style="font-size:11px">${(p.ros - p.widthRos).toFixed(0)}–${(p.ros + p.widthRos).toFixed(0)}</td>
                <td class="faint" style="font:600 11px 'Fira Sans',sans-serif">T${p.tier}</td>
                <td>
                  ${p.isDrafted
                    ? `<span class="micro faint">${p.draftedBy === 'me' ? 'MINE' : 'gone'}${p.draftedPrice ? ' $' + p.draftedPrice : ''}</span>`
                    : `<button class="btn btn-ghost btn-sm draftBtn" data-pid="${p.player_id}" data-name="${escapeHtml(p.player_name)}" data-val="${p.auction}" style="font-size:11px; padding:2px 8px">Draft</button>`
                  }
                </td>
              </tr>
            `).join('')}
          </tbody>
        </table>
      </div>
    </div>
  `;

  // --- Event handlers ---

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

  // Hide drafted toggle
  root.querySelector('#hideDrafted')?.addEventListener('change', e => {
    const p = new URLSearchParams(location.hash.split('?')[1] || '');
    if (e.target.checked) p.set('hide', '1');
    else p.delete('hide');
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

  // Copy CSV
  root.querySelector('#copyAuction')?.addEventListener('click', () => {
    const csvPlayers = filteredPlayers.filter(p => !p.isDrafted);
    const csv = ['rank,player,pos,team,weekly,ros,vor,auction,interval,tier']
      .concat(csvPlayers.slice(0, 120).map((p, i) =>
        `${i + 1},"${p.player_name}",${p.position},${p.team},${p.weekly.toFixed(1)},${p.ros.toFixed(1)},${p.vor.toFixed(1)},${p.auction},${(p.ros - p.widthRos).toFixed(0)}-${(p.ros + p.widthRos).toFixed(0)},T${p.tier}`
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
        <input type="number" id="draftPrice" value="${suggestedVal}" min="1" max="250" style="width:100%; background:var(--surface-raised); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:8px; font-size:16px; margin-top:4px">
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
