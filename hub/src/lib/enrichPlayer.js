// hub/src/lib/enrichPlayer.js — single canonical player enrichment used by every view.

import { computeVbdParams, vbdAuction, vbdAuctionUncapped } from '../components/vbdAuction.js';

function num(x, fallback = 0) {
  const n = Number(x);
  return Number.isFinite(n) ? n : fallback;
}

export function enrichPlayer(p, compRow, opts = {}) {
  const defaultSlot = opts.defaultSlot || 'BENCH';
  const comp = compRow || {};

  const pid = String(p.player_id || '');
  const pos = (p.position || p.position_group || 'UNK').toUpperCase();

  const weekly = num(p.projected_points ?? comp.projected_points ?? comp.weekly, 0);
  const season = num(comp.ros ?? comp.marketRos ?? weekly * 17, weekly * 17);
  const width = num(p.width ?? p.projection_width ?? comp.interval_width ?? comp.projection_width ?? comp.width, 5.0);
  const lower = num(p.projection_lower ?? p.lower_bound ?? p.lower, weekly - width / 2);
  const upper = num(p.projection_upper ?? p.upper_bound ?? p.upper, weekly + width / 2);

  const compPlayers = opts.compPlayers || (comp && comp.__compPlayers) || null;
  const vbdParams = opts.vbdParams || (comp && comp.__vbdParams) || (compPlayers ? computeVbdParams(compPlayers) : null);

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

  const passYd = Math.round(comp.market_season_stats?.passing_yards ?? (p.pass_yd ? p.pass_yd * 17 : (pos === 'QB' ? weekly * 16.5 * 17 : 0)));
  const rushYd = Math.round(comp.market_season_stats?.rushing_yards ?? (p.rush_yd ? p.rush_yd * 17 : (pos === 'RB' ? weekly * 5.2 * 17 : pos === 'QB' ? weekly * 1.4 * 17 : 0)));
  const recYd = Math.round(comp.market_season_stats?.receiving_yards ?? (p.rec_yd ? p.rec_yd * 17 : ((pos === 'WR' || pos === 'TE') ? weekly * 5.6 * 17 : pos === 'RB' ? weekly * 2.1 * 17 : 0)));
  const recs = Math.round(comp.market_season_stats?.receptions ?? (p.receptions ? p.receptions * 17 : ((pos === 'WR' || pos === 'TE') ? weekly * 0.46 * 17 : pos === 'RB' ? weekly * 0.28 * 17 : 0)));
  const tds = Number((comp.market_season_stats?.total_tds ?? (weekly * 0.52 * 17 / 10)).toFixed(1));

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