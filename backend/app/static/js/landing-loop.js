/**
 * Landing — interactive "How it works" demo.
 * Auto-advances through steps; tabs are clickable; respects reduced motion.
 */
(function () {
    'use strict';

    var STEP_MS = 5200;
    var root = document.getElementById('lp-loop-demo');
    if (!root) return;

    var total = parseInt(root.getAttribute('data-step-count') || '5', 10);
    var tabs = Array.prototype.slice.call(root.querySelectorAll('.lp-loop__tab'));
    var panels = Array.prototype.slice.call(root.querySelectorAll('.lp-loop__panel'));
    var dots = Array.prototype.slice.call(root.querySelectorAll('.lp-loop__dot'));
    var statusEl = document.getElementById('lp-loop-status');
    var playBtn = document.getElementById('lp-loop-play');
    var current = 1;
    var timer = null;
    var playing = true;
    var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function tr(key, vars, fallback) {
        return (window.t ? window.t(key, vars) : null) || fallback || key;
    }

    function stepLabel(n) {
        var fmt = (statusEl && statusEl.getAttribute('data-step-format')) || '';
        if (window.t) {
            var translated = window.t('landing.loop.demo.step_of', { current: n, total: total });
            if (translated && translated.indexOf('landing.') !== 0) return translated;
        }
        if (fmt) {
            return fmt.replace('{current}', String(n)).replace('{total}', String(total));
        }
        return 'Step ' + n + ' of ' + total;
    }

    function setPlayUi(isPlaying) {
        if (!playBtn) return;
        playing = isPlaying;
        playBtn.setAttribute('aria-pressed', isPlaying ? 'true' : 'false');
        var icon = playBtn.querySelector('i');
        var label = playBtn.querySelector('span');
        if (icon) {
            icon.className = isPlaying ? 'fas fa-pause' : 'fas fa-play';
        }
        if (label) {
            label.textContent = isPlaying
                ? tr('landing.loop.demo.pause', null, 'Pause demo')
                : tr('landing.loop.demo.play', null, 'Play demo');
        }
    }

    function applyPhaseHeights(panel) {
        if (!panel) return;
        Array.prototype.forEach.call(panel.querySelectorAll('.lp-loop__phase-bar'), function (bar) {
            var h = bar.getAttribute('data-h');
            if (h) bar.style.setProperty('--h', h);
        });
        Array.prototype.forEach.call(panel.querySelectorAll('.lp-loop__review-fill'), function (fill) {
            var w = fill.getAttribute('data-w');
            if (w) fill.style.setProperty('--target', w);
        });
    }

    function goTo(step, userInitiated) {
        current = Math.max(1, Math.min(total, step));

        tabs.forEach(function (tab, idx) {
            var n = idx + 1;
            var active = n === current;
            tab.classList.toggle('is-active', active);
            tab.setAttribute('aria-selected', active ? 'true' : 'false');
        });

        panels.forEach(function (panel, idx) {
            var n = idx + 1;
            var active = n === current;
            panel.classList.toggle('is-active', active);
            panel.hidden = !active;
            if (active) applyPhaseHeights(panel);
        });

        dots.forEach(function (dot, idx) {
            dot.classList.toggle('is-active', idx + 1 === current);
        });

        if (statusEl) statusEl.textContent = stepLabel(current);

        if (timer) {
            clearInterval(timer);
            timer = null;
        }
        if (playing && !reducedMotion && (!userInitiated || userInitiated)) {
            timer = setInterval(function () {
                goTo(current >= total ? 1 : current + 1, false);
            }, STEP_MS);
        }
    }

    tabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
            var step = parseInt(tab.getAttribute('data-step') || '1', 10);
            goTo(step, true);
        });
    });

    if (playBtn) {
        playBtn.addEventListener('click', function () {
            setPlayUi(!playing);
            goTo(current, true);
        });
    }

    document.addEventListener('visibilitychange', function () {
        if (document.hidden) {
            if (timer) clearInterval(timer);
            timer = null;
        } else if (playing && !reducedMotion) {
            goTo(current, true);
        }
    });

    if (reducedMotion) {
        setPlayUi(false);
    }

    applyPhaseHeights(panels[0]);
    goTo(1, false);
})();
