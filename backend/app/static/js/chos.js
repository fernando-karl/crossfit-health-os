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
         const token = this.getToken();
         if (!token) return false;
         if (isTokenExpired(token)) {
            // Token expired but we may have a refresh token
            if (this.getRefreshToken()) return true;
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            localStorage.removeItem('refresh_token');
            return false;
         }
         return true;
      },

      requireAuth() {
         if (!this.isAuthenticated()) {
            window.location.href = '/login';
            return false;
         }
         return true;
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
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            localStorage.removeItem('user');
         });

         return this._refreshing;
      },

      logout() {
         const token = this.getToken();
         $.ajax({
            url: '/api/v1/auth/logout',
            type: 'POST',
            headers: { 'Authorization': 'Bearer ' + token },
            complete: function() {
               localStorage.removeItem('access_token');
               localStorage.removeItem('refresh_token');
               localStorage.removeItem('user');
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
      const movements = (template.movements && template.movements.length)
         ? template.movements
         : (template.adjusted_movements || []);
      const response = {
         template: {
            name: template.name,
            workout_type: template.workout_type || 'mixed',
            duration_minutes: template.duration_minutes || 60,
            description: template.description || '',
            movements: movements
         },
         adjusted_movements: movements,
         recommendation: (opts && opts.recommendation) || template.description || ''
      };
      try {
         sessionStorage.setItem('chos-quick-workout', JSON.stringify(response));
      } catch (_) { /* storage might be disabled */ }
      window.location.href = '/dashboard/workouts?quick=1';
      return true;
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
      const token = this.auth.getToken();

      // If token is expired but we have a refresh token, try refreshing
      if (token && isTokenExpired(token) && this.auth.getRefreshToken()) {
         this.auth.refreshAccessToken().then(function() {
            CHOS._setupDashboardUI();
         }).fail(function() {
            window.location.href = '/login';
         });
         return;
      }

      if (!this.auth.requireAuth()) return;
      this._setupDashboardUI();
   },

   _setupDashboardUI() {
      const user = this.auth.getUser();
      if (user.name) {
         $('#user-name').text(user.name);
         $('#welcome-name').text(user.name.split(' ')[0]);
      }

      // Setup logout
      $('#logout-btn').on('click', function(e) {
         e.preventDefault();
         CHOS.auth.logout();
      });

      // Set today's date
      const today = new Date().toLocaleDateString('pt-BR', {
         weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'
      });
      $('#today-date').text(today);
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
      const cls = expired ? 'alert-danger' : (isUrgent ? 'alert-warning' : 'alert-info');
      const title = expired
         ? tr('billing.banner.expired_title', null, 'Your free trial has ended')
         : tr('billing.banner.trialing_title', { days: daysLeft }, daysLeft + ' day(s) left in your free trial');
      const cta = tr('billing.banner.cta', null, 'Upgrade');
      const dismissBtn = expired
         ? ''
         : '<button type="button" class="btn-close ms-2" aria-label="Dismiss" data-chos-trial-dismiss></button>';

      const html =
         '<div class="alert ' + cls + ' d-flex align-items-center mb-3" role="alert">' +
            '<i class="fas fa-clock me-2"></i>' +
            '<div class="flex-grow-1">' + title + '</div>' +
            '<a href="/dashboard/billing" class="btn btn-sm btn-light ms-3">' + cta + '</a>' +
            dismissBtn +
         '</div>';
      $mount.html(html);

      $mount.find('[data-chos-trial-dismiss]').on('click', function () {
         sessionStorage.setItem(CHOS.trial._STORAGE_DISMISS_KEY, '1');
         $mount.empty();
      });
   }
};

$(document).ready(function () { CHOS.trial.init(); });

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
