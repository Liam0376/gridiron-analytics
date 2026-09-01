import './styles/app.css';
import { allRoutes, getRoute } from './router.js';
import { fetchHealth, fetchMeta, computeStaleness, fetchProjections, fetchComparison, fetchRoster } from './api.js';
import { shimmer } from './components/shimmer.js';
import { renderMobileNav, bindMobileNav } from './components/mobileNav.js';
import { renderDashboard } from './views/dashboard.js';
import { renderMatchups } from './views/matchups.js';
import { renderProjections } from './views/projections.js';
import { renderTierlists } from './views/tierlists.js';
import { renderTeam } from './views/team.js';
import { renderRoster } from './views/roster.js';
import { renderWaiver } from './views/waiver.js';
import { renderTrade } from './views/trade.js';
import { renderAuction } from './views/auction.js';
import { filterPlayers } from './search.js';
import { playerAvatar } from './components/playerAvatar.js';
import { userAvatar } from './components/userAvatar.js';
import { posBadge } from './components/badges.js';
import { teamLogo } from './components/teamLogo.js';
import { openPlayerModal } from './components/playerModal.js';

const views = {
  dashboard: renderDashboard,
  team: renderTeam,
  matchups: renderMatchups,
  projections: renderProjections,
  tierlists: renderTierlists,
  auction: renderAuction,
  roster: renderRoster,
  waiver: renderWaiver,
  trade: renderTrade,
};

function renderNav() {
  const tabs = document.getElementById('navTabs');
  const cur = getRoute().id;
  const icons = {
    dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    team: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    matchups: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3 6h.01"/><path d="M3 12h.01"/><path d="M3 18h.01"/></svg>',
    projections: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 3v18h18"/><path d="M18 17V9"/><path d="M13 17V5"/><path d="M8 17v-3"/></svg>',
    tierlists: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
    roster: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
    waiver: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v8"/><path d="M8 12h8"/></svg>',
    trade: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 16V4"/><path d="M7 4l-3 3"/><path d="M7 4l3 3"/><path d="M17 8v12"/><path d="M17 20l3-3"/><path d="M17 20l-3-3"/></svg>',
  };
  tabs.innerHTML = allRoutes().map(r=>`
    <button class="sidebar-tab ${r.id===cur?'active':''}" data-route="${r.id}" role="tab" aria-selected="${r.id===cur}">${icons[r.id]||icons.dashboard}<span class="label">${r.label}</span></button>
  `).join('');
  tabs.querySelectorAll('[data-route]').forEach(btn=>{
    btn.addEventListener('click', ()=>{ location.hash = btn.getAttribute('data-route'); });
  });
  renderMobileNavBar(cur);
}

function renderMobileNavBar(currentRouteId) {
  const container = document.getElementById('mobileNav');
  if (!container) return;
  container.innerHTML = renderMobileNav(currentRouteId);
  bindMobileNav();
}

async function refreshStaleness() {
  const el = document.getElementById('staleText');
  const dot = document.getElementById('staleDot');
  if (!el || !dot) return;
  try {
    const health = await fetchHealth();
    const meta = await fetchMeta();
    const ts = meta.lastUpdated || meta.last_updated || null;
    const s = computeStaleness(ts);
    if (health.status !== 'ok') {
      dot.className = 'dot cold';
      el.textContent = 'API down — showing DB snapshot';
      return;
    }
    if (s.level === 'fresh') { dot.className = 'dot fresh'; el.textContent = health.source === 'proxy' ? 'Local DB Active' : s.label; }
    else if (s.level === 'stale') { dot.className = 'dot stale'; el.textContent = s.label; }
    else { dot.className = 'dot cold'; el.textContent = health.source === 'proxy' ? 'Local DB Active' : s.label; }
    el.title = ts ? `lastUpdated: ${ts}` : 'no timestamp';
  } catch {
    dot.className = 'dot cold';
    el.textContent = 'checking…';
  }
}

async function render() {
  renderNav();
  refreshStaleness();
  const route = getRoute();
  const app = document.getElementById('app');
  app.innerHTML = `<div class="page"><div class="card" style="padding:20px">${shimmer(route.id === 'projections' ? 'table' : 'kpi')}</div></div>`;
  const fn = views[route.id] || views.dashboard;
  try {
    await fn(app);
    // reveal animation
    app.querySelectorAll('.reveal').forEach((el,i)=>{
      el.style.transitionDelay = `${Math.min(i*40, 240)}ms`;
      requestAnimationFrame(()=> el.classList.add('in'));
    });
    // observe for scroll reveals if more content added
    const io = new IntersectionObserver((entries)=>{
      entries.forEach(e=>{ if(e.isIntersecting) e.target.classList.add('in'); });
    }, { threshold: 0.08 });
    app.querySelectorAll('.reveal').forEach(el=> io.observe(el));
  } catch (e) {
    app.innerHTML = `<div class="alert alert-bad">Failed to render ${route.id}: ${String(e)}<br><span class="faint" style="font:500 11px ui-monospace, SFMono-Regular, monospace">${e.stack || ''}</span></div>`;
    console.error(e);
  }
}

// Global Live Search Dropdown Logic
const globalSearch = document.getElementById('globalSearch');
const searchDropdown = document.getElementById('searchDropdown');
let allSearchPlayers = [];
let searchPromise = null;
let fantasyLeagueTeams = [];

async function loadSearchPlayersCache() {
  if (allSearchPlayers.length === 0) {
    if (!searchPromise) {
      searchPromise = (async () => {
        try {
          const [projData, compData, rosterData] = await Promise.all([
            fetchProjections({}),
            fetchComparison({ limit: 800 }).catch(() => ({ players: [] })),
            fetchRoster().catch(() => ({ allTeams: [] })),
          ]);

          fantasyLeagueTeams = rosterData?.allTeams || rosterData?.leagueRosters || [];
          const rosterPlayerOwnerMap = new Map();

          // Map player_id to owner/fantasy team
          (rosterData?.allTeams || rosterData?.leagueRosters || []).forEach(t => {
            const ownerName = t.owner_name || t.display_name || '';
            const teamName = t.team_name || '';
            (t.starters || []).concat(t.bench || []).concat(t.players || []).forEach(p => {
              const pid = typeof p === 'object' ? String(p.player_id || p.id) : String(p);
              if (pid) rosterPlayerOwnerMap.set(pid, { owner_name: ownerName, team_name: teamName });
            });
          });

          const map = new Map();

          // Populate from comparison (contains full 500+ player universe)
          (compData?.players || []).forEach(p => {
            const pid = String(p.player_id || p.id);
            if (pid) {
              const ownerInfo = rosterPlayerOwnerMap.get(pid) || {};
              map.set(pid, {
                player_id: pid,
                player_name: p.player_name || p.name || p.full_name || pid,
                position: (p.position || p.position_group || 'UNK').toUpperCase(),
                team: (p.team || '').toUpperCase(),
                opponent_team: (p.opponent_team || '').toUpperCase(),
                projected_points: Number(p.model_points ?? p.projected_points ?? p.market_points ?? 0),
                market_points: p.market_points,
                fp_ecr: p.fp_ecr,
                owner_name: ownerInfo.owner_name || '',
                team_name: ownerInfo.team_name || '',
              });
            }
          });

          // Merge active projections
          (projData?.players || []).forEach(p => {
            const pid = String(p.player_id || p.id);
            if (pid) {
              const existing = map.get(pid) || {};
              map.set(pid, {
                ...existing,
                ...p,
                player_name: p.player_name || existing.player_name || pid,
                position: (p.position || existing.position || 'UNK').toUpperCase(),
                projected_points: Number(p.projected_points ?? existing.projected_points ?? 0),
              });
            }
          });

          allSearchPlayers = Array.from(map.values());
        } catch (e) {
          console.error('Error loading search cache:', e);
        }
      })();
    }
    await searchPromise;
  }
}

if (globalSearch && searchDropdown) {
  let searchTimer = null;

  globalSearch.addEventListener('focus', () => {
    loadSearchPlayersCache();
    if (globalSearch.value.trim().length > 0) {
      renderSearchDropdown(globalSearch.value.trim());
    }
  });

  globalSearch.addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(async () => {
      const q = e.target.value.trim();
      if (!q) {
        searchDropdown.style.display = 'none';
        return;
      }
      await loadSearchPlayersCache();
      renderSearchDropdown(q);
    }, 350);
  });

  globalSearch.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      const q = globalSearch.value.trim();
      if (q) {
        searchDropdown.style.display = 'none';
        location.hash = `projections?q=${encodeURIComponent(q)}`;
      }
    } else if (e.key === 'Escape') {
      searchDropdown.style.display = 'none';
    }
  });

  document.addEventListener('click', (e) => {
    if (!globalSearch.contains(e.target) && !searchDropdown.contains(e.target)) {
      searchDropdown.style.display = 'none';
    }
  });
}

function renderSearchDropdown(q) {
  const normQ = q.toLowerCase();
  
  // Filter matching fantasy teams
  const matchingTeams = fantasyLeagueTeams.filter(t => {
    const tName = (t.team_name || '').toLowerCase();
    const oName = (t.owner_name || t.display_name || '').toLowerCase();
    return tName.includes(normQ) || oName.includes(normQ);
  }).slice(0, 3);

  // Filter matching players (excludes opponent match)
  const matches = filterPlayers(allSearchPlayers, q).slice(0, 8);

  if (!matches.length && !matchingTeams.length) {
    searchDropdown.innerHTML = `<div class="empty" style="padding:12px; font-size:12px">No matches found for "${escapeHtml(q)}"</div>`;
    searchDropdown.style.display = 'block';
    return;
  }

  searchDropdown.innerHTML = `
    <div style="display:flex; flex-direction:column; gap:2px">
      ${matchingTeams.length ? `
        <div class="micro faint" style="padding:4px 8px; text-transform:uppercase; letter-spacing:0.04em">Fantasy Bahamas Teams</div>
        ${matchingTeams.map(t => `
          <a href="#roster" class="search-item row align-between" style="padding:6px 10px; border-radius:8px; text-decoration:none; color:var(--text)">
            <div class="row align-center" style="gap:10px">
              ${userAvatar(t, 26)}
              <div>
                <strong style="font-size:13px">${escapeHtml(t.team_name || `Team ${t.roster_id}`)}</strong>
                <div class="micro faint">@${escapeHtml(t.owner_name || t.display_name || '')}</div>
              </div>
            </div>
            <span class="badge badge-amber mono" style="font-size:10px">Fantasy Team</span>
          </a>
        `).join('')}
        <div class="divider" style="margin:4px 0"></div>
      ` : ''}

      ${matches.length ? `
        <div class="micro faint" style="padding:4px 8px; text-transform:uppercase; letter-spacing:0.04em">NFL Players</div>
        ${matches.map(p => `
          <div class="search-item row align-between" data-search-pid="${p.player_id}" style="padding:8px 10px; border-radius:8px; cursor:pointer; transition:background 0.12s">
            <div class="row align-center" style="gap:10px">
              ${playerAvatar(p, 28)}
              <div>
                <div class="row align-center" style="gap:6px">
                  <strong style="font-size:13px">${escapeHtml(p.player_name || p.player_id)}</strong>
                  ${posBadge(p.position)}
                </div>
                <div class="micro faint" style="display:flex; align-items:center; gap:4px; margin-top:2px">
                  ${teamLogo(p.team, 12)} <span>${p.team || 'FA'}</span> ${p.owner_name ? `· <span style="color:var(--amber)">@${escapeHtml(p.owner_name)}</span>` : ''}
                </div>
              </div>
            </div>
            <div style="text-align:right">
              <span class="mono" style="font-weight:700; font-size:12px; color:var(--amber)">${Number(p.projected_points ?? 0).toFixed(1)}</span>
              <span class="micro faint" style="display:block">pts</span>
            </div>
          </div>
        `).join('')}
      ` : ''}

      <div class="divider" style="margin:4px 0"></div>
      <div id="viewAllSearchBtn" style="padding:8px; text-align:center; font:600 12px "Helvetica Neue", Helvetica, sans-serif; color:var(--sky); cursor:pointer">
        View all ${allSearchPlayers.length ? filterPlayers(allSearchPlayers, q).length : ''} matches in Projections →
      </div>
    </div>
  `;

  searchDropdown.style.display = 'block';

  searchDropdown.querySelectorAll('[data-search-pid]').forEach(el => {
    el.addEventListener('click', () => {
      const pid = el.getAttribute('data-search-pid');
      const p = allSearchPlayers.find(x => String(x.player_id) === String(pid));
      if (p) {
        searchDropdown.style.display = 'none';
        openPlayerModal(p);
      }
    });
  });

  searchDropdown.querySelector('#viewAllSearchBtn')?.addEventListener('click', () => {
    searchDropdown.style.display = 'none';
    location.hash = `projections?q=${encodeURIComponent(q)}`;
  });
}

function escapeHtml(s) {
  return String(s || '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

document.addEventListener('keydown', (e)=>{
  if (e.key === '/' && !/input|textarea/i.test(document.activeElement.tagName)) {
    e.preventDefault();
    if (globalSearch) { globalSearch.focus(); globalSearch.select(); }
    else location.hash = 'projections';
  }
});

// Linear-style mouse spotlight tracking for data cards and rows
document.addEventListener('mousemove', (e) => {
  const target = e.target.closest('.card, tr, .player-card-v2, .kpi-card');
  if (target) {
    const rect = target.getBoundingClientRect();
    target.style.setProperty('--mx', `${e.clientX - rect.left}px`);
    target.style.setProperty('--my', `${e.clientY - rect.top}px`);
  }
});

window.addEventListener('hashchange', render);
render();
setInterval(refreshStaleness, 30000);

// Pre-load search player cache in background for instant dropdown results
loadSearchPlayersCache();
