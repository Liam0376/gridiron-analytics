const routes = [
  { id: 'dashboard', label: 'Dashboard', path: '#dashboard' },
  { id: 'team', label: 'Team Hub', path: '#team' },
  { id: 'matchups', label: 'Matchups', path: '#matchups' },
  { id: 'projections', label: 'Projections', path: '#projections' },
  { id: 'tierlists', label: 'Tier Lists', path: '#tierlists' },
  { id: 'roster', label: 'League Directory', path: '#roster' },
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
