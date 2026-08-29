const routes = [
  { id: 'dashboard', label: 'Dashboard', path: '#dashboard' },
  { id: 'matchups', label: 'Matchups', path: '#matchups' },
  { id: 'projections', label: 'Projections', path: '#projections' },
  { id: 'tierlists', label: 'Tierlists', path: '#tierlists' },
  { id: 'auction', label: 'Auction', path: '#auction' },
  { id: 'roster', label: 'My Roster', path: '#roster' },
  { id: 'waiver', label: 'Waiver', path: '#waiver' },
  { id: 'trade', label: 'Trade Lab', path: '#trade' },
];

export function getRoute() {
  const raw = (location.hash || '#dashboard').replace('#','');
  const id = raw.split('?')[0];
  return routes.find(r => r.id === id) || routes[0];
}
export function allRoutes() { return routes; }
export function navigate(id) { location.hash = id; }
