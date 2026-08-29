// Bottom tab bar for mobile viewports
const TABS = [
  { id: 'dashboard', label: 'Home', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>' },
  { id: 'projections', label: 'Proj', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>' },
  { id: 'auction', label: 'Auction', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>' },
  { id: 'roster', label: 'Roster', icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>' },
];

const MORE_TABS = [
  { id: 'matchups', label: 'Matchups' },
  { id: 'tierlists', label: 'Tierlists' },
  { id: 'waiver', label: 'Waiver' },
  { id: 'trade', label: 'Trade Lab' },
];

export function renderMobileNav(currentRouteId) {
  const isMore = MORE_TABS.some(t => t.id === currentRouteId);
  const moreIcon = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>';

  return `
    <nav class="mobile-nav" id="mobileNav">
      ${TABS.map(t => `
        <button class="mob-tab ${t.id === currentRouteId ? 'active' : ''}" data-route="${t.id}">
          ${t.icon}
          <span class="mob-tab-label">${t.label}</span>
        </button>
      `).join('')}
      <button class="mob-tab ${isMore ? 'active' : ''}" id="moreTabBtn">
        ${moreIcon}
        <span class="mob-tab-label">More</span>
      </button>
      <div class="more-drawer" id="moreDrawer">
        ${MORE_TABS.map(t => `
          <button class="more-drawer-item ${t.id === currentRouteId ? 'active' : ''}" data-route="${t.id}">${t.label}</button>
        `).join('')}
      </div>
    </nav>
  `;
}

export function bindMobileNav() {
  const nav = document.getElementById('mobileNav');
  if (!nav) return;

  nav.querySelectorAll('[data-route]').forEach(btn => {
    btn.addEventListener('click', () => {
      const drawer = document.getElementById('moreDrawer');
      if (drawer) drawer.classList.remove('open');
      location.hash = btn.getAttribute('data-route');
    });
  });

  const moreBtn = document.getElementById('moreTabBtn');
  const drawer = document.getElementById('moreDrawer');
  if (moreBtn && drawer) {
    moreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      drawer.classList.toggle('open');
    });
    document.addEventListener('click', (e) => {
      if (!nav.contains(e.target)) drawer.classList.remove('open');
    });
  }
}
