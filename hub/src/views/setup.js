// hub/src/views/setup.js — league setup + switcher modal.
// Flow: enter Sleeper username → pick one of their NFL leagues →
// confirm draft type → sync. The username is the only typed input;
// league id, name, teams, season, draft type, scoring and rosters
// all come from Sleeper. Known leagues on this machine stay a
// one-click quick-select.
import { fetchDraftInfo, fetchMeta, fetchReady, setActiveLeague, triggerRefresh } from '../api.js';
import { getLeagueId, setDraftTypeOverride, getDraftTypeOverride, isValidLeagueId, addKnownLeague } from '../lib/league.js';
import { escapeHtml, escapeAttr } from '../lib/escape.js';
import { trapFocus } from '../lib/focusTrap.js';

function overlayHtml(inner) {
  return `<div class="player-modal-backdrop show" id="setupBackdrop" style="position:fixed; inset:0; z-index:2000; background:rgba(0,0,0,0.55); display:flex; align-items:center; justify-content:center; padding:16px">
    <div class="card player-modal-card show" id="setupCard" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="setupTitle" style="max-width:520px; width:100%; max-height:90vh; overflow:auto; padding:20px">
      ${inner}
    </div>
  </div>`;
}

function draftBadge(t) {
  if (t === 'auction') return `<span class="badge" style="background:var(--amber-dim); color:var(--amber)">auction</span>`;
  if (t === 'snake') return `<span class="badge" style="background:var(--sky-dim); color:var(--sky)">snake</span>`;
  return `<span class="badge">draft type unknown</span>`;
}

export async function openSetupModal({ onDone } = {}) {
  const triggerEl = document.activeElement;
  let container = document.getElementById('setupModalRoot');
  if (!container) {
    container = document.createElement('div');
    container.id = 'setupModalRoot';
    document.body.appendChild(container);
  }

  // The modal has three views (username → league list → confirm); each
  // mount re-traps focus and rebinds the shared chrome.
  let release = null;
  const cleanup = () => { try { if (release) release(); } catch (_) {} release = null; };
  const close = (saved) => {
    cleanup();
    container.innerHTML = '';
    try { if (triggerEl && triggerEl.focus) triggerEl.focus(); } catch (_) {}
    if (typeof onDone === 'function') onDone(saved);
  };
  const mount = (html) => {
    cleanup();
    container.innerHTML = overlayHtml(html);
    const card = container.querySelector('#setupCard');
    release = trapFocus(card, triggerEl, () => close(false));
    const closeBtn = container.querySelector('#setupClose');
    if (closeBtn) closeBtn.addEventListener('click', () => close(false));
    container.querySelector('#setupBackdrop').addEventListener('click', (e) => {
      if (e.target.id === 'setupBackdrop') close(false);
    });
    return card;
  };

  const meta = await fetchMeta().catch(() => null);
  const configured = (meta && meta.configuredLeagues) || [];
  const current = getLeagueId();
  const season = (meta && meta.season) ? String(meta.season) : String(new Date().getFullYear());

  const knownHtml = configured.length
    ? `<label class="faint" for="setupExisting" style="display:block; margin-bottom:4px">Synced leagues on this machine</label>
    <div class="row" style="gap:8px; margin-bottom:16px">
      <select id="setupExisting" class="team-select-dropdown" style="flex:1">${configured.map(l => {
        const id = String(l.league_id || '');
        if (!id) return '';
        const sel = id === current ? 'selected' : '';
        const label = `${l.league_name || 'League'} (${id.slice(0, 6)}…)`;
        return `<option value="${escapeAttr(id)}" ${sel}>${escapeHtml(label)}</option>`;
      }).join('')}</select>
      <button class="btn btn-ghost btn-sm" id="setupUseExisting">Use</button>
    </div>`
    : '';

  const renderStep1 = () => {
    const card = mount(`
      <h2 id="setupTitle" style="margin:0 0 4px">Fantasy league setup</h2>
      <p class="faint" style="margin:0 0 16px">Enter your Sleeper username to find your leagues.</p>
      ${knownHtml}
      <label class="faint" for="setupUsername" style="display:block; margin-bottom:4px">Sleeper username</label>
      <div class="row" style="gap:8px; margin-bottom:12px">
        <input id="setupUsername" class="search-top" style="flex:1; border:1px solid var(--border); border-radius:8px; padding:8px 10px" placeholder="your_username" autocomplete="off" autocapitalize="none" spellcheck="false" />
        <button class="btn btn-primary btn-sm" id="setupLookup">Find leagues</button>
      </div>
      <div id="setupResult" aria-live="polite"></div>
      <div class="row" style="gap:8px; margin-top:16px; justify-content:flex-end">
        <button class="btn btn-ghost btn-sm" id="setupClose">Close</button>
      </div>
    `);

    const useExisting = card.querySelector('#setupUseExisting');
    if (useExisting) {
      useExisting.addEventListener('click', () => {
        const id = card.querySelector('#setupExisting').value;
        if (!isValidLeagueId(id)) return;
        setActiveLeague(id);
        close(true);
      });
    }

    const resultEl = card.querySelector('#setupResult');
    const doLookup = async () => {
      const username = (card.querySelector('#setupUsername').value || '').trim();
      if (!username) {
        resultEl.innerHTML = `<div class="alert alert-bad">Enter your Sleeper username.</div>`;
        return;
      }
      resultEl.innerHTML = `<div class="faint">Looking up <strong>${escapeHtml(username)}</strong>…</div>`;
      let user;
      try {
        const resp = await fetch(`https://api.sleeper.app/v1/user/${encodeURIComponent(username)}`);
        if (!resp.ok) {
          resultEl.innerHTML = `<div class="alert alert-bad">User not found — check spelling. Sleeper usernames are case-sensitive.</div>`;
          return;
        }
        user = await resp.json();
      } catch (err) {
        resultEl.innerHTML = `<div class="alert alert-bad">Network error: ${escapeHtml(err && err.message || 'connection failed')}.</div>`;
        return;
      }
      if (!user || !user.user_id) {
        resultEl.innerHTML = `<div class="alert alert-bad">Couldn't find that user on Sleeper.</div>`;
        return;
      }
      const who = user.display_name || username;
      resultEl.innerHTML = `<div class="faint">Found <strong>${escapeHtml(who)}</strong> — loading ${escapeHtml(season)} leagues…</div>`;
      let leagues = [];
      try {
        const lr = await fetch(`https://api.sleeper.app/v1/user/${encodeURIComponent(user.user_id)}/leagues/nfl/${season}`);
        if (lr.ok) leagues = await lr.json();
      } catch (_) { leagues = []; }
      if (!Array.isArray(leagues) || !leagues.length) {
        resultEl.innerHTML = `<div class="alert alert-bad">No NFL leagues found for <strong>${escapeHtml(who)}</strong> in ${escapeHtml(season)}.</div>`;
        return;
      }
      renderLeagueList(leagues, who);
    };
    card.querySelector('#setupLookup').addEventListener('click', doLookup);
    card.querySelector('#setupUsername').addEventListener('keydown', (e) => {
      if (e.key === 'Enter') doLookup();
    });
  };

  const renderLeagueList = (leagues, who) => {
    const card = mount(`
      <h2 id="setupTitle" style="margin:0 0 4px">Pick your league</h2>
      <p class="faint" style="margin:0 0 12px">${escapeHtml(who)}'s ${escapeHtml(season)} leagues</p>
      <div style="max-height:380px; overflow-y:auto; display:flex; flex-direction:column; gap:4px">
        ${leagues.map(lg => {
          const lid = String(lg.league_id || '');
          const name = escapeHtml(lg.name || `League ${lid.slice(0, 6)}…`);
          const line = `${String(lg.total_rosters || '?')} teams · ${escapeHtml(String(lg.season || ''))}${lg.status ? ` · ${escapeHtml(lg.status)}` : ''}`;
          return `<div role="option" tabindex="0" data-lid="${escapeAttr(lid)}" class="search-item" style="padding:10px 12px; border-radius:8px; cursor:pointer"><div style="font-weight:700; margin-bottom:2px">${name}</div><div class="faint mono" style="font-size:11px">${line}</div></div>`;
        }).join('')}
      </div>
      <div id="setupResult" aria-live="polite" style="margin-top:8px"></div>
      <div class="row" style="gap:8px; margin-top:16px; justify-content:flex-end">
        <button class="btn btn-ghost btn-sm" id="setupBack">← Back</button>
        <button class="btn btn-ghost btn-sm" id="setupClose">Close</button>
      </div>
    `);

    card.querySelector('#setupBack').addEventListener('click', renderStep1);
    const resultEl = card.querySelector('#setupResult');
    card.querySelectorAll('[data-lid]').forEach(el => {
      const activate = async () => {
        const lid = el.getAttribute('data-lid');
        if (!lid) return;
        resultEl.innerHTML = `<div class="faint">Fetching league details…</div>`;
        const info = await fetchDraftInfo(lid);
        if (!info || !info.league_id) {
          resultEl.innerHTML = `<div class="alert alert-bad">Couldn't fetch details. Try again.</div>`;
          return;
        }
        renderConfirm(lid, info);
      };
      el.addEventListener('click', activate);
      el.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activate(); }
      });
    });
  };

  const renderConfirm = (id, info) => {
    const card = mount(`
      <h2 id="setupTitle" style="margin:0 0 4px">${escapeHtml(info.league_name || 'Unnamed league')}</h2>
      <p class="faint" style="margin:0 0 12px">${escapeHtml(String(info.total_rosters || '?'))} teams · season ${escapeHtml(String(info.season || '?'))} ${draftBadge(info.draft_type)}</p>
      <label class="faint" for="setupDraftType" style="display:block; margin-bottom:4px">Draft type <span class="faint">(auto-detected — override only if wrong)</span></label>
      <select id="setupDraftType" class="team-select-dropdown" style="width:100%; margin-bottom:16px">
        <option value="auto" ${getDraftTypeOverride() === 'auto' ? 'selected' : ''}>Auto (${escapeHtml(info.draft_type)})</option>
        <option value="snake" ${getDraftTypeOverride() === 'snake' ? 'selected' : ''}>Snake</option>
        <option value="auction" ${getDraftTypeOverride() === 'auction' ? 'selected' : ''}>Auction</option>
      </select>
      <div class="row" style="gap:8px; justify-content:flex-end">
        <button class="btn btn-ghost btn-sm" id="setupBack">← Back</button>
        <button class="btn btn-primary" id="setupSave">Use this league</button>
      </div>
      <div id="setupDataCheck"></div>
    `);

    card.querySelector('#setupBack').addEventListener('click', renderStep1);
    card.querySelector('#setupSave').addEventListener('click', async () => {
      setDraftTypeOverride(card.querySelector('#setupDraftType').value);
      setActiveLeague(id);
      addKnownLeague(id, info.league_name, info.season);
      const checkEl = card.querySelector('#setupDataCheck');
      checkEl.innerHTML = `<div class="faint" style="margin-top:8px">Checking synced data…</div>`;
      const ready = await fetchReady().catch(() => null);
      if (ready) {
        close(true);
        return;
      }

      const renderSyncState = (statusHtml) => {
        checkEl.innerHTML = `
          <div class="alert alert-info" style="margin-top:12px">
            <div><strong>Sync League Data</strong></div>
            <div class="faint" style="margin-top:4px">This league is set up. Click below to pull settings, rosters, and matchups from Sleeper directly into your local database.</div>
            <div id="syncProgressArea" style="margin-top:10px">${statusHtml}</div>
          </div>`;
      };

      renderSyncState(`<button class="btn btn-primary" id="setupSyncBtn">Sync League Data Now</button>`);

      const bindSyncBtn = () => {
        const syncBtn = card.querySelector('#setupSyncBtn');
        if (!syncBtn) return;
        syncBtn.addEventListener('click', async () => {
          syncBtn.disabled = true;
          syncBtn.textContent = 'Starting sync…';
          const progress = card.querySelector('#syncProgressArea');
          try {
            await triggerRefresh(id);
            if (progress) progress.innerHTML = `<div class="faint" style="display:flex; align-items:center; gap:8px"><span class="spinner" style="width:14px; height:14px; border:2px solid var(--border); border-top-color: var(--amber); border-radius:50%; animation:spin 0.8s linear infinite"></span> Fetching Sleeper settings, rosters &amp; matchups…</div>`;

            // Poll fetchReady until local DB is populated
            let attempts = 0;
            const poll = setInterval(async () => {
              attempts++;
              const isReady = await fetchReady().catch(() => null);
              if (isReady || attempts >= 15) {
                clearInterval(poll);
                close(true);
              }
            }, 2000);
          } catch (err) {
            if (progress) {
              progress.innerHTML = `
                <div class="alert alert-bad" style="margin-bottom:8px">Model backend unreachable or busy (${escapeHtml(err.message || 'connection failed')}). Make sure backend is running.</div>
                <button class="btn btn-primary btn-sm" id="setupSyncBtn">Retry Sync</button>
                <button class="btn btn-ghost btn-sm" id="setupDoneBtn" style="margin-left:8px">Done (sync later)</button>`;
              bindSyncBtn();
              const doneBtn = card.querySelector('#setupDoneBtn');
              if (doneBtn) doneBtn.addEventListener('click', () => close(true));
            }
          }
        });
      };
      bindSyncBtn();
    });
  };

  renderStep1();
}
