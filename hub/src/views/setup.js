// hub/src/views/setup.js — league setup + switcher modal.
// The only two things a user ever types: league ID (or pasted Sleeper URL)
// and optionally a draft-type override. Everything else (name, teams,
// season, draft type, scoring, rosters) is fetched from Sleeper per league.
import { fetchDraftInfo, fetchMeta, fetchReady, setActiveLeague, triggerRefresh } from '../api.js';
import { getLeagueId, setDraftTypeOverride, getDraftTypeOverride, parseLeagueInput, isValidLeagueId } from '../lib/league.js';
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
  const close = (saved) => {
    container.innerHTML = '';
    try { if (triggerEl && triggerEl.focus) triggerEl.focus(); } catch (_) {}
    if (typeof onDone === 'function') onDone(saved);
  };

  const meta = await fetchMeta().catch(() => null);
  const configured = (meta && meta.configuredLeagues) || [];
  const current = getLeagueId();

  const leagueOptions = configured.length
    ? configured.map(l => {
        const id = String(l.league_id || '');
        if (!id) return '';
        const sel = id === current ? 'selected' : '';
        const label = `${l.league_name || 'League'} (${id.slice(0, 6)}…)`;
        return `<option value="${escapeAttr(id)}" ${sel}>${escapeHtml(label)}</option>`;
      }).join('')
    : '';

  container.innerHTML = overlayHtml(`
    <h2 id="setupTitle" style="margin:0 0 4px">Fantasy league setup</h2>
    <p class="faint" style="margin:0 0 16px">Two things, then everything else comes from Sleeper automatically.</p>
    ${configured.length ? `
    <label class="faint" for="setupExisting" style="display:block; margin-bottom:4px">Synced leagues on this machine</label>
    <div class="row" style="gap:8px; margin-bottom:16px">
      <select id="setupExisting" class="team-select-dropdown" style="flex:1">${leagueOptions}</select>
      <button class="btn btn-ghost btn-sm" id="setupUseExisting">Use</button>
    </div>` : ''}
    <label class="faint" for="setupInput" style="display:block; margin-bottom:4px">1 · Sleeper league ID <span class="faint">(or paste your league URL)</span></label>
    <div class="row" style="gap:8px; margin-bottom:12px">
      <input id="setupInput" class="search-top" style="flex:1; border:1px solid var(--border); border-radius:8px; padding:8px 10px" placeholder="e.g. 123456789012345678" inputmode="numeric" value="${escapeAttr(current)}" />
      <button class="btn btn-primary btn-sm" id="setupValidate">Look up</button>
    </div>
    <div id="setupResult" aria-live="polite"></div>
    <div class="row" style="gap:8px; margin-top:16px; justify-content:flex-end">
      <button class="btn btn-ghost btn-sm" id="setupClose">Close</button>
    </div>
  `);

  const card = container.querySelector('#setupCard');
  const release = trapFocus(card, triggerEl, () => close(false));
  const resultEl = container.querySelector('#setupResult');

  const cleanup = () => { try { release(); } catch (_) {} };
  const origClose = close;

  container.querySelector('#setupClose').addEventListener('click', () => { cleanup(); origClose(false); });
  container.querySelector('#setupBackdrop').addEventListener('click', (e) => {
    if (e.target.id === 'setupBackdrop') { cleanup(); origClose(false); }
  });
  const useExisting = container.querySelector('#setupUseExisting');
  if (useExisting) {
    useExisting.addEventListener('click', () => {
      const id = container.querySelector('#setupExisting').value;
      if (!isValidLeagueId(id)) return;
      setActiveLeague(id);
      cleanup(); origClose(true);
    });
  }

  container.querySelector('#setupValidate').addEventListener('click', async () => {
    const raw = container.querySelector('#setupInput').value;
    const id = parseLeagueInput(raw);
    if (!isValidLeagueId(id)) {
      resultEl.innerHTML = `<div class="alert alert-bad">That doesn't look like a Sleeper league ID — paste the digits from your league URL (sleeper.app/leagues/…).</div>`;
      return;
    }
    resultEl.innerHTML = `<div class="faint">Looking up league ${escapeHtml(id)} on Sleeper…</div>`;
    const info = await fetchDraftInfo(id);
    if (!info || !info.league_id) {
      resultEl.innerHTML = `<div class="alert alert-bad">Couldn't reach Sleeper for that ID. Check the digits and your connection, then try again.</div>`;
      return;
    }
    const override = getDraftTypeOverride();
    resultEl.innerHTML = `
      <div class="card" style="padding:12px; margin-top:4px">
        <div style="font-weight:700">${escapeHtml(info.league_name || 'Unnamed league')}</div>
        <div class="faint mono" style="font-size:11px; margin:4px 0 8px">${escapeHtml(String(info.total_rosters || '?'))} teams · season ${escapeHtml(String(info.season || '?'))} ${draftBadge(info.draft_type)}</div>
        <label class="faint" for="setupDraftType" style="display:block; margin-bottom:4px">2 · Draft type <span class="faint">(auto-detected — override only if wrong)</span></label>
        <select id="setupDraftType" class="team-select-dropdown" style="width:100%; margin-bottom:12px">
          <option value="auto" ${override === 'auto' ? 'selected' : ''}>Auto (${escapeHtml(info.draft_type)})</option>
          <option value="snake" ${override === 'snake' ? 'selected' : ''}>Snake</option>
          <option value="auction" ${override === 'auction' ? 'selected' : ''}>Auction</option>
        </select>
        <div class="row" style="gap:8px; justify-content:flex-end">
          <button class="btn btn-primary" id="setupSave">Use this league</button>
        </div>
        <div id="setupDataCheck"></div>
      </div>`;
      container.querySelector('#setupSave').addEventListener('click', async () => {
        const dt = container.querySelector('#setupDraftType').value;
        setDraftTypeOverride(dt);
        setActiveLeague(id);
        const checkEl = container.querySelector('#setupDataCheck');
        checkEl.innerHTML = `<div class="faint" style="margin-top:8px">Checking synced data…</div>`;
        const ready = await fetchReady().catch(() => null);
        if (ready) {
          cleanup(); origClose(true);
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
          const syncBtn = container.querySelector('#setupSyncBtn');
          if (!syncBtn) return;
          syncBtn.addEventListener('click', async () => {
            syncBtn.disabled = true;
            syncBtn.textContent = 'Starting sync…';
            const progress = container.querySelector('#syncProgressArea');
            try {
              await triggerRefresh(id);
              if (progress) progress.innerHTML = `<div class="faint" style="display:flex; align-items:center; gap:8px"><span class="spinner" style="width:14px; height:14px; border:2px solid var(--border); border-top-color:var(--amber); border-radius:50%; animation:spin 0.8s linear infinite"></span> Fetching Sleeper settings, rosters &amp; matchups…</div>`;

              // Poll fetchReady until local DB is populated
              let attempts = 0;
              const poll = setInterval(async () => {
                attempts++;
                const isReady = await fetchReady().catch(() => null);
                if (isReady || attempts >= 15) {
                  clearInterval(poll);
                  cleanup(); origClose(true);
                }
              }, 2000);
            } catch (err) {
              if (progress) {
                progress.innerHTML = `
                  <div class="alert alert-bad" style="margin-bottom:8px">Model backend unreachable or busy (${escapeHtml(err.message || 'connection failed')}). Make sure backend is running.</div>
                  <button class="btn btn-primary btn-sm" id="setupSyncBtn">Retry Sync</button>
                  <button class="btn btn-ghost btn-sm" id="setupDoneBtn" style="margin-left:8px">Done (sync later)</button>`;
                bindSyncBtn();
                const doneBtn = container.querySelector('#setupDoneBtn');
                if (doneBtn) doneBtn.addEventListener('click', () => { cleanup(); origClose(true); });
              }
            }
          });
        };
        bindSyncBtn();
      });
    });
  }
