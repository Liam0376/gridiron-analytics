// hub/src/lib/enrichPlayer.js — single canonical player enrichment used by every view.

import { computeVbdParams, vbdAuction, vbdAuctionUncapped } from '../components/vbdAuction.js';

function num(x, fallback = 0) {
  const n = Number(x);
  return Number.isFinite(n) ? n : fallback;
}

export function enrichPlayer(p, compRow, opts = {}) {
  const defaultSlot = opts.defaultSlot || 'BENCH';
  const pid = String(p.player_id || '');
  // why lookup here (user-caught live bug, 2026-09-10): every call site
  // passes compRow=null and only forwards opts.compPlayers (a flat array),
  // so comp.market_season_stats was always undefined and the ratio-guess
  // fallback below (weekly fantasy points * yards-per-point * 17 games)
  // fired for every player — e.g. a ~25pt/week QB projected to 7043 season
  // passing yards, nearly 1500 over the NFL record. Real market season
  // stats already exist in compPlayers; they just weren't being matched
  // to this player.
  const comp = compRow || (opts.compPlayers || []).find(c => String(c.player_id) === pid) || {};
  const pos = (p.position || p.position_group || 'UNK').toUpperCase();

  const weekly = num(p.projected_points ?? comp.projected_points ?? comp.weekly, 0);
  const season = num(comp.ros ?? comp.marketRos ?? weekly * 17, weekly * 17);
  const width = num(p.width ?? p.projection_width ?? comp.interval_width ?? comp.projection_width ?? comp.width, 5.0);
  // why no /2: width is HALF-width (unified 2026-09-09). Floor matches src.
  const lower = num(p.projection_lower ?? p.lower_bound ?? p.lower, Math.max(0, weekly - width));
  const upper = num(p.projection_upper ?? p.upper_bound ?? p.upper, weekly + width);

  const compPlayers = opts.compPlayers || (comp && comp.__compPlayers) || null;
  const vbdParams = opts.vbdParams || (comp && comp.__vbdParams) || (compPlayers ? computeVbdParams(compPlayers, opts.league) : null);

  const modelSeason = num(
    p.model_season_points ?? comp.model_season_points ?? (p._neutral_points != null ? p._neutral_points * 17 : weekly * 17),
    weekly * 17
  );

  const gridironAuction = num(
    p.gridironAuction ?? comp.auction ?? (vbdParams
      ? (comp.model_season_points != null
          ? vbdAuction(num(comp.model_season_points), pos, vbdParams)
          : vbdAuction(modelSeason, pos, vbdParams))
      : Math.max(1, Math.round(Math.max(0, modelSeason - 100) * 0.25))),
    1
  );

  const gridironUncapped = num(
    comp.auctionUncapped ?? (vbdParams
      ? vbdAuctionUncapped(comp.model_season_points ?? modelSeason, pos, vbdParams)
      : null),
    gridironAuction
  );

  const marketVbd = (vbdParams && comp.market_season_points != null)
    ? vbdAuction(num(comp.market_season_points), pos, vbdParams)
    : null;
  const marketUncapped = comp.marketAuctionUncapped ?? ((vbdParams && comp.market_season_points != null)
    ? vbdAuctionUncapped(num(comp.market_season_points), pos, vbdParams)
    : null);
  const marketAuction = num(
    p.auction_price_paid ?? p.marketAuction ?? comp.marketAuction ?? marketVbd ?? Math.max(1, Math.round(gridironAuction * 0.9)),
    1
  );

  const replPts = (vbdParams?.replPts?.[pos] ?? 100);
  const vor = Math.max(0, modelSeason - replPts);
  const deltaAuction = gridironAuction - marketAuction;

  const slot = p.slot || defaultSlot;
  const ecr = comp.fp_ecr ?? p.fp_ecr ?? null;
  const ecrPos = comp.fp_ecr_pos ?? p.fp_ecr_pos ?? null;
  const adp = comp.fp_adp ?? p.fp_adp ?? null;
  const tier = comp.fp_tier ?? comp.tier ?? p.tier ?? null;
  const edge = (p.edge || comp.edge || 'NEUTRAL').toUpperCase();
  const status = p.injury_status || comp.injury_status || null;
  const windMph = num(p.wind_speed_mph ?? p.wind_mph, 0);
  const marketWeekly = num(
    comp.market_season_points != null ? comp.market_season_points / 17 : (comp.projected_points ?? weekly),
    weekly
  );

  let rec = 'START';
  const slotUp = String(slot).toUpperCase();
  if (slotUp.startsWith('BN') || slotUp === 'BENCH' || slotUp === 'IR') {
    rec = weekly >= 12.0 ? 'POTENTIAL START' : 'BENCH';
  } else {
    rec = width > 7.0 ? 'TOSS-UP' : weekly >= 10.0 ? 'CONFIDENT' : 'RISK';
  }

  // why no ratio-guess fallback: a prior fallback estimated season yards
  // from weekly fantasy points times a made-up "yards per point" constant
  // (e.g. weekly * 16.5 * 17) — nonsense math that produced a 7043-yard QB
  // season projection (user-caught live bug, 2026-09-10). Same honesty
  // rule as is_empty_projection elsewhere: no real market_season_stats ->
  // show 0/unknown, never a fabricated number.
  const passYd = Math.round(comp.market_season_stats?.passing_yards ?? 0);
  const rushYd = Math.round(comp.market_season_stats?.rushing_yards ?? 0);
  const recYd = Math.round(comp.market_season_stats?.receiving_yards ?? 0);
  const recs = Math.round(comp.market_season_stats?.receptions ?? 0);
  const tds = Number((comp.market_season_stats?.total_tds ?? 0).toFixed(1));

  return {
    ...p,
    player_id: pid,
    player_name: p.player_name || p.name || pid,
    position: pos,
    team: (p.team || '').toUpperCase(),
    opponent_team: p.opponent_team || '',
    weekly,
    marketWeekly,
    season,
    width,
    lower,
    upper,
    vor,
    gridironAuction,
    gridironUncapped,
    marketAuction,
    marketUncapped,
    deltaAuction,
    ecr,
    ecrPos,
    adp,
    tier,
    edge,
    injury_status: status,
    slot,
    recommendation: rec,
    wind_mph: windMph,
    season_pass_yd: passYd,
    season_rush_yd: rushYd,
    season_rec_yd: recYd,
    season_rec: recs,
    season_tds: tds,
  };
}