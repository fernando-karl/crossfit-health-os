// FAB + bottom sheet wiring.
// The FAB toggles the sheet. Backdrop click + Escape close it. Sheet items
// are plain links — page-specific handlers (e.g. opening the recovery modal
// on the dashboard) read the URL fragment after navigation.
(function () {
   const fab      = document.getElementById('chos-fab-btn');
   const sheet    = document.getElementById('chos-sheet');
   const backdrop = document.getElementById('chos-sheet-backdrop');
   if (!fab || !sheet || !backdrop) return;

   function open() {
      sheet.hidden = false;
      // Force reflow so the transition triggers.
      sheet.offsetHeight; // eslint-disable-line no-unused-expressions
      sheet.classList.add('is-open');
      backdrop.classList.add('is-open');
      document.body.style.overflow = 'hidden';
   }
   function close() {
      sheet.classList.remove('is-open');
      backdrop.classList.remove('is-open');
      document.body.style.overflow = '';
      // Wait for the transition to finish before re-hiding so a11y tools
      // don't see the sheet flicker.
      setTimeout(() => { sheet.hidden = true; }, 250);
   }

   fab.addEventListener('click', (e) => {
      const direct = fab.dataset.directAction;
      if (direct === 'checkin' && typeof window.openRecoveryModal === 'function') {
         e.preventDefault();
         e.stopImmediatePropagation();
         window.openRecoveryModal();
         return;
      }
      if (direct === 'train') {
         e.preventDefault();
         e.stopImmediatePropagation();
         if (window.CHOS && CHOS.trainNow) {
            CHOS.trainNow.start({ trigger: fab });
         } else if (typeof window.startWorkout === 'function') {
            window.startWorkout();
         }
         return;
      }
      if (direct === 'generate' && typeof window.generateWorkout === 'function') {
         e.preventDefault();
         e.stopImmediatePropagation();
         window.generateWorkout();
         return;
      }
      sheet.classList.contains('is-open') ? close() : open();
   });
   backdrop.addEventListener('click', close);
   document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && sheet.classList.contains('is-open')) close();
   });
   // Tapping any sheet action navigates; close before navigation so the
   // sheet animation doesn't show when the user comes back via Back.
   sheet.querySelectorAll('[data-quick-action]').forEach(el => {
      el.addEventListener('click', () => close());
   });
})();

// Page-level hash handlers — when a quick action lands on a page with #hash,
// the page can read window.location.hash and trigger the right modal.
// Dashboard handles #log-recovery; nutrition handles #meal-photo;
// workouts handles #add-pr. (Each is wired in the corresponding template's
// own script block.)
