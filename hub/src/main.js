import './styles/app.css';
import { allRoutes, getRoute } from './router.js';
import { fetchHealth, fetchMeta, computeStaleness } from './api.js';
import { shimmer } from './components/shimmer.js';
import { renderMobileNav, bindMobileNav } from './components/mobileNav.js';
import { renderDashboard } from './views/dashboard.js';
import { renderMatchups } from './views/matchups.js';
import { renderProjections } from './views/projections.js';
import { renderTierlists } from './views/tierlists.js';
import { renderAuction } from './views/auction.js';
import { renderRoster } from './views/roster.js';
import { renderWaiver } from './views/waiver.js';
import { renderTrade } from './views/trade.js';

const views = {
  dashboard: renderDashboard,
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
  tabs.innerHTML = allRoutes().map(r=>`
    <button class="nav-tab ${r.id===cur?'active':''}" data-route="${r.id}" role="tab" aria-selected="${r.id===cur}">${r.label}</button>
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
    app.innerHTML = `<div class="alert alert-bad">Failed to render ${route.id}: ${String(e)}<br><span class="faint" style="font:500 11px 'Fragment Mono', monospace">${e.stack || ''}</span></div>`;
    console.error(e);
  }
}

// global search "/"
document.addEventListener('keydown', (e)=>{
  if (e.key === '/' && !/input|textarea/i.test(document.activeElement.tagName)) {
    e.preventDefault();
    const input = document.getElementById('globalSearch');
    if (input) { input.focus(); input.select(); }
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
