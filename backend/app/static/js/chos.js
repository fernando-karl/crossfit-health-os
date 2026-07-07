/**
 * CrossFit Health OS - Core Utilities
 * Toast notifications, loading states, auth middleware, API helpers
 */

// JWT validation helper
function isTokenExpired(token) {
    if (!token || token.split('.').length !== 3) return true;
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        if (!payload.exp) return true;
        return Date.now() > payload.exp * 1000;
    } catch {
        return true;
    }
}

const CHOS = {
   
   // ============================================
   // Auth Middleware
   // ============================================
   auth: {
      _refreshing: null,
      _ensuring: null,

      getToken() {
         return localStorage.getItem('access_token');
      },

      getRefreshToken() {
         return localStorage.getItem('refresh_token');
      },

      isTokenExpired(token) {
         return isTokenExpired(token);
      },

      getUser() {
         try {
            return JSON.parse(localStorage.getItem('user') || '{}');
         } catch { return {}; }
      },

      isAuthenticated() {
         const refresh = this.getRefreshToken();
         const token = this.getToken();
         if (refresh && (!token || isTokenExpired(token))) {
            return true;
         }
         if (!token) return false;
         if (isTokenExpired(token)) {
            this.clearStoredAuth();
            return false;
         }
         return true;
      },

      clearStoredAuth() {
         localStorage.removeItem('access_token');
         localStorage.removeItem('user');
         localStorage.removeItem('refresh_token');
      },

      requireAuth() {
         if (!this.isAuthenticated()) {
            window.location.href = '/login';
            return false;
         }
         return true;
      },

      /**
       * Ensure a valid access token is available — refresh silently when needed.
       * Deduplicates concurrent calls. Rejects when no recoverable session exists.
       */
      ensureSession() {
         if (this._ensuring) return this._ensuring;

         const token = this.getToken();
         const refresh = this.getRefreshToken();

         if (!token && !refresh) {
            return $.when(Promise.reject(new Error('No session')));
         }
         if (token && !isTokenExpired(token)) {
            return $.when(Promise.resolve(token));
         }
         if (refresh) {
            this._ensuring = $.when(this.refreshAccessToken()).always(function() {
               CHOS.auth._ensuring = null;
            });
            return this._ensuring;
         }
         this.clearStoredAuth();
         return $.when(Promise.reject(new Error('Session expired')));
      },

      /**
       * Attempt to refresh the access token using the stored refresh token.
       * Returns a promise that resolves with the new access token or rejects.
       * Deduplicates concurrent refresh requests.
       */
      refreshAccessToken() {
         if (this._refreshing) return this._refreshing;

         const refreshToken = this.getRefreshToken();
         if (!refreshToken) {
            return Promise.reject(new Error('No refresh token'));
         }

         this._refreshing = $.ajax({
            url: '/api/v1/auth/refresh',
            type: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({ refresh_token: refreshToken }),
            dataType: 'json'
         }).then(function(response) {
            localStorage.setItem('access_token', response.access_token);
            if (response.refresh_token) {
               localStorage.setItem('refresh_token', response.refresh_token);
            }
            if (response.user) {
               localStorage.setItem('user', JSON.stringify(response.user));
            }
            CHOS.auth._refreshing = null;
            return response.access_token;
         }).fail(function() {
            CHOS.auth._refreshing = null;
            CHOS.auth.clearStoredAuth();
         });

         return this._refreshing;
      },

      logout() {
         const token = this.getToken();
         const refreshToken = this.getRefreshToken();
         const headers = token ? { 'Authorization': 'Bearer ' + token } : {};
         $.ajax({
            url: '/api/v1/auth/logout',
            type: 'POST',
            contentType: 'application/json',
            headers: headers,
            data: JSON.stringify({ refresh_token: refreshToken || null }),
            complete: function() {
               CHOS.auth.clearStoredAuth();
               window.location.href = '/';
            }
         });
      }
   },
   
   // ============================================
   // Toast Notifications
   // ============================================
   toast: {
      _container: null,
      
      _getContainer() {
         if (!this._container) {
            this._container = document.createElement('div');
            this._container.className = 'chos-toast-container';
            document.body.appendChild(this._container);
         }
         return this._container;
      },
      
      show(message, type = 'info', duration = 4000) {
         const container = this._getContainer();
         const icons = {
            success: 'fa-check-circle',
            error: 'fa-exclamation-circle',
            warning: 'fa-exclamation-triangle',
            info: 'fa-info-circle'
         };
         
         const colors = {
            success: 'color: var(--color-success)',
            error: 'color: var(--color-danger)',
            warning: 'color: var(--color-warning)',
            info: 'color: var(--color-primary)'
         };
         
         const toast = document.createElement('div');
         toast.className = 'chos-toast ' + type;
         toast.innerHTML = `
            <i class="fas ${icons[type] || icons.info}" style="${colors[type] || colors.info}; font-size: 1.25rem;"></i>
            <div style="flex: 1;">
               <div style="font-weight: 600; font-size: 0.875rem;">${message}</div>
            </div>
            <button onclick="this.parentElement.remove()" style="background: none; border: none; cursor: pointer; color: var(--color-text-muted); font-size: 1.25rem;">
               <i class="fas fa-times"></i>
            </button>
         `;
         
         container.appendChild(toast);
         
         if (duration > 0) {
            setTimeout(() => {
               toast.style.animation = 'slideOutRight 0.3s ease-in forwards';
               setTimeout(() => toast.remove(), 300);
            }, duration);
         }
         
         return toast;
      },
      
      success(msg) { return this.show(msg, 'success'); },
      error(msg) { return this.show(msg, 'error', 6000); },
      warning(msg) { return this.show(msg, 'warning'); },
      info(msg) { return this.show(msg, 'info'); }
   },
   
   // ============================================
   // Loading States
   // ============================================
   loading: {
      button(btn, loading = true) {
         const $btn = $(btn);
         if (loading) {
            $btn.addClass('loading').prop('disabled', true);
            if (!$btn.find('.btn-spinner').length) {
               $btn.wrapInner('<span class="btn-text"></span>');
               $btn.prepend('<span class="btn-spinner"><i class="fas fa-spinner fa-spin"></i></span> ');
            }
         } else {
            $btn.removeClass('loading').prop('disabled', false);
         }
      },
      
      skeleton(container, count = 3) {
         const $container = $(container);
         let html = '';
         for (let i = 0; i < count; i++) {
            html += `
               <div class="chos-card mb-3">
                  <div class="card-body">
                     <div class="chos-skeleton chos-skeleton-title"></div>
                     <div class="chos-skeleton chos-skeleton-text" style="width: 80%;"></div>
                     <div class="chos-skeleton chos-skeleton-text" style="width: 60%;"></div>
                  </div>
               </div>
            `;
         }
         $container.html(html);
      },
      
      spinner(container) {
         $(container).html(`
            <div class="text-center py-5">
               <div class="spinner-border text-primary" role="status">
                  <span class="visually-hidden">Loading...</span>
               </div>
               <p class="text-muted mt-3">Loading...</p>
            </div>
         `);
      }
   },
   
   // ============================================
   // API Helper
   // ============================================
   api: {
      _baseHeaders() {
         const headers = { 'Content-Type': 'application/json' };
         const token = CHOS.auth.getToken();
         if (token) headers['Authorization'] = 'Bearer ' + token;
         return headers;
      },

      /**
       * Make an API request with automatic token refresh on 401.
       * If a 401 is received and a refresh token exists, attempts to
       * refresh the access token and retry the original request once.
       */
      _request(method, url, data) {
         const self = this;
         const doRequest = () => {
            const opts = {
               url: url,
               type: method,
               headers: self._baseHeaders(),
               dataType: 'json'
            };
            if (data !== undefined) {
               opts.data = JSON.stringify(data);
            }
            return $.ajax(opts);
         };

         return doRequest().then(null, function(xhr) {
            // On 401, try to refresh the token and retry once
            if (xhr.status === 401 && CHOS.auth.getRefreshToken()) {
               return CHOS.auth.refreshAccessToken().then(function() {
                  return doRequest();
               }).then(null, function() {
                  CHOS.toast.error((window.t ? t('common.session_expired') : 'Session expired. Please login again.'));
                  setTimeout(() => { window.location.href = '/login'; }, 1500);
                  return $.Deferred().reject(xhr);
               });
            }
            // For non-401 errors, use standard handler
            self._handleNon401Error(xhr);
            return $.Deferred().reject(xhr);
         });
      },

      get(url) {
         return this._request('GET', url);
      },

      post(url, data) {
         return this._request('POST', url, data);
      },

      patch(url, data) {
         return this._request('PATCH', url, data);
      },

      put(url, data) {
         return this._request('PUT', url, data);
      },

      delete(url) {
         return this._request('DELETE', url);
      },

      _handleNon401Error(xhr) {
         if (xhr.status === 422) {
            const errors = xhr.responseJSON?.detail;
            if (Array.isArray(errors)) {
               errors.forEach(e => CHOS.toast.error(e.msg));
            } else {
               CHOS.toast.error((window.t ? t('common.validation_error') : 'Validation error'));
            }
         } else if (xhr.status === 402) {
            // Trial expired or subscription not active. Backend sends a
            // structured detail; we render a sticky modal pointing to
            // /dashboard/billing. Built once on first 402 and reused.
            CHOS.billing.showUpgradeModal(xhr);
         } else if (xhr.status >= 500) {
            CHOS.toast.error((window.t ? t('common.server_error') : 'Server error. Please try again later.'));
         }
      }
   },

   /**
    * Build recovery payload for POST /api/v1/training/generate.
    * Field names match WorkoutGenerationRequest on the backend.
    */
   async buildRecoveryGeneratePayload() {
      const defaults = {
         readiness_score: 75,
         hrv_rmssd_ms: 60,
         sleep_duration_hours: 7.5,
         muscle_soreness: 3,
      };
      try {
         const recovery = await CHOS.api.get('/api/v1/health/recovery/latest');
         if (recovery && CHOS.recoveryIsToday(recovery)) {
            return {
               readiness_score: recovery.readiness_score ?? defaults.readiness_score,
               hrv_rmssd_ms: recovery.hrv_rmssd_ms ?? defaults.hrv_rmssd_ms,
               sleep_duration_hours: recovery.sleep_duration_hours ?? defaults.sleep_duration_hours,
               muscle_soreness: recovery.muscle_soreness ?? defaults.muscle_soreness,
               stress_level: recovery.stress_level ?? undefined,
               sleep_quality_score: recovery.sleep_quality_score ?? undefined,
            };
         }
      } catch (e) {
         /* use defaults */
      }
      return defaults;
   },
   
   // ============================================
   // Movement video lookup (cheap dynamic search)
   // ============================================
   // Build a YouTube search URL biased toward Squat University + CrossFit
   // so users can quickly understand a movement they don't know. We don't
   // curate per-movement videos — just hand the user a good search.
   movementVideoUrl(movement) {
      if (!movement) return null;
      const human = CHOS.humanize(movement);
      // Append biasing keywords so results lean toward the two channels
      // the user named. YouTube's relevance ranking handles the rest.
      const q = `${human} technique squat university crossfit`;
      return `https://www.youtube.com/results?search_query=${encodeURIComponent(q)}`;
   },

   // Render a small "watch video" icon link. Returns an HTML string —
   // callers paste it inline next to a movement name.
   movementVideoIcon(movement) {
      const url = CHOS.movementVideoUrl(movement);
      if (!url) return '';
      const label = (window.t ? t('common.actions.watch_video') : 'Watch tutorial');
      const safeLabel = CHOS.escape(label);
      return `<a href="${url}" target="_blank" rel="noopener noreferrer"
                 class="text-secondary ms-1"
                 title="${safeLabel}" aria-label="${safeLabel}"
                 onclick="event.stopPropagation()"
                 style="text-decoration: none;">
                <i class="fab fa-youtube" style="font-size: 0.85em;"></i>
              </a>`;
   },

   // ============================================
   // Cross-page workout handoff
   // ============================================
   // Stash a workout/template in sessionStorage and navigate to the workouts
   // page so it can auto-open the tracking modal without a second round-trip.
   // Used by:
   //   - dashboard Start button (today workout)
   //   - schedule day drawer Start button (planned session template)
   // The workouts page reads `chos-quick-workout` when ?quick=1 is present.
   startWorkoutFromTemplate(template, opts) {
      if (!template) return false;
      opts = opts || {};
      const movements = (template.movements && template.movements.length)
         ? template.movements
         : (template.adjusted_movements || []);
      const templateId = template.id || opts.template_id || null;
      const response = {
         planned_session_id: opts.planned_session_id || template.planned_session_id || null,
         template: {
            id: templateId,
            name: template.name,
            workout_type: template.workout_type || 'mixed',
            duration_minutes: template.duration_minutes || 60,
            description: template.description || '',
            target_stimulus: template.target_stimulus || '',
            warm_up: template.warm_up || template.warmup || '',
            equipment_required: template.equipment_required || [],
            movements: movements
         },
         adjusted_movements: movements,
         recommendation: opts.recommendation || template.description || template.target_stimulus || ''
      };
      try {
         sessionStorage.setItem('chos-quick-workout', JSON.stringify(response));
      } catch (_) { /* storage might be disabled */ }
      if (window.location.pathname === '/dashboard/workouts'
          && typeof window.openWorkoutTracking === 'function') {
         window.openWorkoutTracking(response);
         return true;
      }
      window.location.href = '/dashboard/workouts?quick=1';
      return true;
   },

   /** Local calendar date as YYYY-MM-DD (not UTC). */
   todayLocalIso() {
      const d = new Date();
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, '0');
      const day = String(d.getDate()).padStart(2, '0');
      return `${y}-${m}-${day}`;
   },

   /** True when a recovery row is dated today (local calendar). */
   recoveryIsToday(recovery) {
      if (!recovery || recovery.date == null || recovery.date === '') return false;
      return String(recovery.date).slice(0, 10) === CHOS.todayLocalIso();
   },

   // Global "Train now" — next planned session from active macrocycle.
   trainNow: {
      CACHE_MS: 60000,
      _cache: null,
      _cacheAt: 0,
      _templateCache: {},
      _navBound: false,

      todayIso() {
         return CHOS.todayLocalIso();
      },

      isQuickStartable(s) {
         return !!(s && s.generated_template_id && !s.completed && s.status !== 'skipped');
      },

      compareSessions(a, b) {
         if (a.date !== b.date) return a.date < b.date ? -1 : 1;
         const orderA = a.order_in_day || 0;
         const orderB = b.order_in_day || 0;
         if (orderA !== orderB) return orderA - orderB;
         const timeA = a.start_time || '';
         const timeB = b.start_time || '';
         return timeA.localeCompare(timeB);
      },

      pickNext(sessions, weekEnd) {
         const todayIso = this.todayIso();
         const candidates = (sessions || [])
            .filter(s => this.isQuickStartable(s))
            .filter(s => !weekEnd || s.date <= weekEnd)
            .sort((a, b) => this.compareSessions(a, b));
         if (!candidates.length) return null;

         const todayFirst = candidates.find(s => s.date === todayIso);
         if (todayFirst) return todayFirst;

         const upcoming = candidates.find(s => s.date >= todayIso);
         return upcoming || candidates[0];
      },

      sessionLabel(session) {
         if (!session) return '';
         const tr = window.t || (k => k);
         if (session.focus && CHOS.stimulus) {
            return CHOS.stimulus.displayLabel(session.focus);
         }
         if (session.workout_type) {
            const key = 'schedule.workout_type.' + session.workout_type;
            const hit = tr(key);
            return hit !== key ? hit : CHOS.humanize(session.workout_type);
         }
         return tr('nav.train_now.label');
      },

      invalidate() {
         this._cache = null;
         this._cacheAt = 0;
      },

      updateFromMicro(micro) {
         if (!micro) {
            this.invalidate();
            this.refreshNav();
            return;
         }
         this._cache = this.pickNext(micro.sessions || [], micro.end_date);
         this._cacheAt = Date.now();
         this.refreshNav();
      },

      async fetchNextSession(force) {
         const now = Date.now();
         if (!force && this._cache && (now - this._cacheAt) < this.CACHE_MS) {
            return this._cache;
         }
         try {
            const macro = await CHOS.api.get('/api/v1/schedule/macrocycles/active');
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            let micro = (macro.microcycles || []).find(m => {
               const s = new Date(m.start_date + 'T00:00:00');
               const e = new Date(m.end_date + 'T23:59:59');
               return today >= s && today <= e;
            });
            if (!micro && macro.microcycles && macro.microcycles.length) {
               micro = macro.microcycles[macro.microcycles.length - 1];
            }
            if (!micro) {
               this._cache = null;
               this._cacheAt = now;
               return null;
            }
            const microData = await CHOS.api.get('/api/v1/schedule/microcycles/' + micro.id);
            const next = this.pickNext(microData.sessions || [], microData.end_date);
            this._cache = next;
            this._cacheAt = now;
            return next;
         } catch (xhr) {
            if (xhr && xhr.status === 404) {
               this._cache = null;
               this._cacheAt = Date.now();
               return null;
            }
            throw xhr;
         }
      },

      async startSession(session, triggerEl) {
         if (!session || !session.generated_template_id) return false;
         const btn = triggerEl;
         const done = () => {
            if (btn) {
               btn.classList.remove('is-loading');
               btn.disabled = false;
            }
         };
         if (btn) {
            btn.classList.add('is-loading');
            btn.disabled = true;
         }
         const templateId = session.generated_template_id;
         let template = this._templateCache[templateId];
         if (!template) {
            try {
               template = await CHOS.api.get('/api/v1/training/templates/' + templateId);
               this._templateCache[templateId] = template;
            } catch (_) {
               done();
               CHOS.toast.error((window.t && t('schedule.toast.session_load_error')) || 'Error');
               return false;
            }
         }
         CHOS.startWorkoutFromTemplate(
            Object.assign({}, template, { id: templateId }),
            { planned_session_id: session.id }
         );
         done();
         return true;
      },

      async start(opts) {
         opts = opts || {};
         try {
            const session = await this.fetchNextSession(opts.force);
            if (session) {
               return this.startSession(session, opts.trigger);
            }
         } catch (_) {
            CHOS.toast.error((window.t && t('schedule.toast.session_load_error')) || 'Error');
            return false;
         }
         if (typeof window.startWorkout === 'function') {
            window.startWorkout();
            return true;
         }
         CHOS.toast.info((window.t && t('nav.train_now.none')) || 'No workout');
         window.location.href = '/dashboard/programs';
         return false;
      },

      bindNav() {
         if (this._navBound) return;
         const btn = document.getElementById('nav-train-now');
         if (!btn) return;
         this._navBound = true;
         btn.addEventListener('click', (e) => {
            e.preventDefault();
            this.start({ trigger: btn });
         });
      },

      refreshNav() {
         const item = document.getElementById('nav-train-now-item');
         const btn = document.getElementById('nav-train-now');
         if (!btn || !item) return;
         const session = this._cache;
         if (!session || !this.isQuickStartable(session)) {
            item.classList.add('d-none');
            return;
         }
         item.classList.remove('d-none');
         const label = this.sessionLabel(session);
         btn.title = label;
         const sub = btn.querySelector('.nav-train-now__sub');
         if (sub) sub.textContent = label;
      },

      init() {
         this.bindNav();
         if (!CHOS.auth.getToken()) return;
         this.fetchNextSession()
            .then(() => this.refreshNav())
            .catch(() => {
               const item = document.getElementById('nav-train-now-item');
               if (item) item.classList.add('d-none');
            });
      }
   },

   // ============================================
   // Formatters
   // ============================================
   // HTML-escape any value being injected into innerHTML/template strings.
   escape(value) {
      if (value == null) return '';
      const s = String(value);
      return s.replace(/[&<>"']/g, ch => ({
         '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      })[ch]);
   },

   // Convert snake_case identifiers (back_squat) to display form (Back Squat).
   // Backend movement IDs come back as enum-style strings; users shouldn't see
   // the raw form.
   humanize(s) {
      if (!s) return '';
      return String(s)
         .replace(/_/g, ' ')
         .replace(/\b\w/g, c => c.toUpperCase());
   },

   // CFAI primary_stimulus keys — shared by calendar drawer and programs viewer.
   stimulus: {
      FOCUS_CUSTOM: '__custom__',

      TO_WORKOUT_TYPE: {
         strength_max: 'strength',
         strength_volume: 'strength',
         hypertrophy: 'strength',
         power: 'strength',
         aerobic_z2: 'conditioning',
         aerobic_threshold: 'conditioning',
         vo2_max: 'metcon',
         lactic_tolerance: 'metcon',
         alactic_power: 'metcon',
         mixed_modal: 'metcon',
         gymnastic_capacity: 'skill',
         skill_acquisition: 'skill',
         midline_endurance: 'skill',
         recovery: 'conditioning',
      },

      GROUPS: [
         { groupKey: 'schedule.stimulus.group_strength', items: ['strength_max', 'strength_volume', 'hypertrophy', 'power'] },
         { groupKey: 'schedule.stimulus.group_conditioning', items: ['aerobic_z2', 'aerobic_threshold', 'recovery'] },
         { groupKey: 'schedule.stimulus.group_metcon', items: ['vo2_max', 'lactic_tolerance', 'alactic_power', 'mixed_modal'] },
         { groupKey: 'schedule.stimulus.group_skill', items: ['gymnastic_capacity', 'skill_acquisition', 'midline_endurance'] },
      ],

      _t(key) {
         const hit = window.t ? window.t(key) : null;
         return hit && hit !== key ? hit : null;
      },

      isKnown(focus) {
         return !!(focus && Object.prototype.hasOwnProperty.call(this.TO_WORKOUT_TYPE, focus));
      },

      label(key) {
         if (!key) return '';
         const i18nKey = 'schedule.stimulus.' + key;
         return this._t(i18nKey) || CHOS.humanize(key);
      },

      displayLabel(focus) {
         if (!focus) return '';
         return this.isKnown(focus) ? this.label(focus) : focus;
      },

      workoutTypeFor(stimulus) {
         return this.TO_WORKOUT_TYPE[stimulus] || 'mixed';
      },

      stimuliForWorkoutType(workoutType) {
         if (!workoutType || workoutType === 'mixed') {
            return Object.keys(this.TO_WORKOUT_TYPE);
         }
         return Object.keys(this.TO_WORKOUT_TYPE).filter(
            key => this.TO_WORKOUT_TYPE[key] === workoutType
         );
      },

      isCompatible(stimulus, workoutType) {
         if (!workoutType || workoutType === 'mixed') return true;
         return this.workoutTypeFor(stimulus) === workoutType;
      },

      catClassForStimulus(stimulus) {
         const wt = this.workoutTypeFor(stimulus);
         return this.catClassForWorkoutType(wt);
      },

      catClassForWorkoutType(workoutType) {
         const map = {
            strength: 'is-strength',
            metcon: 'is-cardio',
            conditioning: 'is-recovery',
            skill: 'is-nutrition',
            mixed: 'is-recovery',
         };
         return map[workoutType] || 'is-recovery';
      },

      buildPickerHtml(focus, workoutType, opts) {
         const o = opts || {};
         const t = window.t || function (k) { return k; };
         const esc = CHOS.escape;
         const allowed = workoutType === 'mixed'
            ? null
            : new Set(this.stimuliForWorkoutType(workoutType));
         const isKnown = this.isKnown(focus);
         const isCustom = !!(focus && !isKnown);
         const customSelected = isCustom;
         let html = '';

         this.GROUPS.forEach(function (g) {
            const chips = g.items
               .filter(function (key) { return !allowed || allowed.has(key); })
               .map(function (key) {
                  const catCls = CHOS.stimulus.catClassForStimulus(key);
                  const sel = isKnown && focus === key ? ' is-selected' : '';
                  return '<button type="button" class="chos-stimulus-chip ' + catCls + sel + '"'
                     + ' data-stimulus="' + esc(key) + '"'
                     + ' aria-pressed="' + (sel ? 'true' : 'false') + '">'
                     + '<span class="chip-dot"></span>' + esc(CHOS.stimulus.label(key))
                     + '</button>';
               })
               .join('');
            if (!chips) return;
            html += '<div class="chos-stimulus-group mb-2">'
               + '<div class="chos-stimulus-group__label small text-secondary fw-medium mb-1">'
               + esc(t(g.groupKey)) + '</div>'
               + '<div class="d-flex flex-wrap gap-2">' + chips + '</div></div>';
         });

         const customSel = customSelected ? ' is-selected' : '';
         html += '<div class="d-flex flex-wrap gap-2 mt-1">'
            + '<button type="button" class="chos-stimulus-chip chos-stimulus-chip--custom' + customSel + '"'
            + ' data-stimulus="' + esc(CHOS.stimulus.FOCUS_CUSTOM) + '"'
            + ' aria-pressed="' + (customSelected ? 'true' : 'false') + '">'
            + '<span class="chip-dot"></span>' + esc(t('schedule.stimulus.custom'))
            + '</button></div>';

         const customHidden = customSelected ? '' : ' d-none';
         const customValue = customSelected ? esc(focus || '') : '';
         const placeholder = esc(o.placeholder || t('schedule.drawer.focus_placeholder'));
         html += '<input type="text" class="chos-input mt-2' + customHidden + '" data-field="focus_custom"'
            + ' value="' + customValue + '" placeholder="' + placeholder + '"'
            + ' aria-label="' + esc(t('schedule.drawer.field_focus')) + '">';

         if (workoutType && workoutType !== 'mixed') {
            html += '<div class="form-text text-secondary small mt-1">'
               + esc(t('schedule.drawer.focus_filtered')) + '</div>';
         }

         return html;
      },

      WORKOUT_TYPES: ['strength', 'metcon', 'skill', 'conditioning', 'mixed'],

      TYPE_ICONS: {
         strength: 'fa-dumbbell',
         metcon: 'fa-fire',
         skill: 'fa-star',
         conditioning: 'fa-heart-pulse',
         mixed: 'fa-layer-group',
      },

      buildWorkoutTypePickerHtml(selectedType) {
         const t = window.t || function (k) { return k; };
         const esc = CHOS.escape;
         const selected = selectedType || 'mixed';
         const self = this;
         return '<div class="d-flex flex-wrap gap-2">' + this.WORKOUT_TYPES.map(function (wt) {
            const catCls = self.catClassForWorkoutType(wt);
            const sel = selected === wt ? ' is-selected' : '';
            const icon = self.TYPE_ICONS[wt] || 'fa-circle';
            return '<button type="button" class="chos-stimulus-chip chos-type-chip ' + catCls + sel + '"'
               + ' data-workout-type="' + esc(wt) + '"'
               + ' aria-pressed="' + (sel ? 'true' : 'false') + '">'
               + '<i class="fas ' + icon + '" style="font-size:0.75rem;opacity:0.85;"></i>'
               + esc(t('schedule.workout_type.' + wt))
               + '</button>';
         }).join('') + '</div>';
      },
   },

   // Session shift picker — calendar drawer.
   shift: {
      SHIFTS: ['morning', 'afternoon', 'evening', 'custom'],

      ICONS: {
         morning: 'fa-sun',
         afternoon: 'fa-cloud-sun',
         evening: 'fa-moon',
         custom: 'fa-clock',
      },

      DEFAULT_TIMES: {
         morning: '06:00',
         afternoon: '14:00',
         evening: '18:00',
      },

      CAT_CLASS: {
         morning: 'is-morning',
         afternoon: 'is-afternoon',
         evening: 'is-evening',
         custom: 'is-custom',
      },

      isValid(shift) {
         return this.SHIFTS.indexOf(shift) !== -1;
      },

      label(shift) {
         if (!this.isValid(shift)) return '';
         const key = 'schedule.shift.' + shift;
         const hit = window.t ? window.t(key) : null;
         return (hit && hit !== key) ? hit : CHOS.humanize(shift);
      },

      buildPickerHtml(selectedShift) {
         const esc = CHOS.escape;
         const selected = this.isValid(selectedShift) ? selectedShift : 'morning';
         const self = this;
         return '<div class="d-flex flex-wrap gap-2">' + this.SHIFTS.map(function (sh) {
            const catCls = self.CAT_CLASS[sh] || '';
            const sel = selected === sh ? ' is-selected' : '';
            const icon = self.ICONS[sh] || 'fa-circle';
            return '<button type="button" class="chos-stimulus-chip chos-shift-chip ' + catCls + sel + '"'
               + ' data-shift="' + esc(sh) + '"'
               + ' aria-pressed="' + (sel ? 'true' : 'false') + '">'
               + '<i class="fas ' + icon + '" style="font-size:0.75rem;opacity:0.85;"></i>'
               + esc(self.label(sh))
               + '</button>';
         }).join('') + '</div>';
      },

      buildGridBadge(session) {
         if (!session) return '';
         const esc = CHOS.escape;
         const shift = this.isValid(session.shift) ? session.shift : '';
         if (!shift) {
            if (session.start_time) {
               return '<span class="chos-session-shift is-custom" title="' + esc(session.start_time.slice(0, 5)) + '">'
                  + '<i class="fas fa-clock"></i><span class="num">' + esc(session.start_time.slice(0, 5)) + '</span></span>';
            }
            return '';
         }
         const cat = this.CAT_CLASS[shift] || '';
         const icon = this.ICONS[shift] || 'fa-clock';
         const fullLabel = this.label(shift);
         const shortLabel = shift === 'custom' && session.start_time
            ? session.start_time.slice(0, 5)
            : fullLabel;
         return '<span class="chos-session-shift ' + cat + '" title="' + esc(fullLabel) + '">'
            + '<i class="fas ' + icon + '"></i>'
            + '<span>' + esc(shortLabel) + '</span></span>';
      },
   },

   // Session duration presets — calendar drawer.
   duration: {
      PRESETS: [45, 60, 75, 90, 120],

      presetsFor(macroDefault) {
         const base = this.PRESETS.slice();
         const d = parseInt(macroDefault, 10) || 60;
         if (d >= 15 && d <= 240 && base.indexOf(d) === -1) {
            return { presets: base.concat([d]).sort(function (a, b) { return a - b; }), macroDefault: d };
         }
         return { presets: base, macroDefault: d };
      },

      buildPickerHtml(selectedMinutes, opts) {
         const o = opts || {};
         const esc = CHOS.escape;
         const t = window.t || function (k) { return k; };
         const presetInfo = this.presetsFor(o.macroDefault);
         const presets = presetInfo.presets;
         const macroDefault = presetInfo.macroDefault;
         const selected = parseInt(selectedMinutes, 10) || macroDefault;
         const isPreset = presets.indexOf(selected) !== -1;
         const macroHint = t('schedule.drawer.duration_macro_hint');
         const chips = presets.map(function (mins) {
            const sel = isPreset && selected === mins ? ' is-selected' : '';
            const isMacro = mins === macroDefault;
            const macroCls = isMacro ? ' chos-duration-chip--macro' : '';
            const macroTitle = isMacro ? ' title="' + esc(macroHint) + '"' : '';
            return '<button type="button" class="chos-stimulus-chip chos-duration-chip' + macroCls + sel + '"'
               + ' data-duration="' + mins + '"' + macroTitle
               + ' aria-pressed="' + (sel ? 'true' : 'false') + '">'
               + (isMacro ? '<i class="fas fa-star" style="font-size:0.55rem;opacity:0.75;"></i>' : '')
               + '<span class="num">' + mins + '</span> min'
               + '</button>';
         }).join('');
         const customSel = !isPreset ? ' is-selected' : '';
         return '<div class="d-flex flex-wrap gap-2 align-items-center mb-2">' + chips
            + '<button type="button" class="chos-stimulus-chip chos-duration-chip chos-duration-chip--custom' + customSel + '"'
            + ' data-duration="custom" aria-pressed="' + (!isPreset ? 'true' : 'false') + '">'
            + '<i class="fas fa-sliders-h" style="font-size:0.75rem;opacity:0.85;"></i>'
            + esc(t('schedule.drawer.duration_custom'))
            + '</button></div>'
            + '<div class="chos-duration-custom' + (isPreset ? ' d-none' : '') + '">'
            + '<div class="position-relative" style="max-width: 8rem;">'
            + '<input type="number" class="chos-input" data-field="duration_minutes" min="15" max="240" step="5"'
            + ' value="' + (isPreset ? '' : esc(String(selected))) + '"'
            + ' aria-label="' + esc(t('schedule.drawer.field_duration')) + '">'
            + '<span class="position-absolute text-secondary small" style="right: 0.875rem; top: 50%; transform: translateY(-50%); pointer-events: none;">min</span>'
            + '</div></div>';
      },
   },

   // Macrocycle create form — duration + training days chips.
   macroForm: {
      DURATION_PRESETS: [30, 45, 60, 90, 120, 180],
      DAYS_OPTIONS: [3, 4, 5, 6, 7],

      buildDurationPickerHtml(selectedMinutes) {
         const esc = CHOS.escape;
         const selected = parseInt(selectedMinutes, 10) || 60;
         return '<div class="d-flex flex-wrap gap-2">' + this.DURATION_PRESETS.map(function (mins) {
            const sel = selected === mins ? ' is-selected' : '';
            return '<button type="button" class="chos-stimulus-chip chos-macro-chip' + sel + '"'
               + ' data-macro-duration="' + mins + '"'
               + ' aria-pressed="' + (sel ? 'true' : 'false') + '">'
               + '<span class="num">' + mins + '</span> min</button>';
         }).join('') + '</div>';
      },

      buildDaysPickerHtml(selectedDays) {
         const esc = CHOS.escape;
         const t = window.t || function (k, p) { return k; };
         const selected = parseInt(selectedDays, 10) || 5;
         return '<div class="d-flex flex-wrap gap-2">' + this.DAYS_OPTIONS.map(function (days) {
            const sel = selected === days ? ' is-selected' : '';
            return '<button type="button" class="chos-stimulus-chip chos-macro-chip' + sel + '"'
               + ' data-macro-days="' + days + '"'
               + ' aria-pressed="' + (sel ? 'true' : 'false') + '">'
               + '<span class="num">' + days + '</span> '
               + esc(t('schedule.modal.days_chip', { n: days }))
               + '</button>';
         }).join('') + '</div>';
      },
   },

   format: {
      date(dateStr) {
         const locale = window.LOCALE || 'pt-BR';
         return new Date(dateStr).toLocaleDateString(locale, {
            day: '2-digit', month: '2-digit', year: 'numeric'
         });
      },
      
      dateTime(dateStr) {
         return new Date(dateStr).toLocaleDateString('pt-BR', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit'
         });
      },
      
      relativeTime(dateStr) {
         const now = new Date();
         const then = new Date(dateStr);
         const diff = Math.floor((now - then) / 1000);
         
         if (diff < 60) return 'agora';
         if (diff < 3600) return Math.floor(diff / 60) + 'min atrás';
         if (diff < 86400) return Math.floor(diff / 3600) + 'h atrás';
         if (diff < 604800) return Math.floor(diff / 86400) + 'd atrás';
         return this.date(dateStr);
      },
      
      rpeStars(rpe, max = 10) {
         let html = '<span class="chos-rpe">';
         for (let i = 1; i <= max; i++) {
            html += `<i class="fas fa-star star ${i <= rpe ? 'active' : ''}"></i>`;
         }
         html += '</span>';
         return html;
      },
      
      readinessClass(score) {
         if (score >= 80) return 'high';
         if (score >= 50) return 'medium';
         return 'low';
      }
   },
   
   // ============================================
   // Dashboard Init
   // ============================================
   initDashboard() {
      this.auth.ensureSession().then(function() {
         CHOS._setupDashboardUI();
      }).catch(function() {
         window.location.href = '/login';
      });
   },

   _setupDashboardUI() {
      const user = this.auth.getUser();
      if (user.name) {
         $('#user-name').text(user.name.split(' ')[0]);
         if ($('#welcome-name').length) {
            $('#welcome-name').text(user.name.split(' ')[0]);
         }
      }

      $('#logout-btn').on('click', function(e) {
         e.preventDefault();
         CHOS.auth.logout();
      });

      if (CHOS.trainNow) CHOS.trainNow.init();

      // Date/greeting on dashboard are set by loadUserData with locale-aware tDate().
      if (!$('#welcome-greeting').length) {
         const today = new Date().toLocaleDateString(window.LOCALE || 'pt-BR', {
            weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
         });
         $('#today-date').text(today);
      }
   }
};

// Add slideOutRight animation
const style = document.createElement('style');
style.textContent = `
   @keyframes slideOutRight {
      to { transform: translateX(120%); opacity: 0; }
   }
`;
document.head.appendChild(style);

// Global AJAX setup for auth
$.ajaxSetup({
   beforeSend: function(xhr) {
      const token = CHOS.auth.getToken();
      if (token) {
         xhr.setRequestHeader('Authorization', 'Bearer ' + token);
      }
   }
});

// ============================================
// Trial banner
// ============================================
// Reads subscription state from /api/v1/users/me on any authenticated
// page that has a #chos-trial-banner mount point. Renders one of:
//   - "X days left in trial" (status=trialing, future expiry)
//   - "Trial expired — upgrade" (status=trialing, past expiry)
//   - hidden (status=active)
//
// Pages opt in by adding `<div id="chos-trial-banner"></div>` near the top
// of their content block. The banner sits above page content, dismissible
// per session via sessionStorage.
CHOS.trial = {
   _STORAGE_DISMISS_KEY: 'chos-trial-banner-dismissed',
   _MOUNT_ID: 'chos-trial-banner',

   init() {
      const $mount = $('#' + this._MOUNT_ID);
      if (!$mount.length || !CHOS.auth.isAuthenticated()) return;
      const self = this;
      CHOS.api.get('/api/v1/users/me')
         .then(function (user) { self.render($mount, user); })
         .fail(function () { /* silent */ });
   },

   render($mount, user) {
      const status = (user && user.subscription_status) || 'trialing';
      if (status === 'active') return;  // paid, nothing to show

      const expiresIso = user && user.trial_expires_at;
      const now = new Date();
      const expires = expiresIso ? new Date(expiresIso) : null;
      const expired = !expires || expires <= now;

      // Days remaining (ceil — partial day counts as a day).
      let daysLeft = 0;
      if (expires && !expired) {
         daysLeft = Math.ceil((expires - now) / (1000 * 60 * 60 * 24));
      }

      const dismissed = sessionStorage.getItem(this._STORAGE_DISMISS_KEY) === '1';
      if (!expired && dismissed) return;  // user closed the soft banner

      const tr = function (key, vars, fb) {
         return (window.t ? t(key, vars) : null) || fb || key;
      };

      const isUrgent = expired || daysLeft <= 3;
      const variant = expired ? 'is-danger' : (isUrgent ? 'is-warning' : 'is-info');
      const title = expired
         ? tr('billing.banner.expired_title', null, 'Your free trial has ended')
         : tr('billing.banner.trialing_title', { days: daysLeft }, daysLeft + ' day(s) left in your free trial');
      const cta = tr('billing.banner.cta', null, 'Upgrade');
      const dismissBtn = expired
         ? ''
         : '<button type="button" class="btn-close ms-2" aria-label="Dismiss" data-chos-trial-dismiss></button>';

      const html =
         '<div class="chos-trial-banner ' + variant + '" role="status">' +
            '<i class="fas fa-clock chos-trial-banner__icon"></i>' +
            '<div class="flex-grow-1">' + title + '</div>' +
            '<a href="/dashboard/billing" class="chos-btn chos-btn-sm chos-btn-primary ms-2">' + cta + '</a>' +
            dismissBtn +
         '</div>';
      $mount.html(html);

      $mount.find('[data-chos-trial-dismiss]').on('click', function () {
         sessionStorage.setItem(CHOS.trial._STORAGE_DISMISS_KEY, '1');
         $mount.empty();
      });
   }
};

$(document).ready(function () {
   CHOS.trial.init();
   CHOS.prefs.init();
});

// ============================================
// User preferences (nutrition gating, etc.)
// ============================================
CHOS.prefs = {
   init() {
      if (!CHOS.auth.isAuthenticated()) return;
      const self = this;
      CHOS.api.get('/api/v1/users/me')
         .then(function (user) {
            self.applyNutritionGating(user);
            if (user && user.name) {
               try {
                  const stored = JSON.parse(localStorage.getItem('user') || '{}');
                  stored.preferences = user.preferences || stored.preferences;
                  stored.nutrition_enabled = user.nutrition_enabled;
                  localStorage.setItem('user', JSON.stringify({ ...stored, ...user }));
               } catch (e) { /* ignore */ }
            }
         })
         .fail(function () { /* silent */ });
   },

   isNutritionEnabled(user) {
      if (!user) return true;
      if (typeof user.nutrition_enabled === 'boolean') return user.nutrition_enabled;
      const prefs = user.preferences || {};
      if (prefs.app_focus === 'training_only') return false;
      if ('nutrition_enabled' in prefs) return Boolean(prefs.nutrition_enabled);
      return true;
   },

   applyNutritionGating(user) {
      const enabled = this.isNutritionEnabled(user);
      if (enabled) return;

      $('.nav-nutrition').addClass('d-none');

      if (window.location.pathname === '/dashboard/nutrition') {
         CHOS.toast && CHOS.toast.info(
            window.t ? t('nav.nutrition_disabled_redirect') : 'Nutrition is disabled for your plan.'
         );
         window.location.replace('/dashboard');
      }
   }
};

// ============================================
// Upgrade modal (shown on 402 from premium endpoints)
// ============================================
CHOS.billing = {
   _MODAL_ID: 'chos-upgrade-modal',

   _ensureModal() {
      let el = document.getElementById(this._MODAL_ID);
      if (el) return el;

      const tr = function (key, fb) {
         return (window.t ? t(key) : null) || fb || key;
      };

      const html =
         '<div class="modal fade" id="' + this._MODAL_ID + '" tabindex="-1">' +
            '<div class="modal-dialog modal-dialog-centered">' +
               '<div class="modal-content">' +
                  '<div class="modal-header">' +
                     '<h5 class="modal-title fw-bold">' +
                        '<i class="fas fa-lock me-2"></i>' +
                        tr('billing.upgrade_modal.title', 'Upgrade required') +
                     '</h5>' +
                     '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' +
                  '</div>' +
                  '<div class="modal-body">' +
                     '<p class="mb-2" id="' + this._MODAL_ID + '-body">' +
                        tr('billing.upgrade_modal.body', 'Your free trial has ended. Upgrade to continue using premium features.') +
                     '</p>' +
                  '</div>' +
                  '<div class="modal-footer">' +
                     '<button class="btn btn-light" data-bs-dismiss="modal">' +
                        tr('billing.upgrade_modal.dismiss', 'Not now') +
                     '</button>' +
                     '<a href="/dashboard/billing" class="btn btn-primary">' +
                        '<i class="fas fa-arrow-right me-1"></i>' +
                        tr('billing.upgrade_modal.cta', 'See plans') +
                     '</a>' +
                  '</div>' +
               '</div>' +
            '</div>' +
         '</div>';
      const wrapper = document.createElement('div');
      wrapper.innerHTML = html;
      el = wrapper.firstElementChild;
      document.body.appendChild(el);
      return el;
   },

   showUpgradeModal(xhr) {
      const el = this._ensureModal();
      // Use the server-supplied message when available.
      try {
         const detail = xhr.responseJSON && xhr.responseJSON.detail;
         if (detail && typeof detail === 'object' && detail.message) {
            $('#' + this._MODAL_ID + '-body').text(detail.message);
         }
      } catch (e) { /* fall through to default copy */ }
      const modal = bootstrap.Modal.getOrCreateInstance(el);
      modal.show();
   }
};

// Make CHOS available globally
window.CHOS = CHOS;

// ============================================
// Pending referral auto-redeem
// ============================================
// If the visitor came in via /register?ref=XYZ, the register page stashed
// the code in sessionStorage. After signup + login the user has a JWT, so
// the next page load that runs this script applies the code via the same
// authenticated /redeem endpoint and shows a welcome toast.
//
// Storage is cleared on success or any 4xx (terminal — bad/self/dup code).
// Network errors and 5xx leave it alone for retry on the next page load.
$(document).ready(function () {
   if (!CHOS.auth || !CHOS.auth.isAuthenticated || !CHOS.auth.isAuthenticated()) return;
   let pending;
   try { pending = sessionStorage.getItem('chos-pending-ref'); } catch (e) { return; }
   if (!pending) return;

   CHOS.api.post('/api/v1/referrals/redeem', { code: pending })
      .then(function (data) {
         try { sessionStorage.removeItem('chos-pending-ref'); } catch (e) {}
         const inviter = data && data.inviter_name ? data.inviter_name : '';
         const msg = window.t
            ? t('referrals.toast.welcome', { name: inviter })
            : (inviter + ' invited you. Both get a free month.');
         CHOS.toast.success(msg);
      })
      .fail(function (xhr) {
         // Terminal failures (bad code / self / already-applied) — clear so
         // we don't keep retrying on every page load.
         if (xhr && xhr.status >= 400 && xhr.status < 500) {
            try { sessionStorage.removeItem('chos-pending-ref'); } catch (e) {}
         }
      });
});
