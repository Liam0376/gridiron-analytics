// Bottom tab bar for mobile viewports
// Skill basis (ui-ux-pro-max): bottom nav ≤5 visible actions, 44px+ touch
// targets with 8px+ spacing, predictable back via hash deep-links.
const TABS = [
  { id: 'dashboard', label: 'Home', fullLabel: 'Dashboard', icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>' },
  { id: 'team', label: 'Team', fullLabel: 'Team Hub', icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>' },
  { id: 'projections', label: 'Proj', fullLabel: 'Projections', icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="12" width="4" height="9" rx="1"/><rect x="10" y="7" width="4" height="14" rx="1"/><rect x="17" y="3" width="4" height="18" rx="1"/></svg>' },
  { id: 'roster', label: 'League', fullLabel: 'League Directory', icon: '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><line x1="19" y1="8" x2="19" y2="14"/><line x1="22" y1="11" x2="16" y2="11"/></svg>' },
];

const MORE_TABS = [
  { id: 'matchups', label: 'Matchups' },
  { id: 'tierlists', label: 'Tierlists' },
  { id: 'auction', label: 'Auction' },
  { id: 'waiver', label: 'Waiver' },
  { id: 'trade', label: 'Trade Lab' },
  { id: 'props', label: 'Props' },
];

export function renderMobileNav(currentRouteId) {
  const isMore = MORE_TABS.some(t => t.id === currentRouteId);
  const moreIcon = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="1"/><circle cx="5" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg>';

  // NOTE: drawer + backdrop are SIBLINGS of <nav>, not children.
  // A closed drawer (translateY(100%)) still overlaps the nav bar region;
  // as a positioned child (z-99) it painted above the static tab buttons
  // and swallowed every tap. As siblings, nav (z-100) always wins.
  return `
    <nav class="mobile-nav" role="navigation" aria-label="Mobile sections">
      ${TABS.map(t => `
        <button type="button" class="mob-tab ${t.id === currentRouteId ? 'active' : ''}" data-route="${t.id}" aria-label="${t.fullLabel}" ${t.id === currentRouteId ? 'aria-current="page"' : ''}>
          ${t.icon}
          <span class="mob-tab-label" aria-hidden="true">${t.label}</span>
        </button>
      `).join('')}
      <button type="button" class="mob-tab ${isMore ? 'active' : ''}" id="moreTabBtn" aria-label="More sections" aria-haspopup="true" aria-expanded="false" ${isMore ? 'aria-current="page"' : ''}>
        ${moreIcon}
        <span class="mob-tab-label" aria-hidden="true">More</span>
      </button>
    </nav>
    <div class="more-drawer-backdrop" id="moreDrawerBackdrop"></div>
    <div class="more-drawer" id="moreDrawer" role="menu" aria-label="More sections">
      ${MORE_TABS.map(t => `
        <button type="button" class="more-drawer-item ${t.id === currentRouteId ? 'active' : ''}" data-route="${t.id}" role="menuitem" ${t.id === currentRouteId ? 'aria-current="page"' : ''}>${t.label}</button>
      `).join('')}
    </div>
  `;
}

export function bindMobileNav() {
  const nav = document.getElementById('mobileNav');
  if (!nav) return;

  const closeDrawer = () => {
    const drawer = document.getElementById('moreDrawer');
    const backdrop = document.getElementById('moreDrawerBackdrop');
    const moreBtn = document.getElementById('moreTabBtn');
    if (drawer) drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
    if (moreBtn) moreBtn.setAttribute('aria-expanded', 'false');
  };

  nav.querySelectorAll('[data-route]').forEach(btn => {
    btn.addEventListener('click', () => {
      closeDrawer();
      location.hash = btn.getAttribute('data-route');
    });
  });

  const moreBtn = document.getElementById('moreTabBtn');
  const drawer = document.getElementById('moreDrawer');
  const backdrop = document.getElementById('moreDrawerBackdrop');
  if (moreBtn && drawer) {
    moreBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const willOpen = !drawer.classList.contains('open');
      drawer.classList.toggle('open', willOpen);
      if (backdrop) backdrop.classList.toggle('open', willOpen);
      moreBtn.setAttribute('aria-expanded', willOpen ? 'true' : 'false');
      if (willOpen) {
        const first = drawer.querySelector('.more-drawer-item');
        if (first) first.focus({ preventScroll: true });
      }
    });
    if (backdrop) {
      backdrop.addEventListener('click', closeDrawer);
    }
    // Remove any previously bound listeners before re-binding
    // (renderMobileNavBar re-renders on every hash change).
    if (nav.__outsideHandler) {
      document.removeEventListener('click', nav.__outsideHandler);
    }
    if (nav.__escapeHandler) {
      document.removeEventListener('keydown', nav.__escapeHandler);
    }
    const onOutside = (e) => {
      if (!nav.contains(e.target)) closeDrawer();
    };
    const onEscape = (e) => {
      if (e.key === 'Escape') {
        closeDrawer();
        if (document.activeElement && nav.contains(document.activeElement)) {
          moreBtn.focus({ preventScroll: true });
        }
      }
    };
    nav.__outsideHandler = onOutside;
    nav.__escapeHandler = onEscape;
    document.addEventListener('click', onOutside);
    document.addEventListener('keydown', onEscape);
  }
}
