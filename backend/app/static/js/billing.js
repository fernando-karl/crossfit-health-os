/**
 * Billing page — wires UI to /api/v1/billing/*. Today the backend
 * returns 501 for checkout/portal/cancel; we surface a friendly
 * "coming soon" message. When Stripe lands, only the backend
 * bodies change — the wiring here stays the same.
 */
(function () {
   'use strict';

   const TRIAL_DAYS_TOTAL = 14;

   function tr(key, vars, fb) {
      return (window.t ? window.t(key, vars) : null) || fb || key;
   }

   function showMsg(type, text) {
      const $msg = $('#billing-msg');
      $msg.removeClass('d-none alert-danger alert-success alert-info alert-warning')
          .addClass('alert-' + type)
          .html(text);
   }

   function setSubmitting($btn, isSubmitting) {
      $btn.prop('disabled', isSubmitting);
      $btn.find('.btn-text').toggleClass('d-none', isSubmitting);
      $btn.find('.btn-spinner').toggleClass('d-none', !isSubmitting);
   }

   function renderStatus(user) {
      const status = (user.subscription_status || 'trialing').toLowerCase();
      const $status = $('#billing-status');
      const labelMap = {
         trialing: { text: tr('billing.status_trialing', null, 'Free trial'), cls: 'bg-info' },
         active:   { text: tr('billing.status_active', null, 'Active'),       cls: 'bg-success' },
         past_due: { text: tr('billing.status_past_due', null, 'Past due'),   cls: 'bg-warning text-dark' },
         canceled: { text: tr('billing.status_canceled', null, 'Canceled'),   cls: 'bg-secondary' }
      };
      const info = labelMap[status] || { text: status, cls: 'bg-secondary' };
      $status.removeClass().addClass('badge ' + info.cls).text(info.text);

      // Expiry / next-billing date.
      if (user.trial_expires_at) {
         const d = new Date(user.trial_expires_at);
         $('#billing-expires').text(d.toLocaleDateString());
      } else {
         $('#billing-expires').text('—');
      }

      // Trial countdown bar.
      if (status === 'trialing' && user.trial_expires_at) {
         const expires = new Date(user.trial_expires_at);
         const now = new Date();
         const msLeft = expires - now;
         const daysLeft = Math.max(0, Math.ceil(msLeft / (1000 * 60 * 60 * 24)));
         const pct = Math.max(0, Math.min(100, (daysLeft / TRIAL_DAYS_TOTAL) * 100));
         $('#trial-days-left').text(daysLeft);
         $('#trial-progress-bar').css('width', pct + '%');
         $('#trial-countdown').removeClass('d-none');
      }

      // Toggle action buttons by status.
      if (status === 'active') {
         $('#btn-subscribe').addClass('d-none');
         $('#btn-manage').removeClass('d-none');
         $('#cancel-section').removeClass('d-none');
         $('#billing-expires-label').text(tr('billing.next_billing_label', null, 'Next billing'));
      } else {
         $('#btn-subscribe').removeClass('d-none');
         $('#btn-manage').addClass('d-none');
         $('#cancel-section').addClass('d-none');
      }
   }

   function handleStripePending(xhr) {
      if (xhr && xhr.status === 501) {
         showMsg('warning', tr('billing.stripe_pending', null,
            'Payments are coming soon. Stay tuned — your trial keeps working in the meantime.'));
         return true;
      }
      return false;
   }

   function bindActions() {
      // Subscribe → POST /billing/checkout, then redirect to checkout_url.
      $('#btn-subscribe').on('click', function () {
         const $btn = $(this);
         setSubmitting($btn, true);
         CHOS.api.post('/api/v1/billing/checkout', {})
            .then(function (data) {
               if (data && data.checkout_url) {
                  window.location.href = data.checkout_url;
                  return;
               }
               showMsg('info', tr('billing.checkout_started', null, 'Redirecting…'));
            })
            .fail(function (xhr) {
               if (!handleStripePending(xhr)) {
                  showMsg('danger', tr('billing.checkout_error', null, 'Could not start checkout.'));
               }
            })
            .always(function () { setSubmitting($btn, false); });
      });

      // Manage → GET /billing/portal, redirect to portal_url.
      $('#btn-manage').on('click', function () {
         CHOS.api.get('/api/v1/billing/portal')
            .then(function (data) {
               if (data && data.portal_url) {
                  window.location.href = data.portal_url;
               }
            })
            .fail(handleStripePending);
      });

      // Cancel → confirm modal → POST /billing/cancel.
      $('#btn-cancel').on('click', function () {
         const modal = new bootstrap.Modal(document.getElementById('cancelConfirmModal'));
         modal.show();
      });
      $('#btn-cancel-confirm').on('click', function () {
         CHOS.api.post('/api/v1/billing/cancel', {})
            .then(function () {
               showMsg('success', tr('billing.cancel_success', null,
                  'Subscription canceled. Access stays active until the end of the period.'));
               // Reload state.
               loadUserState();
            })
            .fail(function (xhr) {
               handleStripePending(xhr) || showMsg('danger',
                  tr('billing.cancel_error', null, 'Could not cancel. Please try again or email support.'));
            })
            .always(function () {
               bootstrap.Modal.getInstance(document.getElementById('cancelConfirmModal'))?.hide();
            });
      });
   }

   function loadUserState() {
      return CHOS.api.get('/api/v1/users/me').then(renderStatus);
   }

   $(document).ready(function () {
      bindActions();
      loadUserState();
   });
})();
