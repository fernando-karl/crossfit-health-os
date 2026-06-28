// Activity rings — Apple Fitness-style trio.
// Three concentric SVG rings: training, recovery, nutrition. Each ring is a
// circle whose stroke-dashoffset goes from full circumference (= 0%) to 0
// (= 100%). The component is rendered into a container by ID; the data is
// fetched lazily from existing API endpoints so we don't need a new
// aggregator route.
(function () {
   const RADII = [50, 38, 26];   // outer → inner radius (px in 120x120 viewBox)
   const CENTER = 60;

   function ringSvg(values) {
      // values = [{ class, pct }] in outer→inner order.
      const parts = values.map((v, i) => {
         const r = RADII[i];
         const c = 2 * Math.PI * r;
         const offset = c * (1 - Math.max(0, Math.min(1, v.pct)));
         return `
            <g class="${v.cls}">
              <circle class="track" cx="${CENTER}" cy="${CENTER}" r="${r}"></circle>
              <circle class="fill"  cx="${CENTER}" cy="${CENTER}" r="${r}"
                      stroke-dasharray="${c.toFixed(2)}"
                      stroke-dashoffset="${offset.toFixed(2)}"></circle>
            </g>`;
      }).join('');
      return `<svg class="chos-rings" viewBox="0 0 120 120" aria-hidden="true">${parts}</svg>`;
   }

   function isToday(isoDate) {
      if (!isoDate) return false;
      const d = new Date(isoDate);
      const now = new Date();
      return d.getFullYear() === now.getFullYear()
          && d.getMonth() === now.getMonth()
          && d.getDate() === now.getDate();
   }

   async function fetchRingsData() {
      // Run the three lookups in parallel — failures degrade to 0%.
      const [todayWorkout, latestRecovery, macros] = await Promise.all([
         CHOS.api.get('/api/v1/training/today').then(r => r).catch(() => null),
         CHOS.api.get('/api/v1/health/recovery/latest').then(r => r).catch(() => null),
         CHOS.api.get('/api/v1/nutrition/macros/summary').then(r => r).catch(() => null),
      ]);

      // Training: ring tracks COMPLETION, not planning. Showing 50% when a
      // workout exists but hasn't been done was misleading — users saw
      // "Train 50%" before they touched the workout. The "Ready" badge on
      // the workout card already conveys that one is planned.
      // 100% iff today's workout has been completed; 0% otherwise.
      let trainPct = 0;
      if (todayWorkout && todayWorkout.workout && todayWorkout.workout.completed_at) {
         trainPct = 1;
      }

      // Recovery: 100% if a record exists for today.
      let recoveryPct = 0;
      if (latestRecovery && isToday(latestRecovery.date)) recoveryPct = 1;

      // Nutrition: today's calories vs the user's configured target.
      let nutritionPct = 0;
      if (macros && macros.calories) {
         const targetCals = (macros.targets && macros.targets.calories) || 2000;
         nutritionPct = Math.min(1, macros.calories / targetCals);
      }

      return { trainPct, recoveryPct, nutritionPct };
   }

   function render(container, data) {
      const t = window.t || ((k) => k);
      const html = `
         <div class="d-flex align-items-center gap-4">
            ${ringSvg([
               { cls: 'ring-train',     pct: data.trainPct     },
               { cls: 'ring-recovery',  pct: data.recoveryPct  },
               { cls: 'ring-nutrition', pct: data.nutritionPct },
            ])}
            <div class="chos-rings-legend d-flex flex-column gap-2">
               <div class="legend-item"><span class="legend-dot" style="background: var(--cat-cardio);"></span>
                  <span>${t('rings.train')}</span>
                  <span class="text-secondary num ms-auto">${Math.round(data.trainPct * 100)}%</span>
               </div>
               <div class="legend-item"><span class="legend-dot" style="background: var(--cat-recovery);"></span>
                  <span>${t('rings.recovery')}</span>
                  <span class="text-secondary num ms-auto">${Math.round(data.recoveryPct * 100)}%</span>
               </div>
               <div class="legend-item"><span class="legend-dot" style="background: var(--cat-nutrition);"></span>
                  <span>${t('rings.nutrition')}</span>
                  <span class="text-secondary num ms-auto">${Math.round(data.nutritionPct * 100)}%</span>
               </div>
            </div>
         </div>`;
      container.innerHTML = html;
   }

   async function init(selector) {
      const container = document.querySelector(selector);
      if (!container) return;
      try {
         const data = await fetchRingsData();
         render(container, data);
      } catch (e) {
         // Silent fallback — show 0/0/0 rings rather than an error state.
         render(container, { trainPct: 0, recoveryPct: 0, nutritionPct: 0 });
      }
   }

   window.CHOS = window.CHOS || {};
   window.CHOS.rings = { init };
})();
