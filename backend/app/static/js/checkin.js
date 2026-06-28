/**
 * Morning check-in UI — readiness ring preview (matches landing demo).
 */
(function () {
   'use strict';

   const RING_C = 2 * Math.PI * 42;

   function tr(key, vars, fb) {
      return (window.t ? window.t(key, vars) : null) || fb || key;
   }

   function estimateReadiness(sleep, energy, stress, soreness) {
      const sleepNorm = Math.min(1, Math.max(0, (sleep - 4) / 5));
      const energyNorm = (energy - 1) / 9;
      const stressNorm = (10 - stress) / 9;
      const sorenessNorm = (10 - soreness) / 9;
      return Math.round(
         (energyNorm * 0.35 + sleepNorm * 0.35 + stressNorm * 0.15 + sorenessNorm * 0.15) * 100
      );
   }

   function setRing($fill, score) {
      if (!$fill.length) return;
      const pct = Math.min(100, Math.max(0, score)) / 100;
      $fill.css('stroke-dashoffset', String(RING_C * (1 - pct)));
   }

   function readinessClass(score) {
      if (score >= 80) return 'high';
      if (score >= 50) return 'medium';
      return 'low';
   }

   function ringDashoffset(score) {
      const pct = Math.min(100, Math.max(0, score)) / 100;
      return String(RING_C * (1 - pct));
   }

   CHOS.checkin = {
      readinessClass,
      ringDashoffset,
      init(opts) {
         opts = opts || {};
         const $modal = $(opts.modal || '#recoveryModal');
         if (!$modal.length) return;

         const $score = $('#checkin-score');
         const $ring = $('#checkin-ring-fill');
         const $time = $('#checkin-time');
         const $source = $('#checkin-source');
         const $hrvMetric = $('#checkin-metric-hrv');
         const $hrvVal = $('#checkin-hrv-value');

         const fields = ['#recovery-sleep', '#recovery-energy', '#recovery-soreness', '#recovery-stress'];

         function updatePreview() {
            const sleep = parseFloat($('#recovery-sleep').val()) || 7;
            const energy = parseInt($('#recovery-energy').val(), 10) || 7;
            const stress = parseInt($('#recovery-stress').val(), 10) || 5;
            const soreness = parseInt($('#recovery-soreness').val(), 10) || 3;
            const score = estimateReadiness(sleep, energy, stress, soreness);
            $score.text(score);
            $score.removeClass('high medium low').addClass(readinessClass(score));
            setRing($ring, score);
            const sleepLabel = sleep % 1 === 0 ? sleep + 'h' : sleep.toFixed(1) + 'h';
            $('#checkin-sleep-preview').text(sleepLabel);
            $('#energy-value-chip').text(energy);
            $('#soreness-value-chip').text(soreness);
            $('#stress-value-chip').text(stress);
         }

         fields.forEach(function (sel) {
            $(sel).on('input change', updatePreview);
         });

         $modal.on('show.bs.modal', function () {
            const now = new Date();
            const locale = window.LOCALE || 'pt-BR';
            $time.text(now.toLocaleTimeString(locale, { hour: '2-digit', minute: '2-digit' }));
            $source.text(tr('dashboard.readiness_card.source_manual', null, 'Manual'));
            updatePreview();

            if (CHOS.auth && CHOS.auth.isAuthenticated()) {
               CHOS.api.get('/api/v1/health/recovery/latest').then(function (rec) {
                  if (rec && rec.hrv_rmssd_ms != null) {
                     $hrvVal.text(rec.hrv_rmssd_ms);
                     $hrvMetric.removeClass('d-none');
                     $('#recovery-hrv').val(rec.hrv_rmssd_ms);
                  } else {
                     $hrvMetric.addClass('d-none');
                  }
                  if (rec) {
                     if (rec.sleep_duration_hours != null) $('#recovery-sleep').val(rec.sleep_duration_hours);
                     if (rec.energy_level != null) $('#recovery-energy').val(rec.energy_level);
                     if (rec.muscle_soreness != null) $('#recovery-soreness').val(rec.muscle_soreness);
                     if (rec.stress_level != null) $('#recovery-stress').val(rec.stress_level);
                     if (rec.resting_heart_rate_bpm != null) $('#recovery-rhr').val(rec.resting_heart_rate_bpm);
                     if (rec.notes) $('#recovery-notes').val(rec.notes);
                     updatePreview();
                  }
               }).catch(function () {
                  $hrvMetric.addClass('d-none');
               });
            }
         });
      }
   };
})();
