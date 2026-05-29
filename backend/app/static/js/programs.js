/**
 * Programs page — generate cfai mesocycles + activate them as macrocycles.
 *
 * Flow:
 *   1. POST /api/v1/programs/generate (heuristic = instant; hybrid_* ~30s)
 *   2. If "Activate immediately" checked → POST /api/v1/programs/{id}/activate
 *   3. Refresh the program history list
 */
(function () {
   'use strict';

   const FORM_ID = '#program-form';
   const SUBMIT_BTN = '#btn-program-submit';
   const LIST_EL = '#programs-list';

   function tr(key, fallback) {
      return (window.t ? window.t(key) : null) || fallback || key;
   }

   function parseCsvList(value) {
      if (!value) return [];
      return value.split(',').map(s => s.trim()).filter(Boolean);
   }

   function parseCsvInts(value) {
      return parseCsvList(value)
         .map(s => parseInt(s, 10))
         .filter(n => Number.isFinite(n));
   }

   function setSubmitting(isSubmitting) {
      const $btn = $(SUBMIT_BTN);
      $btn.prop('disabled', isSubmitting);
      $btn.find('.btn-text').toggleClass('d-none', isSubmitting);
      $btn.find('.btn-spinner').toggleClass('d-none', !isSubmitting);
   }

   function buildPayload() {
      const composer = $('#prog-composer').val();
      const weeks = parseCsvList($('#prog-weeks').val());
      const deload = parseCsvInts($('#prog-deload').val());
      const focus = parseCsvList($('#prog-focus').val());
      const spw = parseInt($('#prog-spw').val(), 10) || 5;
      const startDate = $('#prog-start').val() || null;
      const name = $('#prog-name').val().trim() || null;

      const payload = {
         composer: composer,
         weeks: weeks,
         deload_weeks: deload,
         sessions_per_week: spw,
         primary_focus: focus,
         persist: true
      };
      if (startDate) payload.start_date = startDate;
      if (name) payload.name = name;
      return payload;
   }

   function loadPrograms() {
      CHOS.api.get('/api/v1/programs/')
         .done(function (data) {
            renderPrograms(data || []);
         })
         .fail(function () {
            // Empty state stays
         });
   }

   function renderPrograms(programs) {
      if (!programs.length) {
         $(LIST_EL).html(`
            <div class="chos-empty-state">
               <i class="fas fa-layer-group empty-icon"></i>
               <h5 class="empty-title">${CHOS.escape(tr('programs.empty_title'))}</h5>
               <p class="empty-desc">${CHOS.escape(tr('programs.empty_desc'))}</p>
            </div>
         `);
         return;
      }

      let html = '<div class="row g-3">';
      programs.forEach(function (p) {
         const date = CHOS.format.date(p.created_at);
         const focus = (p.primary_focus || []).map(CHOS.escape).join(', ');
         html += `
            <div class="col-md-6 col-lg-4">
               <div class="chos-card">
                  <div class="card-body">
                     <div class="d-flex justify-content-between align-items-start mb-2">
                        <span class="chos-badge chos-badge-primary text-uppercase">${CHOS.escape(p.composer_used || '')}</span>
                        <span class="text-muted small num">${CHOS.escape(date)}</span>
                     </div>
                     <h5 class="fw-bold mb-1 text-truncate" title="${CHOS.escape(p.name)}">${CHOS.escape(p.name)}</h5>
                     <div class="text-secondary small mb-3">
                        ${CHOS.escape(tr('programs.card_phase'))}: <strong>${CHOS.escape(p.phase)}</strong>
                        · ${p.duration_weeks} ${CHOS.escape(tr('programs.card_weeks'))}
                        · ${(p.duration_weeks || 0) * (p.sessions_per_week || 0)} ${CHOS.escape(tr('programs.card_sessions'))}
                     </div>
                     <div class="text-muted small mb-3" style="min-height: 1.2em;">${focus}</div>
                     <div class="d-flex gap-2">
                        <button class="chos-btn chos-btn-sm chos-btn-primary flex-grow-1"
                                data-action="activate" data-id="${CHOS.escape(p.id)}">
                           <i class="fas fa-bolt me-1"></i>${CHOS.escape(tr('programs.btn_activate'))}
                        </button>
                        <button class="chos-btn chos-btn-sm chos-btn-outline"
                                data-action="view" data-id="${CHOS.escape(p.id)}" data-name="${CHOS.escape(p.name)}">
                           <i class="fas fa-list-ul me-1"></i>${CHOS.escape(tr('programs.btn_view'))}
                        </button>
                     </div>
                  </div>
               </div>
            </div>`;
      });
      html += '</div>';
      $(LIST_EL).html(html);
   }

   function activateProgram(programId) {
      return CHOS.api.post('/api/v1/programs/' + programId + '/activate', {})
         .done(function () {
            CHOS.toast.success(tr('programs.activated_toast'));
         });
   }

   // ============================================
   // Structured Mesocycle renderer
   // ============================================
   // Render the cfai Mesocycle as nested collapsible sections instead of
   // dumping JSON. Hierarchy: Mesocycle → Week → Session → Block → Movements.

   function formatLoad(load) {
      if (!load || !load.type) return '';
      const v = load.value;
      switch (load.type) {
         case 'absolute_kg':  return v + 'kg';
         case 'percent_1rm':  return v + '% ' + (load.reference_lift || '1RM');
         case 'percent_bw':   return v + '% BW';
         case 'rpe':          return 'RPE ' + v;
         case 'ahap':         return 'AHAP';
         case 'bodyweight':   return 'BW';
         default:             return '';
      }
   }

   function renderPrescription(mp) {
      const e = CHOS.escape;
      const name = CHOS.humanize(mp.movement_id || '');
      const parts = [];
      if (mp.reps != null)              parts.push(e(mp.reps) + ' reps');
      if (mp.calories != null)          parts.push(e(mp.calories) + ' cal');
      if (mp.distance_meters != null)   parts.push(e(mp.distance_meters) + 'm');
      if (mp.time_seconds != null)      parts.push(e(mp.time_seconds) + 's');

      const load = mp.load ? formatLoad(mp.load) : '';
      const loadStr = load ? ' <span class="text-secondary num">@ ' + e(load) + '</span>' : '';
      const tempo = mp.tempo ? ' <span class="text-secondary small">tempo ' + e(mp.tempo) + '</span>' : '';
      const pacing = mp.pacing ? ' <span class="text-secondary small">' + e(mp.pacing) + '</span>' : '';
      const notes = mp.notes ? ' <span class="text-secondary fst-italic small">— ' + e(mp.notes) + '</span>' : '';

      const videoIcon = typeof CHOS.movementVideoIcon === 'function'
         ? CHOS.movementVideoIcon(mp.movement_id || '') : '';
      return '<span class="fw-semibold">' + e(name) + '</span>'
           + videoIcon
           + ': <span class="num">' + parts.join(', ') + '</span>'
           + loadStr + tempo + pacing + notes;
   }

   function renderBlock(block) {
      const e = CHOS.escape;
      const type = (block.type || '').replace(/_/g, ' ').toUpperCase();
      const meta = [];
      if (block.format)            meta.push(String(block.format).toUpperCase());
      if (block.duration_minutes)  meta.push(block.duration_minutes + 'min');
      if (block.time_cap_minutes)  meta.push('cap ' + block.time_cap_minutes + 'min');
      if (block.rounds)            meta.push(block.rounds + ' rounds');
      if (block.intensity_rpe)     meta.push('RPE ' + block.intensity_rpe);
      const metaStr = meta.length ? ' · ' + meta.map(e).join(' · ') : '';

      let html = '<div class="mb-3 ps-3" style="border-left: 2px solid var(--color-border);">';
      html += '<div class="small fw-semibold text-secondary mb-1" style="letter-spacing: 0.04em;">'
            + e(type) + '<span class="fw-normal">' + metaStr + '</span></div>';

      if (block.intent) {
         html += '<div class="small fst-italic text-body mb-2">' + e(block.intent) + '</div>';
      }

      if (block.movements && block.movements.length) {
         html += '<ul class="list-unstyled mb-1">';
         block.movements.forEach(function (mp) {
            html += '<li class="small mb-1">' + renderPrescription(mp) + '</li>';
         });
         html += '</ul>';
      }

      const targets = [];
      if (block.target_score) targets.push('Target: ' + e(block.target_score));
      if (block.target_pace)  targets.push('Pace: '   + e(block.target_pace));
      if (targets.length) {
         html += '<div class="small text-secondary">' + targets.join(' · ') + '</div>';
      }

      if (block.coaching_notes) {
         html += '<div class="small text-muted mt-1">' + e(block.coaching_notes) + '</div>';
      }

      html += '</div>';
      return html;
   }

   function renderSession(sess) {
      const e = CHOS.escape;
      const dateStr = sess.date ? CHOS.format.date(sess.date) : '';
      const stimulus = sess.primary_stimulus
         ? '<span class="chos-badge" style="background: var(--surface-sunken); color: var(--color-text-secondary);">'
           + e(String(sess.primary_stimulus).replace(/_/g, ' ')) + '</span>'
         : '';
      const duration = sess.estimated_duration_minutes
         ? '<span class="text-secondary small num"><i class="fas fa-clock me-1"></i>' + sess.estimated_duration_minutes + 'min</span>'
         : '';
      const tmpl = sess.template
         ? '<span class="text-secondary small">' + e(String(sess.template).replace(/_/g, ' ')) + '</span>'
         : '';

      let html = '<div class="mb-3 pb-3" style="border-bottom: 1px solid var(--color-border);">';
      html += '<div class="d-flex flex-wrap align-items-center gap-2 mb-2">';
      html += '<strong>' + e(sess.title || 'Session') + '</strong>';
      if (dateStr) html += '<span class="text-secondary small num">' + e(dateStr) + '</span>';
      html += stimulus + duration + tmpl;
      html += '</div>';

      (sess.blocks || []).forEach(function (b) { html += renderBlock(b); });

      html += '</div>';
      return html;
   }

   function renderMesocycle(meso) {
      if (!meso || !meso.weeks) {
         return '<div class="text-muted fst-italic">No program data.</div>';
      }
      const e = CHOS.escape;
      let html = '';
      const phase = meso.phase || '';
      const weeks = meso.weeks || [];

      // Header
      html += '<div class="d-flex flex-wrap align-items-center gap-2 mb-3">';
      if (phase) {
         html += '<span class="chos-badge chos-badge-primary text-uppercase">' + e(phase) + '</span>';
      }
      html += '<span class="text-secondary small num">' + e(meso.start_date || '')
            + ' · ' + (meso.duration_weeks || weeks.length) + ' '
            + e(tr('programs.card_weeks')) + '</span>';
      html += '</div>';

      if (meso.primary_focus && meso.primary_focus.length) {
         html += '<div class="text-muted small mb-3">'
               + meso.primary_focus.map(e).join(' · ') + '</div>';
      }

      // Weeks — first one open, rest collapsed
      weeks.forEach(function (w, idx) {
         const open = idx === 0 ? ' open' : '';
         const deloadBadge = w.deload
            ? '<span class="chos-badge chos-badge-warning ms-2">DELOAD</span>'
            : '';
         html += '<details class="chos-card mb-3"' + open + '>'
               + '<summary class="d-flex flex-wrap align-items-center gap-2" '
               + 'style="cursor: pointer; padding: var(--space-3); list-style: none;">'
               + '<i class="fas fa-chevron-right me-1 text-secondary" style="transition: transform 0.15s;"></i>'
               + '<strong>Week ' + (w.week_number || idx + 1) + '</strong>'
               + (w.theme ? '<span class="text-secondary small">' + e(w.theme) + '</span>' : '')
               + deloadBadge
               + '<span class="ms-auto text-secondary small num">' + (w.sessions || []).length + ' sessions</span>'
               + '</summary>'
               + '<div class="card-body" style="padding-top: 0;">';
         (w.sessions || []).forEach(function (s) { html += renderSession(s); });
         html += '</div></details>';
      });

      return html;
   }

   function viewProgram(programId, name) {
      $('#program-detail-title').text(name || '—');
      $('#program-detail-body').html('<div class="text-center py-5"><i class="fas fa-spinner fa-spin"></i></div>');
      const modal = new bootstrap.Modal('#programDetailModal');
      modal.show();
      CHOS.api.get('/api/v1/programs/' + programId)
         .done(function (data) {
            $('#program-detail-body').html(renderMesocycle(data.mesocycle));
         })
         .fail(function () {
            $('#program-detail-body').html(
               '<div class="text-danger">'
               + CHOS.escape(tr('common.server_error', 'Failed to load program.'))
               + '</div>'
            );
         });
   }

   function onSubmit(e) {
      e.preventDefault();
      const payload = buildPayload();
      const activate = $('#prog-activate').is(':checked');

      if (!payload.weeks.length) {
         CHOS.toast.error(tr('programs.form.weeks_pattern'));
         return;
      }
      if (!payload.primary_focus.length) {
         CHOS.toast.error(tr('programs.form.primary_focus'));
         return;
      }

      setSubmitting(true);

      CHOS.api.post('/api/v1/programs/generate', payload)
         .done(function (program) {
            CHOS.toast.success(tr('programs.generated_toast'));
            const onDone = function () {
               setSubmitting(false);
               loadPrograms();
            };
            if (activate && program && program.id) {
               activateProgram(program.id).always(onDone);
            } else {
               onDone();
            }
         })
         .fail(function () {
            setSubmitting(false);
         });
   }

   $(document).ready(function () {
      if (!CHOS.auth.requireAuth()) return;
      CHOS.initDashboard && CHOS.initDashboard();

      $(FORM_ID).on('submit', onSubmit);

      // Delegate card actions
      $(LIST_EL).on('click', '[data-action="activate"]', function () {
         const id = $(this).data('id');
         const $btn = $(this);
         $btn.prop('disabled', true);
         activateProgram(id).always(function () {
            $btn.prop('disabled', false);
         });
      });
      $(LIST_EL).on('click', '[data-action="view"]', function () {
         viewProgram($(this).data('id'), $(this).data('name'));
      });

      loadPrograms();
   });
})();
