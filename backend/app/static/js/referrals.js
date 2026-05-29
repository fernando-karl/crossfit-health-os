/**
 * Referrals page — show my code, copy share link, redeem someone else's
 * code, list friends who joined via my code.
 */
(function () {
   'use strict';

   function tr(key, fallback, vars) {
      const out = window.t ? window.t(key, vars) : null;
      return out && out !== key ? out : (fallback || key);
   }

   function copyToClipboard(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
         return navigator.clipboard.writeText(text);
      }
      const el = document.createElement('textarea');
      el.value = text;
      document.body.appendChild(el);
      el.select();
      try { document.execCommand('copy'); } finally { document.body.removeChild(el); }
      return Promise.resolve();
   }

   function loadCode() {
      return CHOS.api.get('/api/v1/referrals/me').then(function (data) {
         $('#ref-code').text(data.code);
         $('#ref-share-url').val(data.share_url);
         $('#ref-stat-signups').text(data.total_signups);
         $('#ref-stat-months').text(data.months_earned);
      });
   }

   function loadList() {
      return CHOS.api.get('/api/v1/referrals/me/list').then(function (data) {
         const items = data.items || [];
         if (items.length === 0) return;
         const $list = $('#ref-list').empty();
         items.forEach(function (item) {
            const date = new Date(item.joined_at);
            const dateStr = date.toLocaleDateString();
            const statusKey = item.status === 'converted'
               ? 'referrals.status_converted'
               : 'referrals.status_pending';
            const statusClass = item.status === 'converted' ? 'text-success' : 'text-muted';
            $list.append(
               '<div class="chos-card mb-2"><div class="card-body py-2 d-flex justify-content-between align-items-center">' +
                  '<div><strong>' + $('<div>').text(item.referee_name).html() + '</strong>' +
                  ' <span class="text-muted small ms-2">' + dateStr + '</span></div>' +
                  '<span class="small ' + statusClass + '">' + tr(statusKey, item.status) + '</span>' +
               '</div></div>'
            );
         });
      });
   }

   function bindCopy() {
      $('#ref-copy-code').on('click', function () {
         copyToClipboard($('#ref-code').text())
            .then(function () { CHOS.toast.success(tr('referrals.copied', 'Copied!')); });
      });
      $('#ref-copy-link').on('click', function () {
         copyToClipboard($('#ref-share-url').val())
            .then(function () { CHOS.toast.success(tr('referrals.copied', 'Copied!')); });
      });
   }

   function bindRedeem() {
      $('#ref-redeem-form').on('submit', function (e) {
         e.preventDefault();
         const code = ($('#ref-redeem-input').val() || '').trim().toLowerCase();
         if (!code) return;
         const $msg = $('#ref-redeem-msg').removeClass('text-success text-danger').text('');
         CHOS.api.post('/api/v1/referrals/redeem', { code: code })
            .then(function (data) {
               const inviter = data.inviter_name || 'a friend';
               $msg.addClass('text-success').text(
                  tr('referrals.redeem_success', 'Code applied! ' + inviter + ' invited you.', { name: inviter })
               );
               $('#ref-redeem-input').val('');
            })
            .fail(function (xhr) {
               const detail = (xhr.responseJSON && xhr.responseJSON.detail) || '';
               let msg = tr('referrals.redeem_error_generic', 'Could not apply code.');
               if (xhr.status === 404) msg = tr('referrals.redeem_error_unknown', 'Code not found.');
               else if (xhr.status === 400) msg = tr('referrals.redeem_error_self', "You can't use your own code.");
               else if (xhr.status === 409) msg = tr('referrals.redeem_error_already', 'A code was already applied.');
               $msg.addClass('text-danger').text(msg);
            });
      });
   }

   $(document).ready(function () {
      bindCopy();
      bindRedeem();
      loadCode().then(loadList).fail(function () {
         CHOS.toast.error(tr('referrals.load_error', 'Could not load your code.'));
      });
   });
})();
