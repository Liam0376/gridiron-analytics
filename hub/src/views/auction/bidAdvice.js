// hub/src/views/auction/bidAdvice.js — instant bid advice for the on-the-block player.
// Pure function over (p, state, myRemaining, maxBid, myNeeds, slotsLeft) — no DOM, no fetch.

export function liveAdviceFor(p, state, myRemaining, maxBid, myNeeds, slotsLeft) {
  const pos = (p.position || '').toUpperCase();
  const need = myNeeds[pos] ?? 0;
  const tier = p.fp_tier ?? p.tier ?? 5;
  const edge = p.edge || 'NEUTRAL';
  const width = Number(p.widthRos ?? p.width * 4 ?? 20);
  const auctionVal = p.auction ?? 1;
  const delta = p.deltaRos;
  let cap = Math.min(auctionVal + (edge === 'BUY' ? 6 : edge === 'SELL' ? -2 : 2), maxBid);
  if (tier <= 2 && edge === 'BUY') cap = Math.min(cap + 4, maxBid);
  if (width > 40) cap = Math.max(1, cap - 2);
  cap = Math.max(1, Math.min(cap, myRemaining - Math.max(0, slotsLeft - 1)));
  let title, color, text;
  if (myRemaining < 5) {
    title = 'BUDGET TIGHT — $1 only';
    color = 'var(--crimson)';
    text = `You have $${myRemaining} left. Only bid $1 unless ${p.player_name} is your last starter.`;
  } else if (p.isDrafted) {
    title = 'Already drafted';
    color = 'var(--text-faint)';
    text = `${p.player_name} is gone for $${p.draftedPrice ?? '?'} (${p.draftedBy}).`;
    cap = 0;
  } else if (edge === 'BUY' && need > 0) {
    title = 'STRONG BUY — bid aggressively';
    color = 'var(--emerald)';
    text = `Model sees +${delta != null ? Number(delta).toFixed(0) : '?'} season vs Market (T${tier}, ${pos} need: ${need} left). Value $${auctionVal} → cap $${cap} (max $${maxBid}). Narrow interval ±${width.toFixed(0)} = floor play.`;
  } else if (edge === 'BUY') {
    title = 'BUY — value but you\'re set at ' + pos;
    color = 'var(--emerald)';
    text = `Value says $${auctionVal} (+${delta != null ? Number(delta).toFixed(0) : '?'} vs Market, T${tier}) but you have no ${pos} need (${need} left). Nominate to drain opponents, or cap $${cap} if you want depth.`;
  } else if (edge === 'SELL') {
    title = 'CAUTION — Market overpay';
    color = 'var(--crimson)';
    text = `Market pays ${delta != null ? Math.abs(Number(delta)).toFixed(0) : '?'} season more than Model (T${tier}). Let others burn cash — cap $${cap} ($${auctionVal} sticker). Wide interval ±${width.toFixed(0)} = risky.`;
  } else {
    title = need > 0 ? 'Fair value — fill need' : 'Fair value — depth';
    color = need > 0 ? 'var(--amber)' : 'var(--text-muted)';
    text = `Neutral edge T${tier} — fair at $${auctionVal} (Δ ${delta != null ? (Number(delta) > 0 ? '+' : '') + Number(delta).toFixed(0) : '—'}). ${need > 0 ? `You need ${need} more ${pos} — cap $${cap}.` : `No ${pos} need — cap $${cap} for depth.`} Max $${maxBid}, $${myRemaining} left.`;
  }
  return { title, color, text, cap: Math.max(0, Math.round(cap)) };
}