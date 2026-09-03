import './styles/app.css';
import { allRoutes, getRoute } from './router.js';
import { fetchHealth, fetchMeta, computeStaleness, fetchProjections, fetchComparison, fetchRoster } from './api.js';
import { shimmer } from './components/shimmer.js';
import { renderMobileNav, bindMobileNav } from './components/mobileNav.js';
import { renderDashboard } from './views/dashboard.js';
import { filterPlayers } from './search.js';
import { playerAvatar } from './components/playerAvatar.js';
import { userAvatar } from './components/userAvatar.js';
import { posBadge } from './components/badges.js';
import { teamLogo } from './components/teamLogo.js';
import { openPlayerModal } from './components/playerModal.js';

// Lazy-loaded view modules — initial bundle stays small (~40% smaller),
// heavy views (auction 940 lines, trade 390, etc.) load only on navigation.
const viewLoaders = {
  dashboard: () => import('./views/dashboard.js'),
  team: () => import('./views/team.js'),
  matchups: () => import('./views/matchups.js'),
  projections: () => import('./views/projections.js'),
  tierlists: () => import('./views/tierlists.js'),
  auction: () => import('./views/auction.js'),
  roster: () => import('./views/roster.js'),
  waiver: () => import('./views/waiver.js'),
  trade: () => import('./views/trade.js'),
};
const viewCache = new Map();

async function loadView(id) {
  const loader = viewLoaders[id] || viewLoaders.dashboard;
  if (viewCache.has(id)) return viewCache.get(id);
  const mod = await loader();
  // Pick the exported render function by convention: render<PascalCase>(root).
  const pascal = id.charAt(0).toUpperCase() + id.slice(1);
  const fn = mod[`render${pascal}`] || mod.default;
  if (!fn) throw new Error(`view ${id} has no render function`);
  viewCache.set(id, fn);
  return fn;
}

function renderNav() {
  const tabs = document.getElementById('navTabs');
  if (!tabs) return;
  tabs.setAttribute('role', 'tablist');
  tabs.setAttribute('aria-label', 'Sections');
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
    <button id="tab-${r.id}" class="sidebar-tab ${r.id===cur?'active':''}" data-route="${r.id}" role="tab" aria-selected="${r.id===cur}" aria-controls="app" tabindex="${r.id===cur?'0':'-1'}">${icons[r.id]||icons.dashboard}<span class="label">${r.label}</span></button>
  `).join('');
  // APG tabpanel wiring: #app is the controlled panel (index.html owns the element).
  const appPanel = document.getElementById('app');
  if (appPanel) {
    appPanel.setAttribute('role', 'tabpanel');
    appPanel.setAttribute('aria-labelledby', `tab-${cur}`);
  }
  const tabBtns = Array.from(tabs.querySelectorAll('[data-route]'));
  const activateTab = (btn) => { location.hash = btn.getAttribute('data-route'); };
  tabBtns.forEach((btn, idx)=>{
    btn.addEventListener('click', ()=> activateTab(btn));
    btn.addEventListener('keydown', (e)=>{
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activateTab(btn);
        return;
      }
      let nextIdx = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') nextIdx = (idx + 1) % tabBtns.length;
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') nextIdx = (idx - 1 + tabBtns.length) % tabBtns.length;
      else if (e.key === 'Home') nextIdx = 0;
      else if (e.key === 'End') nextIdx = tabBtns.length - 1;
      if (nextIdx != null) {
        e.preventDefault();
        tabBtns.forEach(b=>b.setAttribute('tabindex','-1'));
        const next = tabBtns[nextIdx];
        next.setAttribute('tabindex','0');
        next.focus();
        activateTab(next);
      }
    });
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
    // detection failed, default to cold
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
  // Disconnect prior IntersectionObserver before attaching new one.
  if (app.__revealObserver) {
    app.__revealObserver.disconnect();
    app.__revealObserver = null;
  }
  try {
    const fn = await loadView(route.id);
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
    app.__revealObserver = io;
    app.querySelectorAll('.reveal').forEach(el=> io.observe(el));
  } catch (e) {
    app.innerHTML = `<div class="alert alert-bad">Couldn't load this view. Try refreshing.</div>`;
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
          // Reset promise so the next call can retry instead of returning a stuck in-flight.
          searchPromise = null;
        }
      })();
    }
    await searchPromise;
  }
}

if (globalSearch && searchDropdown) {
  let searchTimer = null;
  let searchActiveIndex = -1;

  // APG combobox/listbox wiring
  globalSearch.setAttribute('role', 'combobox');
  globalSearch.setAttribute('aria-expanded', 'false');
  globalSearch.setAttribute('aria-controls', 'searchDropdown');
  globalSearch.setAttribute('aria-autocomplete', 'list');
  globalSearch.setAttribute('aria-haspopup', 'listbox');
  searchDropdown.setAttribute('role', 'listbox');
  searchDropdown.setAttribute('aria-label', 'Search results');

  const setSearchExpanded = (open) => {
    globalSearch.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (!open) {
      searchActiveIndex = -1;
      globalSearch.removeAttribute('aria-activedescendant');
    }
  };
  const hideSearchDropdown = () => {
    searchDropdown.style.display = 'none';
    setSearchExpanded(false);
  };
  const updateSearchActive = () => {
    const opts = Array.from(searchDropdown.querySelectorAll('[role="option"]'));
    opts.forEach((el, i) => {
      const active = i === searchActiveIndex;
      el.setAttribute('aria-selected', active ? 'true' : 'false');
      el.classList.toggle('active', active);
      if (active) {
        globalSearch.setAttribute('aria-activedescendant', el.id);
        el.scrollIntoView({ block: 'nearest' });
      }
    });
    if (searchActiveIndex === -1) globalSearch.removeAttribute('aria-activedescendant');
  };
  const activateSearchOption = (idx) => {
    const opts = Array.from(searchDropdown.querySelectorAll('[role="option"]'));
    const el = opts[idx];
    if (!el) return false;
    // Reuse the element's click handler so keyboard matches mouse behavior.
    el.click();
    return true;
  };
  // Expose for renderSearchDropdown closure
  globalSearch.__searchNav = { updateSearchActive, hideSearchDropdown, activateSearchOption, getActive: () => searchActiveIndex, setActive: (v) => { searchActiveIndex = v; } };

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
        hideSearchDropdown();
        return;
      }
      await loadSearchPlayersCache();
      renderSearchDropdown(q);
    }, 350);
  });

  globalSearch.addEventListener('keydown', (e) => {
    const opts = Array.from(searchDropdown.querySelectorAll('[role="option"]'));
    const isOpen = searchDropdown.style.display === 'block' && opts.length > 0;
    if (e.key === 'ArrowDown') {
      if (!isOpen) return;
      e.preventDefault();
      searchActiveIndex = (searchActiveIndex + 1) % opts.length;
      updateSearchActive();
    } else if (e.key === 'ArrowUp') {
      if (!isOpen) return;
      e.preventDefault();
      searchActiveIndex = (searchActiveIndex - 1 + opts.length) % opts.length;
      updateSearchActive();
    } else if (e.key === 'Home' && isOpen) {
      e.preventDefault();
      searchActiveIndex = 0;
      updateSearchActive();
    } else if (e.key === 'End' && isOpen) {
      e.preventDefault();
      searchActiveIndex = opts.length - 1;
      updateSearchActive();
    } else if (e.key === 'Enter') {
      if (isOpen && searchActiveIndex >= 0) {
        e.preventDefault();
        activateSearchOption(searchActiveIndex);
        return;
      }
      const q = globalSearch.value.trim();
      if (q) {
        hideSearchDropdown();
        location.hash = `projections?q=${encodeURIComponent(q)}`;
      }
    } else if (e.key === 'Escape') {
      hideSearchDropdown();
    }
  });

  document.addEventListener('click', (e) => {
    if (!globalSearch.contains(e.target) && !searchDropdown.contains(e.target)) {
      hideSearchDropdown();
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
    globalSearch.setAttribute('aria-expanded', 'true');
    return;
  }

  searchDropdown.innerHTML = `
    <div style="display:flex; flex-direction:column; gap:2px">
      ${matchingTeams.length ? `
        <div class="micro faint" style="padding:4px 8px; text-transform:uppercase; letter-spacing:0.04em" aria-hidden="true">League Teams</div>
        ${matchingTeams.map((t, i) => `
          <a href="#roster" id="search-opt-team-${i}" role="option" aria-selected="false" tabindex="-1" class="search-item row align-between" style="padding:6px 10px; border-radius:8px; text-decoration:none; color:var(--text)">
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
        <div class="micro faint" style="padding:4px 8px; text-transform:uppercase; letter-spacing:0.04em" aria-hidden="true">NFL Players</div>
        ${matches.map((p, i) => `
          <div id="search-opt-player-${i}" role="option" aria-selected="false" tabindex="-1" class="search-item row align-between" data-search-pid="${p.player_id}" style="padding:8px 10px; border-radius:8px; cursor:pointer; transition:background 0.12s">
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
      <div id="viewAllSearchBtn" role="option" aria-selected="false" tabindex="-1" style="padding:8px; text-align:center; font:600 12px "Helvetica Neue", Helvetica, sans-serif; color:var(--sky); cursor:pointer">
        View all ${allSearchPlayers.length ? filterPlayers(allSearchPlayers, q).length : ''} matches in Projections →
      </div>
    </div>
  `;

  searchDropdown.style.display = 'block';
  globalSearch.setAttribute('aria-expanded', 'true');
  if (globalSearch.__searchNav) globalSearch.__searchNav.setActive(-1);

  const bindOptionKeys = (el) => {
    el.addEventListener('keydown', (ev) => {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        el.click();
      }
    });
  };

  searchDropdown.querySelectorAll('[data-search-pid]').forEach(el => {
    const openForEl = () => {
      const pid = el.getAttribute('data-search-pid');
      const p = allSearchPlayers.find(x => String(x.player_id) === String(pid));
      if (p) {
        searchDropdown.style.display = 'none';
        globalSearch.setAttribute('aria-expanded', 'false');
        openPlayerModal(p);
      }
    };
    el.addEventListener('click', openForEl);
    bindOptionKeys(el);
  });

  searchDropdown.querySelectorAll('a[role="option"]').forEach(el => {
    bindOptionKeys(el);
    el.addEventListener('click', () => {
      searchDropdown.style.display = 'none';
      globalSearch.setAttribute('aria-expanded', 'false');
    });
  });

  searchDropdown.querySelector('#viewAllSearchBtn')?.addEventListener('click', () => {
    searchDropdown.style.display = 'none';
    globalSearch.setAttribute('aria-expanded', 'false');
    location.hash = `projections?q=${encodeURIComponent(q)}`;
  });
  searchDropdown.querySelector('#viewAllSearchBtn') && bindOptionKeys(searchDropdown.querySelector('#viewAllSearchBtn'));
}

document.addEventListener('keydown', (e)=>{
  if (e.key === '/' && !/input|textarea/i.test(document.activeElement.tagName)) {
    e.preventDefault();
    if (globalSearch) { globalSearch.focus(); globalSearch.select(); }
    else location.hash = 'projections';
  }
});

// Linear-style mouse spotlight tracking for data cards and rows (rAF throttled)
let mxPending = null;
let mxLastEvent = null;
function applyMx() {
  if (!mxLastEvent) return;
  const e = mxLastEvent;
  mxPending = null;
  const target = e.target.closest('.card');
  if (!target) return;
  const rect = target.getBoundingClientRect();
  target.style.setProperty('--mx', `${e.clientX - rect.left}px`);
  target.style.setProperty('--my', `${e.clientY - rect.top}px`);
}
document.addEventListener('mousemove', (e) => {
  mxLastEvent = e;
  if (mxPending != null) return;
  mxPending = requestAnimationFrame(applyMx);
});

window.addEventListener('hashchange', render);
render();
setInterval(refreshStaleness, 30000);

// Pre-load search player cache in background for instant dropdown results
loadSearchPlayersCache();
