// hub/src/lib/focusTrap.js — lightweight modal focus trap.
// Cycles focus between first/last focusable elements, closes on Escape,
// returns focus to the trigger on close.

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export function trapFocus(modalEl, triggerEl, onEscape) {
  if (!modalEl) return () => {};
  const previouslyFocused = (triggerEl && typeof triggerEl.focus === 'function')
    ? triggerEl
    : (document.activeElement instanceof HTMLElement ? document.activeElement : null);

  const getFocusable = () =>
    Array.from(modalEl.querySelectorAll(FOCUSABLE_SELECTOR))
      // getClientRects() works for position:fixed (offsetParent is null for fixed).
      .filter((el) => el.getClientRects().length > 0 || el === document.activeElement);

  const ensureTabindex = () => {
    if (!modalEl.hasAttribute('tabindex')) modalEl.setAttribute('tabindex', '-1');
  };

  const focusFirst = () => {
    ensureTabindex();
    const items = getFocusable();
    if (items.length) items[0].focus();
    else modalEl.focus?.();
  };

  const onKey = (e) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      // Escape invokes modal close (not just release) so the dialog DOM is
      // cleared; release() alone would only restore focus and leak the modal.
      if (typeof onEscape === 'function') {
        onEscape();
      } else {
        release();
      }
      return;
    }
    if (e.key !== 'Tab') return;
    const items = getFocusable();
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  };

  document.addEventListener('keydown', onKey, true);
  // Defer focus so the modal is in the DOM and ready.
  requestAnimationFrame(focusFirst);

  function release() {
    document.removeEventListener('keydown', onKey, true);
    if (previouslyFocused && typeof previouslyFocused.focus === 'function') {
      previouslyFocused.focus();
    }
  }

  return release;
}