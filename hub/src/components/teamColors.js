// NFL 32-team color map
export const TEAM_COLORS = {
  ARI: { primary: '#97233F', secondary: '#000000', name: 'Cardinals' },
  ATL: { primary: '#A71930', secondary: '#000000', name: 'Falcons' },
  BAL: { primary: '#241773', secondary: '#000000', name: 'Ravens' },
  BUF: { primary: '#00338D', secondary: '#C60C30', name: 'Bills' },
  CAR: { primary: '#0085CA', secondary: '#101820', name: 'Panthers' },
  CHI: { primary: '#0B162A', secondary: '#C83803', name: 'Bears' },
  CIN: { primary: '#FB4F14', secondary: '#000000', name: 'Bengals' },
  CLE: { primary: '#311D00', secondary: '#FF3C00', name: 'Browns' },
  DAL: { primary: '#003594', secondary: '#869397', name: 'Cowboys' },
  DEN: { primary: '#FB4F14', secondary: '#002244', name: 'Broncos' },
  DET: { primary: '#0076B6', secondary: '#B0B7BC', name: 'Lions' },
  GB:  { primary: '#203731', secondary: '#FFB612', name: 'Packers' },
  HOU: { primary: '#03202F', secondary: '#A71930', name: 'Texans' },
  IND: { primary: '#002C5F', secondary: '#A2AAAD', name: 'Colts' },
  JAX: { primary: '#006778', secondary: '#D7A22A', name: 'Jaguars' },
  KC:  { primary: '#E31837', secondary: '#FFB81C', name: 'Chiefs' },
  LAC: { primary: '#0080C6', secondary: '#FFC20E', name: 'Chargers' },
  LAR: { primary: '#003594', secondary: '#FFA300', name: 'Rams' },
  LV:  { primary: '#000000', secondary: '#A5ACAF', name: 'Raiders' },
  MIA: { primary: '#008E97', secondary: '#FC4C02', name: 'Dolphins' },
  MIN: { primary: '#4F2683', secondary: '#FFC62F', name: 'Vikings' },
  NE:  { primary: '#002244', secondary: '#C60C30', name: 'Patriots' },
  NO:  { primary: '#D3BC8D', secondary: '#101820', name: 'Saints' },
  NYG: { primary: '#0B2265', secondary: '#A71930', name: 'Giants' },
  NYJ: { primary: '#125740', secondary: '#000000', name: 'Jets' },
  PHI: { primary: '#004C54', secondary: '#A5ACAF', name: 'Eagles' },
  PIT: { primary: '#FFB612', secondary: '#101820', name: 'Steelers' },
  SEA: { primary: '#002244', secondary: '#69BE28', name: 'Seahawks' },
  SF:  { primary: '#AA0000', secondary: '#B3995D', name: 'San Francisco 49ers' },
  TB:  { primary: '#D50A0A', secondary: '#34302B', name: 'Buccaneers' },
  TEN: { primary: '#0C2340', secondary: '#4B92DB', name: 'Titans' },
  WAS: { primary: '#5A1414', secondary: '#FFB612', name: 'Commanders' },
};

export function getTeamColor(abbr) {
  const t = TEAM_COLORS[(abbr || '').toUpperCase()];
  return t ? t.primary : '#6B7280';
}

// Dark-theme readability: mix a hex color toward white by amt (0-1).
export function brighten(hex, amt = 0.55) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return hex;
  const n = parseInt(m[1], 16);
  const mix = c => Math.round(c + (255 - c) * amt);
  const r = mix((n >> 16) & 255), g = mix((n >> 8) & 255), b = mix(n & 255);
  return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1).toUpperCase();
}

// Relative luminance 0-1 (WCAG weights).
export function luminance(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex || '');
  if (!m) return 1;
  const n = parseInt(m[1], 16);
  const lin = c => {
    c /= 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
}

// Display color for dark backgrounds (badges, pills, fallback squares).
// Primaries below the floor come back brightened but still recognizable;
// bright primaries pass through untouched. getTeamColor (raw identity)
// stays for large surfaces that carry their own contrast.
export function getTeamDisplayColor(abbr) {
  const raw = getTeamColor(abbr);
  return luminance(raw) < 0.12 ? brighten(raw) : raw;
}
