// Calendar UI for the training scheduling page.
// Expects CHOS.api / CHOS.toast / CHOS.loading to be available from chos.js.

const ScheduleUI = (function () {
    const METHODOLOGY_PLANS = {
        hwpo: [
            { type: "accumulation", weeks: 3 },
            { type: "deload", weeks: 1 },
            { type: "intensification", weeks: 3 },
            { type: "deload", weeks: 1 },
            { type: "realization", weeks: 2 },
            { type: "test", weeks: 1 },
            { type: "transition", weeks: 1 },
        ],
        mayhem: [
            { type: "accumulation", weeks: 9 },
            { type: "intensification", weeks: 10 },
            { type: "realization", weeks: 8 },
            { type: "intensification", weeks: 8 },
            { type: "realization", weeks: 8 },
        ],
        comptrain: [
            { type: "accumulation", weeks: 4 },
            { type: "deload", weeks: 1 },
            { type: "intensification", weeks: 4 },
            { type: "deload", weeks: 1 },
            { type: "realization", weeks: 2 },
        ],
        custom: [],
    };

    const WORKOUT_COLORS = {
        strength: "primary",
        metcon: "danger",
        skill: "success",
        conditioning: "info",
        mixed: "warning",
    };

    const S = function () { return CHOS.stimulus; };
    const Sh = function () { return CHOS.shift; };
    const D = function () { return CHOS.duration; };

    function focusDisplayLabel(focus) {
        return S().displayLabel(focus);
    }

    function getMacroDefaultDuration() {
        const raw = state.macrocycle && state.macrocycle.available_minutes_per_session;
        const d = parseInt(raw, 10);
        return Number.isFinite(d) ? d : 60;
    }

    function durationPickerOptions() {
        return {
            macroDefault: getMacroDefaultDuration(),
            placeholder: t("schedule.drawer.focus_placeholder"),
        };
    }

    function isKnownStimulus(focus) {
        return S().isKnown(focus);
    }

    function formatSessionScheduleMeta(session) {
        const shift = formatSessionShift(session);
        const time = session && session.start_time ? session.start_time.slice(0, 5) : "";
        const dur = session && session.duration_minutes;
        const parts = [];
        if (time) parts.push(shift + " · " + time);
        else if (shift) parts.push(shift);
        if (dur) parts.push(String(dur) + t("schedule.session.duration_min"));
        return parts.join(" · ");
    }

    function formatSessionTimeMeta(session) {
        const time = session && session.start_time ? session.start_time.slice(0, 5) : "";
        const dur = session && session.duration_minutes;
        const parts = [];
        if (time) parts.push(time);
        if (dur) parts.push(String(dur) + t("schedule.session.duration_min"));
        return parts.join(" · ");
    }

    function updateSessionSummaryChips(wrapper, session) {
        if (!wrapper) return;
        const catCls = S().catClassForWorkoutType(session.workout_type);
        const headerCat = wrapper.querySelector(".chos-cat.fw-semibold");
        if (headerCat) {
            headerCat.className = "chos-cat " + catCls + " fw-semibold";
        }
        const summary = wrapper.querySelector("[data-session-summary]");
        if (!summary) return;
        const wtLabel = session.workout_type ? t("schedule.workout_type." + session.workout_type) : "?";
        const focusText = focusDisplayLabel(session.focus) || t("schedule.drawer.focus_unset");
        const scheduleChip = formatSessionScheduleMeta(session) || t("schedule.drawer.focus_unset");
        summary.innerHTML = `
            <span class="chos-chip"><span class="chip-dot"></span><i class="fas fa-clock me-1 text-secondary" style="font-size:0.7rem;"></i>${CHOS.escape(scheduleChip)}</span>
            <span class="chos-chip ${catCls}"><span class="chip-dot"></span>${CHOS.escape(wtLabel)}</span>
            <span class="chos-chip"><span class="chip-dot"></span><i class="fas fa-bullseye me-1 text-secondary" style="font-size:0.7rem;"></i>${CHOS.escape(focusText)}</span>`;
    }

    function refreshShiftPicker(wrapper, session) {
        const picker = wrapper && wrapper.querySelector("[data-shift-picker]");
        if (!picker) return;
        const shift = Sh().isValid(session.shift) ? session.shift : "morning";
        picker.innerHTML = Sh().buildPickerHtml(shift);
    }

    function refreshDurationPicker(wrapper, session) {
        const picker = wrapper && wrapper.querySelector("[data-duration-picker]");
        if (!picker) return;
        const defaultDur = getMacroDefaultDuration();
        picker.innerHTML = D().buildPickerHtml(session.duration_minutes || defaultDur, durationPickerOptions());
    }

    function applyDurationChange(wrapper, session, value) {
        if (value === "custom") {
            refreshDurationPicker(wrapper, session);
            const customWrap = wrapper.querySelector(".chos-duration-custom");
            const input = customWrap && customWrap.querySelector("[data-field='duration_minutes']");
            if (input) {
                if (!input.value) input.value = session.duration_minutes || 60;
                input.focus();
            }
            return;
        }
        const mins = parseInt(value, 10);
        if (!Number.isFinite(mins)) return;
        session.duration_minutes = mins;
        refreshDurationPicker(wrapper, session);
        updateSessionSummaryChips(wrapper, session);
        persistSession(session);
    }

    function applyShiftChange(wrapper, session, shift) {
        session.shift = Sh().isValid(shift) ? shift : "morning";
        if (session.shift !== "custom" && Sh().DEFAULT_TIMES[session.shift]) {
            session.start_time = Sh().DEFAULT_TIMES[session.shift];
            const timeInput = wrapper.querySelector("[data-field='start_time']");
            if (timeInput) timeInput.value = session.start_time;
        } else if (session.shift === "custom") {
            const timeInput = wrapper.querySelector("[data-field='start_time']");
            if (timeInput) timeInput.focus();
        }
        refreshShiftPicker(wrapper, session);
        updateSessionSummaryChips(wrapper, session);
        persistSession(session);
    }

    function refreshFocusPicker(wrapper, session) {
        const picker = wrapper && wrapper.querySelector("[data-focus-picker]");
        if (!picker) return;
        picker.innerHTML = S().buildPickerHtml(session.focus, session.workout_type, {
            placeholder: t("schedule.drawer.focus_placeholder"),
        });
    }

    function refreshTypePicker(wrapper, session) {
        const picker = wrapper && wrapper.querySelector("[data-type-picker]");
        if (!picker) return;
        picker.innerHTML = S().buildWorkoutTypePickerHtml(session.workout_type);
    }

    function applyWorkoutTypeChange(wrapper, session, workoutType) {
        session.workout_type = workoutType || "mixed";
        if (session.focus && isKnownStimulus(session.focus)
            && !S().isCompatible(session.focus, session.workout_type)) {
            session.focus = null;
        }
        refreshTypePicker(wrapper, session);
        refreshFocusPicker(wrapper, session);
        updateSessionSummaryChips(wrapper, session);
        persistSession(session);
    }

    let drawerEventsBound = false;

    function bindDrawerEvents() {
        if (drawerEventsBound) return;
        const container = document.getElementById("drawer-sessions");
        if (!container) return;
        drawerEventsBound = true;

        container.addEventListener("click", function (e) {
            const durChip = e.target.closest(".chos-duration-chip[data-duration]");
            if (durChip) {
                const wrapper = durChip.closest("[data-idx]");
                if (!wrapper) return;
                const idx = parseInt(wrapper.dataset.idx, 10);
                const session = state.drawerSessions[idx];
                if (!session) return;
                applyDurationChange(wrapper, session, durChip.dataset.duration);
                return;
            }

            const shiftChip = e.target.closest(".chos-shift-chip[data-shift]");
            if (shiftChip) {
                const wrapper = shiftChip.closest("[data-idx]");
                if (!wrapper) return;
                const idx = parseInt(wrapper.dataset.idx, 10);
                const session = state.drawerSessions[idx];
                if (!session) return;
                applyShiftChange(wrapper, session, shiftChip.dataset.shift);
                return;
            }

            const typeChip = e.target.closest(".chos-type-chip[data-workout-type]");
            if (typeChip) {
                const wrapper = typeChip.closest("[data-idx]");
                if (!wrapper) return;
                const idx = parseInt(wrapper.dataset.idx, 10);
                const session = state.drawerSessions[idx];
                if (!session) return;
                applyWorkoutTypeChange(wrapper, session, typeChip.dataset.workoutType);
                return;
            }

            const chip = e.target.closest(".chos-stimulus-chip[data-stimulus]");
            if (!chip) return;
            const wrapper = chip.closest("[data-idx]");
            if (!wrapper) return;
            const idx = parseInt(wrapper.dataset.idx, 10);
            const session = state.drawerSessions[idx];
            if (!session) return;

            const stimulus = chip.dataset.stimulus;
            const customInput = wrapper.querySelector("[data-field='focus_custom']");

            wrapper.querySelectorAll(".chos-stimulus-chip[data-stimulus]").forEach(function (c) {
                c.classList.remove("is-selected");
                c.setAttribute("aria-pressed", "false");
            });
            chip.classList.add("is-selected");
            chip.setAttribute("aria-pressed", "true");

            if (stimulus === S().FOCUS_CUSTOM) {
                if (customInput) {
                    customInput.classList.remove("d-none");
                    customInput.focus();
                }
                session.focus = customInput ? customInput.value.trim() || null : null;
            } else {
                if (customInput) customInput.classList.add("d-none");
                session.focus = stimulus;
                session.workout_type = S().workoutTypeFor(stimulus);
                refreshTypePicker(wrapper, session);
                refreshFocusPicker(wrapper, session);
            }

            updateSessionSummaryChips(wrapper, session);
            persistSession(session);
        });

        container.addEventListener("change", function (e) {
            const field = e.target.dataset && e.target.dataset.field;
            if (!field) return;
            const wrapper = e.target.closest("[data-idx]");
            if (!wrapper) return;
            const idx = parseInt(wrapper.dataset.idx, 10);
            const session = state.drawerSessions[idx];
            if (!session) return;

            if (field === "focus_custom") {
                session.focus = e.target.value.trim() || null;
                updateSessionSummaryChips(wrapper, session);
                persistSession(session);
                return;
            }

            let value = e.target.value;
            if (field === "duration_minutes") {
                value = parseInt(value, 10);
                if (!Number.isFinite(value)) return;
                session.duration_minutes = value;
                refreshDurationPicker(wrapper, session);
            } else if (field === "start_time" && session.shift !== "custom" && value) {
                session.shift = "custom";
                refreshShiftPicker(wrapper, session);
                session[field] = value || null;
            } else {
                session[field] = value || null;
            }

            updateSessionSummaryChips(wrapper, session);
            persistSession(session);
        });

        container.addEventListener("input", function (e) {
            if (!e.target.matches("[data-field='focus_custom']")) return;
            const wrapper = e.target.closest("[data-idx]");
            if (!wrapper) return;
            const idx = parseInt(wrapper.dataset.idx, 10);
            const session = state.drawerSessions[idx];
            if (!session) return;
            session.focus = e.target.value.trim() || null;
            updateSessionSummaryChips(wrapper, session);
        });
    }

    function isValidShift(shift) {
        return CHOS.shift && CHOS.shift.isValid(shift);
    }

    function shiftLabel(shift) {
        if (CHOS.shift) return CHOS.shift.label(shift);
        if (!isValidShift(shift)) return "";
        const key = "schedule.shift." + shift;
        const hit = t(key);
        return hit !== key ? hit : shift;
    }

    function formatSessionShift(session) {
        const label = shiftLabel(session && session.shift);
        if (label) return label;
        if (session && session.start_time) return session.start_time.slice(0, 5);
        return shiftLabel("morning");
    }

    // Back-compat: existing code reads SHIFT_LABELS[s.shift]; resolve via t() so
    // values stay in sync with the active locale. Guard against null → "null".
    const SHIFT_LABELS = new Proxy({}, {
        get: function (_target, prop) {
            if (prop === "null" || prop === "undefined") return "";
            return shiftLabel(prop);
        },
    });

    let state = {
        macrocycle: null,   // active macrocycle (with microcycles)
        currentMicro: null, // microcycle being displayed
        viewDate: null,     // a date inside the currently-displayed week
        drawerSessions: [], // sessions in the open drawer
        drawerDate: null,
        templateCache: {},  // template_id -> workout template data
        templateLoading: {},
    };

    // ----- Date helpers (local time — never UTC) -----------------------------
    function parseISODate(s) {
        const [y, m, d] = s.split("-").map(Number);
        return new Date(y, m - 1, d);
    }

    function toISODate(d) {
        const y = d.getFullYear();
        const m = String(d.getMonth() + 1).padStart(2, "0");
        const day = String(d.getDate()).padStart(2, "0");
        return `${y}-${m}-${day}`;
    }

    function addDays(d, n) {
        const x = new Date(d);
        x.setDate(x.getDate() + n);
        return x;
    }

    function mondayOf(d) {
        const wd = d.getDay(); // 0=Sun,1=Mon,...6=Sat
        const offset = wd === 0 ? -6 : 1 - wd;
        return addDays(d, offset);
    }

    function formatShortPt(d) {
        return tDate(d, { weekday: "short", day: "2-digit", month: "2-digit" });
    }

    function formatLongPt(d) {
        return tDate(d, { day: "2-digit", month: "long" });
    }

    function isSameDay(a, b) {
        return a.getFullYear() === b.getFullYear()
            && a.getMonth() === b.getMonth()
            && a.getDate() === b.getDate();
    }

    // ----- Init ---------------------------------------------------------------
    function init() {
        refreshBlockPlanPreview();
        document.getElementById("macro-input-start").value = toISODate(mondayOf(new Date()));
        bindDrawerEvents();
        bindMacroFormEvents();
        renderMacroFormPickers();
        loadActiveMacro();
        window.addEventListener("pageshow", refreshScheduleIfNeeded);
    }

    let macroFormBound = false;

    function renderMacroFormPickers() {
        if (!CHOS.macroForm) return;
        const minsInput = document.getElementById("macro-input-minutes");
        const daysInput = document.getElementById("macro-input-days");
        const durPicker = document.getElementById("macro-duration-picker");
        const daysPicker = document.getElementById("macro-days-picker");
        const mins = parseInt(minsInput && minsInput.value, 10) || 60;
        const days = parseInt(daysInput && daysInput.value, 10) || 5;
        if (durPicker) durPicker.innerHTML = CHOS.macroForm.buildDurationPickerHtml(mins);
        if (daysPicker) daysPicker.innerHTML = CHOS.macroForm.buildDaysPickerHtml(days);
    }

    function bindMacroFormEvents() {
        if (macroFormBound) return;
        const modal = document.getElementById("createMacroModal");
        if (!modal) return;
        macroFormBound = true;
        modal.addEventListener("click", function (e) {
            const durChip = e.target.closest("[data-macro-duration]");
            if (durChip) {
                const input = document.getElementById("macro-input-minutes");
                if (input) input.value = durChip.dataset.macroDuration;
                renderMacroFormPickers();
                return;
            }
            const daysChip = e.target.closest("[data-macro-days]");
            if (daysChip) {
                const input = document.getElementById("macro-input-days");
                if (input) input.value = daysChip.dataset.macroDays;
                renderMacroFormPickers();
            }
        });
        modal.addEventListener("show.bs.modal", renderMacroFormPickers);
    }

    function refreshScheduleIfNeeded() {
        if (!sessionStorage.getItem("chos-schedule-refresh")) return;
        sessionStorage.removeItem("chos-schedule-refresh");
        if (state.currentMicro && state.currentMicro.id) {
            CHOS.api.get("/api/v1/schedule/microcycles/" + state.currentMicro.id)
                .done(function (fresh) {
                    state.currentMicro = fresh;
                    renderBanner();
                    paintGrid(fresh);
                });
            return;
        }
        if (state.macrocycle) loadActiveMacro();
    }

    function loadActiveMacro() {
        CHOS.api.get("/api/v1/schedule/macrocycles/active")
            .done(function (data) {
                state.macrocycle = data;
                renderBanner();
                // Default view: microcycle that contains today, else the first one
                const today = new Date();
                let target = data.microcycles.find(function (m) {
                    const s = parseISODate(m.start_date), e = parseISODate(m.end_date);
                    return today >= s && today <= e;
                });
                if (!target && data.microcycles.length) target = data.microcycles[0];
                if (target) {
                    state.currentMicro = target;
                    state.viewDate = parseISODate(target.start_date);
                    showCalendar();
                    renderWeek();
                }
            })
            .fail(function (xhr) {
                if (xhr.status === 404) showEmpty();
                else console.error("Failed to load macrocycle", xhr);
            });
    }

    function showEmpty() {
        document.getElementById("empty-state").classList.remove("d-none");
        document.getElementById("macro-banner").classList.add("d-none");
        document.getElementById("calendar-container").classList.add("d-none");
    }

    function showCalendar() {
        document.getElementById("empty-state").classList.add("d-none");
        document.getElementById("macro-banner").classList.remove("d-none");
        document.getElementById("calendar-container").classList.remove("d-none");
    }

    // ----- Banner + calendar rendering --------------------------------------
    function renderBanner() {
        const m = state.macrocycle;
        document.getElementById("macro-name").textContent = m.name;
        document.getElementById("macro-dates").textContent =
            `${formatLongPt(parseISODate(m.start_date))} – ${formatLongPt(parseISODate(m.end_date))}`;
        const durEl = document.getElementById("macro-session-duration");
        if (durEl) {
            durEl.textContent = t("schedule.macro_session_duration", { n: m.available_minutes_per_session || 60 });
        }
        document.getElementById("macro-methodology").textContent = m.methodology.toUpperCase();

        const micro = state.currentMicro;
        if (!micro) return;

        document.getElementById("macro-block-badge").textContent =
            t("schedule.block_badge", { block: micro.block_type || "—" });

        // Total weeks across the macro (sum of block_plan).
        const totalWeeks = (m.block_plan || []).reduce((acc, b) => acc + (b.weeks || 0), 0) || 1;
        const weekIdx = micro.week_index_in_macro;
        const pct = Math.min(100, Math.round((weekIdx / totalWeeks) * 100));

        document.getElementById("macro-week-label").textContent =
            t("schedule.week_label", {
                wk_in_block: micro.week_index_in_block || "?",
                total_in_block: totalWeeksInBlock(m, micro),
                wk_in_macro: weekIdx,
            });
        document.getElementById("macro-progress-text").textContent = `${weekIdx}/${totalWeeks}`;
        document.getElementById("macro-progress-bar").style.width = pct + "%";
        renderPhaseTimeline();
        renderWeekStrip();
    }

    function totalWeeksInBlock(macro, micro) {
        if (!macro || !micro || !micro.block_type) return "?";
        let idx = micro.week_index_in_macro, cum = 0;
        for (const b of macro.block_plan) {
            cum += b.weeks;
            if (idx <= cum) return b.weeks;
        }
        return "?";
    }

    function blockTypeLabel(blockType) {
        if (!blockType) return "—";
        const key = "shared.block_type." + String(blockType).toLowerCase();
        const hit = t(key);
        if (hit && hit.indexOf("shared.") !== 0) return hit;
        const alt = "shared.phases." + String(blockType).toLowerCase();
        const hit2 = t(alt);
        return hit2 && hit2.indexOf("shared.") !== 0 ? hit2 : blockType;
    }

    function getCurrentBlockRange(macro, micro) {
        const plan = macro.block_plan || [];
        let cum = 0;
        for (let i = 0; i < plan.length; i++) {
            const b = plan[i];
            const start = cum + 1;
            cum += b.weeks || 0;
            if (micro.week_index_in_macro <= cum) {
                return { block: b, startWeek: start, endWeek: cum, index: i };
            }
        }
        return null;
    }

    function renderPhaseTimeline() {
        const el = document.getElementById("phase-timeline");
        if (!el || !state.macrocycle) return;
        const plan = state.macrocycle.block_plan || [];
        const micro = state.currentMicro;
        if (!plan.length) {
            el.innerHTML = "";
            return;
        }
        const maxWeeks = Math.max.apply(null, plan.map(function (b) { return b.weeks || 1; }));
        const currentRange = micro ? getCurrentBlockRange(state.macrocycle, micro) : null;
        const html = plan.map(function (b, i) {
            const isCurrent = currentRange && currentRange.index === i;
            const pct = Math.round(((b.weeks || 1) / maxWeeks) * 100);
            const barH = Math.max(32, Math.min(100, pct));
            const cls = "chos-phase" + (isCurrent ? " is-current" : "");
            return `<div class="${cls}" title="${CHOS.escape(blockTypeLabel(b.type))}">
                <div class="chos-phase__bar" style="height: ${barH}%"></div>
                <span class="chos-phase__label">${CHOS.escape(blockTypeLabel(b.type))}</span>
                <span class="chos-phase__weeks num">${t("schedule.modal.weeks_short", { n: b.weeks })}</span>
            </div>`;
        }).join("");
        el.innerHTML = html;
    }

    function renderWeekStrip() {
        const el = document.getElementById("week-strip");
        if (!el || !state.macrocycle || !state.currentMicro) return;
        const range = getCurrentBlockRange(state.macrocycle, state.currentMicro);
        if (!range) {
            el.innerHTML = "";
            return;
        }
        const weeks = (state.macrocycle.microcycles || []).filter(function (m) {
            return m.week_index_in_macro >= range.startWeek && m.week_index_in_macro <= range.endWeek;
        });
        const html = weeks.map(function (m) {
            const isActive = state.currentMicro && String(m.id) === String(state.currentMicro.id);
            const cls = "chos-week-strip__pill num" + (isActive ? " is-active" : "");
            return `<button type="button" class="${cls}" data-micro-id="${m.id}" aria-current="${isActive ? "true" : "false"}">${t("shared.week_n_short", { n: m.week_index_in_block || m.week_index_in_macro })}</button>`;
        }).join("");
        el.innerHTML = html;
        el.querySelectorAll("[data-micro-id]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                jumpToMicro(btn.getAttribute("data-micro-id"));
            });
        });
        const active = el.querySelector(".is-active");
        if (active && active.scrollIntoView) {
            active.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
        }
    }

    function renderWeekStats(micro) {
        const el = document.getElementById("week-stats");
        if (!el) return;
        const sessions = micro.sessions || [];
        const byDate = {};
        sessions.forEach(function (s) {
            (byDate[s.date] = byDate[s.date] || []).push(s);
        });
        let training = 0;
        let generated = 0;
        let completed = 0;
        let restDays = 0;
        const start = parseISODate(micro.start_date);
        for (let i = 0; i < 7; i++) {
            const iso = toISODate(addDays(start, i));
            const daySessions = byDate[iso] || [];
            if (!daySessions.length) {
                restDays++;
            } else if (daySessions.every(function (s) { return s.status === "skipped"; })) {
                restDays++;
            } else {
                const active = daySessions.filter(function (s) { return s.status !== "skipped"; });
                training += active.length;
                generated += active.filter(function (s) { return s.status === "generated"; }).length;
                completed += active.filter(function (s) { return s.completed; }).length;
            }
        }
        const pct = training > 0 ? Math.round((completed / training) * 100) : 0;
        el.innerHTML = `
            <div class="chos-week-stats-progress mb-2">
                <div class="d-flex justify-content-between align-items-center small text-secondary mb-1">
                    <span>${t("schedule.week_stats.progress", { done: completed, total: training })}</span>
                    <span class="num fw-semibold">${pct}%</span>
                </div>
                <div class="chos-progress" style="height: 5px;" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
                    <div class="chos-progress-fill success" style="width: ${pct}%"></div>
                </div>
            </div>
            <span class="chos-schedule-stat is-training"><i class="fas fa-dumbbell"></i>${t("schedule.week_stats.training", { n: training })}</span>
            <span class="chos-schedule-stat is-generated"><i class="fas fa-check"></i>${t("schedule.week_stats.generated", { n: generated })}</span>
            <span class="chos-schedule-stat is-done"><i class="fas fa-flag-checkered"></i>${t("schedule.week_stats.completed", { n: completed })}</span>
            <span class="chos-schedule-stat is-rest"><i class="fas fa-bed"></i>${t("schedule.week_stats.rest", { n: restDays })}</span>
        `;
    }

    function canQuickStartSession(s) {
        return !!(s && s.generated_template_id && !s.completed && s.status !== "skipped");
    }

    function compareSessionsForStart(a, b) {
        if (a.date !== b.date) return a.date < b.date ? -1 : 1;
        const orderA = a.order_in_day || 0;
        const orderB = b.order_in_day || 0;
        if (orderA !== orderB) return orderA - orderB;
        const timeA = a.start_time || "";
        const timeB = b.start_time || "";
        return timeA.localeCompare(timeB);
    }

    function findNextQuickStartSession(micro) {
        if (!micro) return null;
        const todayIso = toISODate(new Date());
        const weekEnd = micro.end_date;
        const candidates = (micro.sessions || []).filter(canQuickStartSession)
            .filter(function (s) { return s.date <= weekEnd; })
            .sort(compareSessionsForStart);
        if (!candidates.length) return null;

        const todayFirst = candidates.find(function (s) { return s.date === todayIso; });
        if (todayFirst) return todayFirst;

        const upcoming = candidates.find(function (s) { return s.date >= todayIso; });
        return upcoming || candidates[0];
    }

    function formatNextWorkoutWhen(session) {
        const todayIso = toISODate(new Date());
        if (session.date === todayIso) return t("schedule.next_workout.today");
        return formatShortPt(parseISODate(session.date));
    }

    function renderNextWorkoutBanner(micro) {
        const el = document.getElementById("schedule-next-workout");
        if (!el) return;
        const session = findNextQuickStartSession(micro);
        if (!session) {
            el.classList.add("d-none");
            el.innerHTML = "";
            return;
        }

        const title = focusDisplayLabel(session.focus)
            || (session.workout_type ? t("schedule.workout_type." + session.workout_type) : t("schedule.next_workout.label"));
        const when = formatNextWorkoutWhen(session);
        const meta = formatSessionScheduleMeta(session);
        const catCls = S().catClassForWorkoutType(session.workout_type);

        el.classList.remove("d-none");
        el.innerHTML = `
            <div class="chos-next-workout-banner__inner ${catCls}">
                <div class="chos-next-workout-banner__copy">
                    <div class="chos-next-workout-banner__eyebrow">${t("schedule.next_workout.label")}</div>
                    <div class="chos-next-workout-banner__title">${CHOS.escape(title)}</div>
                    <div class="chos-next-workout-banner__meta num">
                        <span class="chos-badge chos-badge-primary" style="font-size:0.65rem;">${CHOS.escape(when)}</span>
                        ${meta ? `<span class="text-secondary">${CHOS.escape(meta)}</span>` : ""}
                    </div>
                </div>
                <button type="button" class="chos-btn chos-btn-primary chos-btn-sm" data-action="quickstart" data-session-id="${session.id}">
                    <i class="fas fa-play me-1"></i>${t("schedule.next_workout.start")}
                </button>
            </div>`;
    }

    function renderSessionQuickStart(s) {
        if (!canQuickStartSession(s)) return "";
        const label = t("schedule.session.quick_start");
        const short = t("schedule.session.quick_start_short");
        return `<button type="button" class="chos-session-quickstart" data-action="quickstart" data-session-id="${s.id}"`
            + ` aria-label="${CHOS.escape(label)}" title="${CHOS.escape(label)}">`
            + `<span class="chos-session-quickstart__icon"><i class="fas fa-play"></i></span>`
            + `<span class="chos-session-quickstart__label d-none d-md-inline">${CHOS.escape(label)}</span>`
            + `<span class="chos-session-quickstart__label d-md-none">${CHOS.escape(short)}</span>`
            + `</button>`;
    }

    function resolveSessionStatus(s) {
        if (s.status === "skipped") return { key: "rest", cls: "is-rest" };
        if (s.completed) return { key: "completed", cls: "is-completed" };
        if (s.status === "generated") return { key: "generated", cls: "is-generated" };
        return { key: "planned", cls: "is-planned" };
    }

    function sessionMovementPreviewHtml(s) {
        if (!s.generated_template_id) return "";
        const tmpl = getTemplate(s.generated_template_id);
        if (!tmpl || !tmpl.movements || !tmpl.movements.length) return "";
        const line = tmpl.movements.slice(0, 3).map(function (m) {
            return humanize(m.movement || m.name);
        }).join(" · ");
        return `<div class="chos-session-item__preview">${CHOS.escape(line)}</div>`;
    }

    function buildSessionTooltip(tmpl) {
        if (!tmpl) return "";
        const parts = [];
        const stimRaw = tmpl.target_stimulus || tmpl.description || "";
        if (stimRaw) {
            const stim = (CHOS.stimulus && CHOS.stimulus.isKnown(stimRaw))
                ? CHOS.stimulus.label(stimRaw) : stimRaw;
            parts.push(stim);
        }
        const eq = (tmpl.equipment_required || []).filter(Boolean);
        if (eq.length) {
            parts.push(t("schedule.tooltip.equipment", { list: eq.join(", ") }));
        } else {
            parts.push(t("schedule.tooltip.no_equipment"));
        }
        return parts.join("\n");
    }

    function escAttr(s) {
        return String(s)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/</g, "&lt;")
            .replace(/\n/g, "&#10;");
    }

    function wireSessionTooltips() {
        if (typeof bootstrap === "undefined") return;
        const canHover = window.matchMedia("(hover: hover)").matches;
        document.querySelectorAll(".chos-session-item[data-bs-title]").forEach(function (el) {
            const inst = bootstrap.Tooltip.getInstance(el);
            if (inst) inst.dispose();
            if (!canHover) return;
            new bootstrap.Tooltip(el, {
                title: el.getAttribute("data-bs-title") || "",
                placement: "top",
                trigger: "hover focus",
                customClass: "chos-session-tooltip",
            });
        });
    }

    function applySessionTooltip(el, tmpl) {
        if (!el || !tmpl) return;
        const tip = buildSessionTooltip(tmpl);
        if (!tip) return;
        el.setAttribute("data-bs-title", tip);
        el.setAttribute("tabindex", "0");
    }

    function prefetchWeekTemplates(micro) {
        (micro.sessions || []).forEach(function (s) {
            if (s.generated_template_id) loadTemplateForGrid(s.generated_template_id);
        });
    }

    function loadTemplateForGrid(templateId) {
        if (!templateId || state.templateCache[templateId] || state.templateLoading[templateId]) return;
        state.templateLoading[templateId] = true;
        CHOS.api.get(`/api/v1/training/templates/${templateId}`)
            .then(function (data) {
                state.templateCache[templateId] = data;
                delete state.templateLoading[templateId];
                refreshSessionPreviews();
            })
            .catch(function () {
                delete state.templateLoading[templateId];
            });
    }

    function refreshSessionPreviews() {
        document.querySelectorAll(".chos-session-item[data-template-id]").forEach(function (el) {
            const tid = el.getAttribute("data-template-id");
            const tmpl = getTemplate(tid);
            if (!tmpl || !tmpl.movements || !tmpl.movements.length) return;
            const line = tmpl.movements.slice(0, 3).map(function (m) {
                return humanize(m.movement || m.name);
            }).join(" · ");
            let slot = el.querySelector(".chos-session-item__preview");
            if (!slot) {
                slot = document.createElement("div");
                slot.className = "chos-session-item__preview";
                const meta = el.querySelector(".chos-session-item__meta");
                if (meta) meta.before(slot);
                else el.appendChild(slot);
            }
            slot.textContent = line;
        });
        document.querySelectorAll(".chos-session-item[data-template-id]").forEach(function (el) {
            const tid = el.getAttribute("data-template-id");
            applySessionTooltip(el, getTemplate(tid));
        });
        wireSessionTooltips();
    }

    function renderWeek() {
        const micro = state.currentMicro;
        if (!micro) return;
        const start = parseISODate(micro.start_date);
        const end = parseISODate(micro.end_date);

        document.getElementById("week-label").textContent =
            `${formatLongPt(start)} – ${formatLongPt(end)}`;

        // Reload microcycle with sessions to get fresh state
        CHOS.api.get(`/api/v1/schedule/microcycles/${micro.id}`)
            .done(function (fresh) {
                state.currentMicro = fresh;
                renderBanner();
                paintGrid(fresh);
            });
    }

    function paintGrid(micro) {
        const start = parseISODate(micro.start_date);
        const today = new Date();
        const sessionsByDate = {};
        (micro.sessions || []).forEach(function (s) {
            (sessionsByDate[s.date] = sessionsByDate[s.date] || []).push(s);
        });

        let html = "";
        for (let i = 0; i < 7; i++) {
            const d = addDays(start, i);
            const iso = toISODate(d);
            const sessions = sessionsByDate[iso] || [];
            sessions.sort(function (a, b) { return a.order_in_day - b.order_in_day; });
            const isToday = isSameDay(d, today);

            // Map workout_type to category modifier class for unified coloring.
            const catModifier = {
                strength: 'is-strength',
                metcon: 'is-cardio',
                conditioning: 'is-recovery',
                skill: 'is-nutrition',
                mixed: 'is-recovery'
            };

            const sessionHtml = sessions.length
                ? sessions.map(function (s) {
                    const wtLabel = s.workout_type ? t("schedule.workout_type." + s.workout_type) : "?";
                    const title = focusDisplayLabel(s.focus) || wtLabel;
                    const timeMeta = formatSessionTimeMeta(s);
                    const shiftBadge = Sh().buildGridBadge(s);
                    const isRest = s.status === "skipped";
                    const catCls = isRest ? '' : (catModifier[s.workout_type] || 'is-recovery');
                    const st = resolveSessionStatus(s);
                    const statusLabel = t("schedule.session.status_" + st.key);
                    const completedCls = s.completed ? " is-completed" : "";
                    const previewHtml = sessionMovementPreviewHtml(s);
                    const tmpl = s.generated_template_id ? getTemplate(s.generated_template_id) : null;
                    const tipAttr = tmpl ? ` data-bs-title="${escAttr(buildSessionTooltip(tmpl))}"` : "";
                    const quickStart = renderSessionQuickStart(s);
                    const quickCls = quickStart ? " is-quickstartable" : "";
                    const tplAttr = s.generated_template_id ? ` data-template-id="${s.generated_template_id}"` : "";
                    const quickTab = quickStart ? ` tabindex="0" aria-label="${CHOS.escape(title)}. ${CHOS.escape(t("schedule.session.double_tap_title"))}"` : "";
                    return `
                        <div class="chos-session-item ${catCls}${completedCls}${quickCls} ${isRest ? 'is-rest' : ''}" data-session-id="${s.id}"${tplAttr}${tipAttr}${quickTab}>
                            <div class="chos-session-item__layout">
                                ${quickStart}
                                <div class="chos-session-item__body">
                            <div class="d-flex align-items-start justify-content-between gap-1 mb-1">
                                <span class="chos-session-item__title"${quickStart ? ` title="${CHOS.escape(t("schedule.session.double_tap_title"))}"` : ""}>${title}</span>
                                <span class="chos-session-status ${st.cls}">${statusLabel}</span>
                            </div>
                            ${previewHtml}
                            <div class="chos-session-item__meta d-flex align-items-center justify-content-between mt-1 gap-1">
                                <div class="d-flex align-items-center gap-1 flex-wrap min-w-0">
                                    <span class="chos-cat ${catCls}" style="font-size: 0.65rem;">${wtLabel.toUpperCase()}</span>
                                    ${shiftBadge}
                                </div>
                                ${timeMeta ? `<span class="text-secondary small num flex-shrink-0"><i class="fas fa-clock me-1"></i>${CHOS.escape(timeMeta)}</span>` : ""}
                            </div>
                                </div>
                            </div>
                        </div>`;
                }).join("")
                : `<div class="d-flex flex-column align-items-center justify-content-center h-100" style="min-height: 80px;">
                       <div class="text-secondary small fst-italic mb-2">${t("schedule.session.rest")}</div>
                       <button class="chos-btn chos-btn-ghost chos-btn-sm" onclick="event.stopPropagation(); ScheduleUI.toggleRestDay('${iso}')" title="${t("schedule.btn.mark_rest_day")}"><i class="fas fa-bed me-1"></i>${t("schedule.btn.rest_label")}</button>
                   </div>`;

            const dragEnabled = sessions.length <= 1;
            const todayCls = isToday ? 'chos-day-today' : '';
            const dayStart = new Date(d); dayStart.setHours(0, 0, 0, 0);
            const todayStart = new Date(today); todayStart.setHours(0, 0, 0, 0);
            const pastCls = dayStart < todayStart ? 'chos-day-past' : '';
            const trainingSessions = sessions.filter(function (s) { return s.status !== "skipped"; });
            const doneCls = trainingSessions.length > 0 && trainingSessions.every(function (s) { return s.completed; })
                ? ' chos-day-done' : '';
            html += `
                <div class="chos-day-cell">
                    <div class="chos-card chos-day-card ${todayCls}${doneCls} ${pastCls} h-100" onclick="ScheduleUI.openDayDrawer('${iso}')" style="cursor:pointer" role="button" tabindex="0" aria-label="${CHOS.escape(formatShortPt(d))}">
                        <div class="card-body" style="padding: var(--space-3);">
                            <div class="d-flex align-items-center justify-content-between mb-2">
                                <span class="fw-semibold small ${isToday ? 'text-primary' : 'text-secondary'}" style="text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.7rem;">${formatShortPt(d)}</span>
                                ${doneCls ? `<span class="chos-day-done-badge" title="${t("schedule.session.status_completed")}"><i class="fas fa-check-circle"></i></span>`
                                    : isToday ? `<span class="chos-badge chos-badge-primary" style="font-size: 0.65rem;">${t("schedule.today_suffix")}</span>` : ""}
                            </div>
                            <div class="chos-day-dropzone" data-date="${iso}" data-drag-enabled="${dragEnabled}">${sessionHtml}</div>
                        </div>
                    </div>
                </div>`;
        }
        document.getElementById("calendar-grid").innerHTML = html;
        renderNextWorkoutBanner(micro);
        if (CHOS.trainNow) CHOS.trainNow.updateFromMicro(micro);
        renderWeekStats(micro);
        prefetchWeekTemplates(micro);
        wireDragAndDrop();
        wireGridQuickStart();
        wireSessionTooltips();
        scrollToTodayCell();
        const prevMicro = findAdjacentMicro(micro, -1);
        document.getElementById("btn-copy-prev").disabled = !prevMicro;
    }

    function scrollToTodayCell() {
        const todayCard = document.querySelector(".chos-day-card.chos-day-today");
        if (!todayCard) return;
        const cell = todayCard.closest(".chos-day-cell");
        if (!cell) return;
        const grid = document.getElementById("calendar-grid");
        if (!grid || grid.scrollWidth <= grid.clientWidth) return;
        cell.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
    }

    // ----- Drag-and-drop session move/swap ----------------------------------
    function wireDragAndDrop() {
        if (typeof Sortable === "undefined") return;
        const zones = document.querySelectorAll(".chos-day-dropzone");
        zones.forEach(function (zone) {
            if (zone.dataset.dragEnabled !== "true") return;
            // Make session items themselves open the drawer for their day.
            // Without this, the session item fills the day card on mobile and
            // taps don't reach the cell's onclick=openDayDrawer. Sortable
            // works on drag (mousedown→move→mouseup), so binding `click`
            // here doesn't conflict with drag-and-drop.
            zone.querySelectorAll(".chos-session-item").forEach(function (item) {
                item.addEventListener("click", function (ev) {
                    if (ev.target.closest("[data-action='quickstart']")) return;
                    if (ev.target.closest(".chos-session-item__body, .chos-session-item__title") && item.classList.contains("is-quickstartable")) {
                        ev.stopPropagation();
                        return;
                    }
                    ev.stopPropagation();
                    const date = zone.getAttribute("data-date");
                    if (date) openDayDrawer(date);
                });
            });
            Sortable.create(zone, {
                group: "chos-days",
                draggable: ".chos-session-item",
                animation: 150,
                ghostClass: "sortable-ghost",
                chosenClass: "sortable-chosen",
                dragClass: "sortable-drag",
                delay: 120,
                delayOnTouchOnly: true,
                touchStartThreshold: 4,
                onStart: function () {
                    document.body.classList.add("chos-schedule-dragging");
                },
                onEnd: function () {
                    document.body.classList.remove("chos-schedule-dragging");
                },
                onAdd: function (evt) {
                    const fromZone = evt.from;
                    const toZone = evt.to;
                    const movedItem = evt.item;
                    const sourceId = movedItem.getAttribute("data-session-id");
                    const targetDate = toZone.getAttribute("data-date");
                    // The destination's pre-existing session, if any. After
                    // SortableJS inserts the moved item, any sibling .chos-session-item
                    // that isn't the moved one is the swap target.
                    const sibling = Array.from(toZone.querySelectorAll(".chos-session-item"))
                        .find(function (el) { return el !== movedItem; });
                    const targetId = sibling ? sibling.getAttribute("data-session-id") : null;
                    submitSwap(sourceId, targetDate, targetId);
                },
            });
        });
    }

    let gridQuickStartBound = false;
    const TITLE_TAP_MS = 320;
    const titleTapState = { sessionId: null, lastTap: 0, timer: null };

    function cancelTitleTapTimer() {
        if (titleTapState.timer) {
            clearTimeout(titleTapState.timer);
            titleTapState.timer = null;
        }
    }

    function openDrawerForSessionItem(item) {
        const zone = item && item.closest(".chos-day-dropzone");
        const date = zone && zone.getAttribute("data-date");
        if (date) openDayDrawer(date);
    }

    function quickStartTapTarget(ev) {
        const item = ev.target.closest(".chos-session-item.is-quickstartable");
        if (!item || ev.target.closest("[data-action='quickstart']")) return null;
        if (!ev.target.closest(".chos-session-item__body, .chos-session-item__title")) return null;
        return item;
    }

    function wireGridQuickStart() {
        const grid = document.getElementById("calendar-grid");
        if (!grid || gridQuickStartBound) return;
        gridQuickStartBound = true;

        grid.addEventListener("click", function (ev) {
            const btn = ev.target.closest("[data-action='quickstart']");
            if (btn) {
                ev.preventDefault();
                ev.stopPropagation();
                cancelTitleTapTimer();
                const sessionId = btn.getAttribute("data-session-id");
                if (sessionId) quickStart(sessionId, btn);
                return;
            }

            const item = quickStartTapTarget(ev);
            if (!item) return;
            ev.preventDefault();
            ev.stopPropagation();
            const sessionId = item.getAttribute("data-session-id");
            if (!sessionId) return;

            if (ev.detail >= 2) {
                cancelTitleTapTimer();
                titleTapState.sessionId = null;
                titleTapState.lastTap = 0;
                quickStart(sessionId);
                return;
            }

            const now = Date.now();
            if (titleTapState.sessionId === sessionId && titleTapState.lastTap && (now - titleTapState.lastTap) < TITLE_TAP_MS) {
                cancelTitleTapTimer();
                titleTapState.sessionId = null;
                titleTapState.lastTap = 0;
                quickStart(sessionId);
                return;
            }

            titleTapState.sessionId = sessionId;
            titleTapState.lastTap = now;
            cancelTitleTapTimer();
            titleTapState.timer = setTimeout(function () {
                titleTapState.timer = null;
                titleTapState.sessionId = null;
                titleTapState.lastTap = 0;
                openDrawerForSessionItem(item);
            }, TITLE_TAP_MS);
        }, true);

        grid.addEventListener("dblclick", function (ev) {
            const item = quickStartTapTarget(ev);
            if (!item) return;
            ev.preventDefault();
            ev.stopPropagation();
            cancelTitleTapTimer();
            titleTapState.sessionId = null;
            titleTapState.lastTap = 0;
            const sessionId = item.getAttribute("data-session-id");
            if (sessionId) quickStart(sessionId);
        }, true);

        grid.addEventListener("keydown", function (ev) {
            if (ev.key !== "Enter" && ev.key !== " ") return;
            const item = ev.target.closest(".chos-session-item.is-quickstartable");
            if (!item || !item.contains(ev.target)) return;
            if (ev.target.closest("[data-action='quickstart']")) return;
            ev.preventDefault();
            ev.stopPropagation();
            cancelTitleTapTimer();
            const sessionId = item.getAttribute("data-session-id");
            if (sessionId) quickStart(sessionId);
        });
    }

    function submitSwap(sourceId, targetDate, targetId) {
        if (!state.currentMicro) return;
        const microId = state.currentMicro.id;
        const payload = { source_id: sourceId, target_date: targetDate };
        if (targetId) payload.target_id = targetId;
        CHOS.api.post(`/api/v1/schedule/microcycles/${microId}/sessions/swap`, payload)
            .done(function () {
                CHOS.toast.success(t("schedule.toast.session_moved"));
                loadActiveMacro();
            })
            .fail(function (xhr) {
                CHOS.toast.error(xhr.responseJSON?.detail || t("schedule.toast.session_move_error"));
                loadActiveMacro();
            });
    }

    function findAdjacentMicro(current, delta) {
        if (!state.macrocycle) return null;
        const list = state.macrocycle.microcycles;
        const targetIdx = current.week_index_in_macro + delta;
        return list.find(function (m) { return m.week_index_in_macro === targetIdx; });
    }

    // ----- Week navigation ---------------------------------------------------
    function navigateWeek(delta) {
        if (!state.currentMicro || !state.macrocycle) return;
        const nextMicro = findAdjacentMicro(state.currentMicro, delta);
        if (!nextMicro) {
            CHOS.toast.info(delta < 0 ? t("schedule.toast.first_week") : t("schedule.toast.last_week"));
            return;
        }
        state.currentMicro = nextMicro;
        state.viewDate = parseISODate(nextMicro.start_date);
        renderWeek();
    }

    function jumpToMicro(microId) {
        if (!state.macrocycle) return;
        const target = (state.macrocycle.microcycles || []).find(function (m) {
            return String(m.id) === String(microId);
        });
        if (!target) return;
        state.currentMicro = target;
        state.viewDate = parseISODate(target.start_date);
        renderWeek();
    }

    function goToToday() {
        if (!state.macrocycle) return;
        const today = new Date();
        const target = state.macrocycle.microcycles.find(function (m) {
            const s = parseISODate(m.start_date), e = parseISODate(m.end_date);
            return today >= s && today <= e;
        });
        if (!target) { CHOS.toast.info(t("schedule.toast.today_outside_macro")); return; }
        state.currentMicro = target;
        state.viewDate = parseISODate(target.start_date);
        renderWeek();
    }

    // ----- Macrocycle creation ----------------------------------------------
    function refreshBlockPlanPreview() {
        const method = document.getElementById("macro-input-methodology").value;
        const plan = METHODOLOGY_PLANS[method] || [];
        const startStr = document.getElementById("macro-input-start").value;
        const start = startStr ? parseISODate(startStr) : mondayOf(new Date());
        if (!startStr) {
            document.getElementById("block-plan-preview").innerHTML = `<div class="text-muted">${t("schedule.modal.block_plan_pick_date")}</div>`;
            return;
        }
        let html = "", cursor = new Date(start), weekIdx = 0;
        if (!plan.length) {
            html = `<div class="text-muted">${t("schedule.modal.block_plan_custom_hint")}</div>`;
        } else {
            plan.forEach(function (b) {
                const blockStart = new Date(cursor);
                const blockEnd = addDays(cursor, b.weeks * 7 - 1);
                cursor = addDays(blockEnd, 1);
                weekIdx += b.weeks;
                html += `<div class="mb-1">
                    <span class="chos-badge chos-badge-primary">${CHOS.escape(blockTypeLabel(b.type))}</span>
                    <span class="text-muted ms-2">${t("schedule.modal.weeks_short", { n: b.weeks })}</span>
                    <span class="text-muted ms-2">${formatLongPt(blockStart)} – ${formatLongPt(blockEnd)}</span>
                </div>`;
            });
            html += `<div class="mt-2 fw-bold">${t("schedule.modal.block_plan_total", { n: weekIdx })}</div>`;
        }
        document.getElementById("block-plan-preview").innerHTML = html;
    }

    function showCreateMacrocycle() {
        // If an active macrocycle exists, ask what to do
        if (state.macrocycle) {
            const end = parseISODate(state.macrocycle.end_date);
            document.getElementById("confirm-macro-name").textContent = state.macrocycle.name;
            document.getElementById("confirm-macro-dates").textContent =
                formatLongPt(parseISODate(state.macrocycle.start_date)) +
                " – " + formatLongPt(end);
            // Pre-compute the posterior start date (day after current ends)
            const posteriorStart = addDays(end, 1);
            document.getElementById("btn-macro-posterior").dataset.posteriorDate = toISODate(posteriorStart);
            new bootstrap.Modal("#macroConfirmModal").show();
            return;
        }
        // No active macrocycle — open directly
        refreshBlockPlanPreview();
        new bootstrap.Modal("#createMacroModal").show();
    }

    function openCreateMacroPosterior() {
        const posteriorDate = document.getElementById("btn-macro-posterior").dataset.posteriorDate;
        document.getElementById("macro-input-start").value = posteriorDate;
        bootstrap.Modal.getInstance("#macroConfirmModal").hide();
        refreshBlockPlanPreview();
        new bootstrap.Modal("#createMacroModal").show();
    }

    function openCreateMacroSubstituir() {
        bootstrap.Modal.getInstance("#macroConfirmModal").hide();
        refreshBlockPlanPreview();
        new bootstrap.Modal("#createMacroModal").show();
    }

    function saveMacrocycle() {
        const name = document.getElementById("macro-input-name").value.trim() || "My Macrocycle";
        const methodology = document.getElementById("macro-input-methodology").value;
        const startStr = document.getElementById("macro-input-start").value;
        const goal = document.getElementById("macro-input-goal").value.trim() || null;
        const minutes = parseInt(document.getElementById("macro-input-minutes").value, 10);
        const days = parseInt(document.getElementById("macro-input-days").value, 10);
        if (!startStr) { CHOS.toast.error(t("schedule.toast.macro_start_required")); return; }

        const payload = {
            name,
            methodology,
            start_date: startStr,
            goal,
            available_minutes_per_session: minutes,
            training_days_per_week: days,
        };
        const plan = METHODOLOGY_PLANS[methodology];
        if (plan && plan.length) payload.block_plan = plan;

        CHOS.loading.button("#btn-save-macro", true);
        CHOS.api.post("/api/v1/schedule/macrocycles", payload)
            .done(function () {
                CHOS.toast.success(t("schedule.toast.macro_created"));
                bootstrap.Modal.getInstance("#createMacroModal").hide();
                loadActiveMacro();
            })
            .fail(function (xhr) {
                CHOS.toast.error(xhr.responseJSON?.detail || t("schedule.toast.macro_create_error"));
            })
            .always(function () { CHOS.loading.button("#btn-save-macro", false); });
    }

    // ----- Toggle rest day (mark/unmark a training day as rest) -----------
    function toggleRestDay(isoDate) {
        if (!state.currentMicro) return;
        const allSessions = state.currentMicro.sessions || [];
        const restMarker = allSessions.find(function(s){return s.date === isoDate && s.status === "skipped";});
        if (restMarker) {
            CHOS.api.delete(`/api/v1/schedule/planned-sessions/${restMarker.id}`)
                .done(function(){ loadActiveMacro(); })
                .fail(function(){ CHOS.toast.error(t("schedule.toast.rest_remove_error")); });
        } else {
            CHOS.api.post(`/api/v1/schedule/microcycles/${state.currentMicro.id}/sessions`, {
                date: isoDate,
                order_in_day: 1,
                shift: "morning",
                duration_minutes: 15,
                focus: t("schedule.session.rest"),
                status: "skipped",
            })
                .done(function(){ loadActiveMacro(); })
                .fail(function(){ CHOS.toast.error(t("schedule.toast.rest_set_error")); });
        }
    }

    // ----- Day drawer (CRUD sessions) ---------------------------------------
    function openDayDrawer(isoDate) {
        if (!state.currentMicro) return;
        state.drawerDate = isoDate;
        const d = parseISODate(isoDate);
        document.getElementById("drawer-title").textContent =
            tDate(d, { weekday: "long", day: "numeric", month: "long" });

        const allSessions = state.currentMicro.sessions || [];
        const existing = allSessions.filter(function (s) { return s.date === isoDate; });
        existing.sort(function (a, b) { return a.order_in_day - b.order_in_day; });
        state.drawerSessions = existing.map(function (s) {
            return { ...s, _isNew: false, _deleted: false };
        });
        renderDrawerSessions();
        new bootstrap.Modal("#dayDrawer").show();
    }

    // ----- Template loading (with cache) --------------------------------
    function getTemplate(templateId) {
        return state.templateCache[templateId] || null;
    }

    function loadTemplate(templateId) {
        if (!templateId || state.templateCache[templateId]) return;
        CHOS.api.get(`/api/v1/training/templates/${templateId}`).then(function(data) {
            state.templateCache[templateId] = data;
            renderDrawerSessions(); // re-render with loaded template
        }).catch(function(err) {
            console.error("Failed to load template", templateId, err);
        });
    }

    // Movement names from the API arrive in snake_case (back_squat). Convert
    // to "Back Squat" for display so users don't see internal identifiers.
    function humanize(s) {
        if (!s) return '';
        return String(s)
            .replace(/_/g, ' ')
            .replace(/\b\w/g, c => c.toUpperCase());
    }

    // Format seconds as "1:00" / "30s" — used for block_rest_seconds.
    function fmtSeconds(s) {
        if (s == null) return '';
        const n = parseInt(s, 10);
        if (!Number.isFinite(n)) return '';
        if (n >= 60) {
            const m = Math.floor(n / 60), r = n % 60;
            return r === 0 ? `${m}:00` : `${m}:${String(r).padStart(2, '0')}`;
        }
        return `${n}s`;
    }

    // Render a single movement row (without group wrapping).
    function renderMovementRow(m) {
        const e = CHOS.escape;
        const chips = [];
        if (m.sets)             chips.push(`<span class="chos-badge chos-badge-primary">${e(m.sets)}×</span>`);
        if (m.reps)             chips.push(`<span class="text-body num">${e(m.reps)} ${e(m.reps_unit || 'reps')}</span>`);
        if (m.weight_kg)        chips.push(`<span class="text-secondary num">@ ${e(m.weight_kg)} kg</span>`);
        if (m.duration_seconds) chips.push(`<span class="text-secondary num">${e(m.duration_seconds)}s</span>`);
        if (m.distance_meters)  chips.push(`<span class="text-secondary num">${e(m.distance_meters)}m</span>`);
        if (m.intensity)        chips.push(`<span class="chos-badge" style="background: var(--cat-recovery); color: #fff;">${e(m.intensity)}</span>`);

        const restLine = m.rest
            ? `<div class="text-secondary small mt-1"><i class="fas fa-pause-circle me-1"></i>${t("schedule.drawer.rest")}: ${e(m.rest)}</div>`
            : '';
        const notesLine = m.notes
            ? `<div class="text-secondary small fst-italic mt-1">${e(m.notes)}</div>`
            : '';
        const videoIcon = typeof CHOS.movementVideoIcon === 'function'
            ? CHOS.movementVideoIcon(m.movement) : '';

        return `
            <div class="py-2" style="border-bottom: 1px solid var(--color-border);">
                <div class="d-flex flex-wrap align-items-center gap-2">
                    <span class="fw-semibold text-body">${e(humanize(m.movement))}</span>
                    ${videoIcon}
                    <span class="ms-auto d-flex flex-wrap align-items-center gap-2">${chips.join(' ')}</span>
                </div>
                ${restLine}
                ${notesLine}
            </div>`;
    }

    function renderMovements(movements) {
        if (!movements || !movements.length) {
            return `<div class="text-secondary small fst-italic">${t("schedule.drawer.no_movements")}</div>`;
        }
        const e = CHOS.escape;

        // Group consecutive movements that share the same block_id —
        // an AMRAP/EMOM/metcon should render as one section with one
        // header, not as N separate cards each repeating the prescription.
        // Movements without block_id (legacy AI templates) fall through
        // to ungrouped rows so the renderer stays backwards-compatible.
        const groups = [];
        let current = null;
        movements.forEach(function (m) {
            const key = m.block_id || `__solo_${groups.length}_${(current ? current.movements.length : 0)}`;
            if (!current || current.key !== key) {
                current = {
                    key: key,
                    label: m.block_label || '',
                    prescription: m.block_prescription || '',
                    intent: m.block_intent || '',
                    rest: m.block_rest_seconds,
                    movements: [],
                    grouped: !!m.block_id,
                };
                groups.push(current);
            }
            current.movements.push(m);
        });

        return groups.map(function (g) {
            // Solo (legacy / no block_id): render the row plain.
            if (!g.grouped) {
                return g.movements.map(renderMovementRow).join('');
            }
            // Header chips. block_label is rendered as a small upper-case
            // category, prescription as a primary badge, intent as italic.
            const labelChip = g.label
                ? `<span class="text-secondary small" style="text-transform: uppercase; letter-spacing: 0.04em;">${e(humanize(g.label))}</span>`
                : '';
            const prescriptionChip = g.prescription
                ? `<span class="chos-badge chos-badge-primary num">${e(g.prescription)}</span>`
                : '';
            const intentLine = g.intent
                ? `<div class="text-body small fst-italic mt-1">${e(g.intent)}</div>`
                : '';
            const restFooter = g.rest
                ? `<div class="text-secondary small mt-2 pt-2" style="border-top: 1px dashed var(--color-border);"><i class="fas fa-pause-circle me-1"></i>${t("schedule.drawer.rest_between_sets")}: <span class="num">${fmtSeconds(g.rest)}</span></div>`
                : '';

            return `
                <div class="chos-card mb-3" style="background: var(--surface-sunken); border: 1px solid var(--color-border);">
                    <div class="card-body" style="padding: var(--space-3);">
                        <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
                            ${labelChip}
                            ${prescriptionChip}
                        </div>
                        ${intentLine}
                        <div class="mt-2">
                            ${g.movements.map(renderMovementRow).join('')}
                        </div>
                        ${restFooter}
                    </div>
                </div>`;
        }).join('');
    }

    function renderWorkoutDetail(template) {
        const e = CHOS.escape;
        const movementsHtml = renderMovements(template.movements || []);
        const warmup    = template.warm_up || template.warmup || '';
        const stimulus  = template.target_stimulus || '';
        const equipment = (template.equipment_required || []).join(', ');
        const difficulty = template.difficulty_level || 'rx';

        // Compact info row built from optional metadata. Each entry has an
        // icon + a single label/value pair so the eye scans top-to-bottom
        // instead of parsing bold-text-with-colon.
        const meta = [];
        if (stimulus) {
            const stimText = isKnownStimulus(stimulus) ? S().label(stimulus) : stimulus;
            meta.push(`<div class="d-flex align-items-start gap-2">
                <i class="fas fa-bullseye text-secondary mt-1" style="width: 16px;"></i>
                <div><div class="small text-secondary fw-medium">${t("schedule.drawer.stimulus")}</div>
                <div class="text-body small">${e(stimText)}</div></div>
            </div>`);
        }
        if (warmup) {
            meta.push(`<div class="d-flex align-items-start gap-2">
                <i class="fas fa-fire text-secondary mt-1" style="width: 16px;"></i>
                <div><div class="small text-secondary fw-medium">${t("schedule.drawer.warmup")}</div>
                <div class="text-body small">${e(warmup)}</div></div>
            </div>`);
        }
        meta.push(`<div class="d-flex align-items-start gap-2">
            <i class="fas fa-dumbbell text-secondary mt-1" style="width: 16px;"></i>
            <div><div class="small text-secondary fw-medium">${t("schedule.drawer.equipment")}</div>
            <div class="text-body small">${e(equipment || t("schedule.drawer.no_equipment"))}</div></div>
        </div>`);
        meta.push(`<div class="d-flex align-items-start gap-2">
            <i class="fas fa-signal text-secondary mt-1" style="width: 16px;"></i>
            <div><div class="small text-secondary fw-medium">${t("schedule.drawer.difficulty")}</div>
            <div><span class="chos-badge chos-badge-primary text-uppercase">${e(difficulty)}</span></div></div>
        </div>`);

        return `
            <div class="rounded mt-2" style="background: var(--surface-sunken); padding: var(--space-3); border-left: 3px solid var(--cat-recovery);">
                ${template.description ? `<p class="small text-body mb-3">${e(template.description)}</p>` : ''}
                <div class="row g-3 mb-3">
                    ${meta.map(m => `<div class="col-6">${m}</div>`).join('')}
                </div>
                <div class="small text-secondary fw-medium mb-1" style="text-transform: uppercase; letter-spacing: 0.04em;">${t("schedule.drawer.movements")}</div>
                <div>${movementsHtml}</div>
            </div>`;
    }

    function renderDrawerSessions() {
        const container = document.getElementById("drawer-sessions");
        if (!state.drawerSessions.length) {
            container.innerHTML = `<div class="text-secondary fst-italic">${t("schedule.drawer.no_sessions")}</div>`;
            return;
        }

        let html = "";
        state.drawerSessions.forEach(function (s, idx) {
            if (s._deleted) return;
            const sessionShift = Sh().isValid(s.shift) ? s.shift : "morning";

            const template = s.generated_template_id ? getTemplate(s.generated_template_id) : null;
            const templateLoading = s.generated_template_id && !state.templateCache[s.generated_template_id];
            const workoutDetail = template ? renderWorkoutDetail(template) : '';
            const loadingSpinner = templateLoading
                ? '<span class="spinner-border spinner-border-sm text-primary ms-2" role="status" aria-hidden="true"></span>'
                : '';
            const workoutBlock = (workoutDetail || templateLoading)
                ? `<details class="chos-drawer-workout mb-3"${workoutDetail ? " open" : ""}>
                        <summary class="chos-drawer-workout__summary">
                            <i class="fas fa-dumbbell me-1"></i>${t("schedule.drawer.workout_content")}
                            ${loadingSpinner}
                        </summary>
                        <div class="chos-drawer-workout__body mt-2">
                            ${workoutDetail || `<div class="text-secondary small fst-italic">${t("schedule.toast.session_load_error")}</div>`}
                        </div>
                   </details>`
                : "";

            // Color the session header by workout type so the eye groups them.
            const catModifier = {
                strength: 'is-strength', metcon: 'is-cardio', conditioning: 'is-recovery',
                skill: 'is-nutrition', mixed: 'is-recovery'
            };
            const catCls = catModifier[s.workout_type] || 'is-recovery';
            const wtLabel = s.workout_type ? t("schedule.workout_type." + s.workout_type) : "?";
            const focusText = focusDisplayLabel(s.focus) || t("schedule.drawer.focus_unset");
            const scheduleChip = formatSessionScheduleMeta(s);

            // Start button — only meaningful when a workout template has
            // been generated for this session. Clicking it stashes the
            // template in sessionStorage and routes to /dashboard/workouts
            // which auto-opens the tracking modal.
            const startBtn = (s.generated_template_id && !s.completed)
                ? `<button class="chos-btn chos-btn-primary chos-btn-sm" onclick="ScheduleUI.startSession(${idx})" aria-label="${t("schedule.drawer.start_session")}" title="${t("schedule.drawer.start_session")}">
                       <i class="fas fa-play me-1"></i><span class="d-none d-sm-inline">${t("schedule.drawer.start_session")}</span>
                   </button>`
                : (s.completed
                    ? `<span class="chos-session-status is-completed">${t("schedule.session.status_completed")}</span>`
                    : '');

            html += `
                <div class="chos-card mb-3" data-idx="${idx}">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <span class="chos-cat ${catCls} fw-semibold">
                                ${t("schedule.drawer.session_n", { n: s.order_in_day })}
                            </span>
                            <div class="d-flex align-items-center gap-2">
                                ${startBtn}
                                <button class="chos-btn chos-btn-ghost chos-btn-sm" onclick="ScheduleUI.deleteSessionRow(${idx})" aria-label="${t("schedule.drawer.delete_session")}">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>

                        ${workoutBlock}

                        <div class="d-flex flex-wrap gap-2 mb-3" data-session-summary>
                            <span class="chos-chip"><span class="chip-dot"></span><i class="fas fa-clock me-1 text-secondary" style="font-size:0.7rem;"></i>${CHOS.escape(scheduleChip)}</span>
                            <span class="chos-chip ${catCls}"><span class="chip-dot"></span>${CHOS.escape(wtLabel)}</span>
                            <span class="chos-chip"><span class="chip-dot"></span><i class="fas fa-bullseye me-1 text-secondary" style="font-size:0.7rem;"></i>${CHOS.escape(focusText)}</span>
                        </div>

                        <div class="small text-secondary fw-medium mt-3 mb-2" style="text-transform: uppercase; letter-spacing: 0.04em;">${t("schedule.drawer.session_settings")}</div>
                        <div class="row g-3">
                            <div class="col-12">
                                <label class="chos-label">${t("schedule.drawer.field_shift")}</label>
                                <div data-shift-picker class="mb-2">
                                    ${Sh().buildPickerHtml(sessionShift)}
                                </div>
                                <div class="row g-3">
                                    <div class="col-sm-6">
                                        <label class="chos-label">${t("schedule.drawer.field_start_time")}</label>
                                        <input type="time" class="chos-input" data-field="start_time" value="${s.start_time ? s.start_time.slice(0,5) : ""}">
                                    </div>
                                    <div class="col-sm-6">
                                        <label class="chos-label">${t("schedule.drawer.field_duration")}</label>
                                        <div data-duration-picker>
                                            ${D().buildPickerHtml(s.duration_minutes || getMacroDefaultDuration(), durationPickerOptions())}
                                        </div>
                                    </div>
                                </div>
                                <div class="form-text text-secondary small mt-1">${t("schedule.drawer.shift_time_hint")}</div>
                            </div>
                            <div class="col-12 chos-session-pickers">
                                <label class="chos-label">${t("schedule.drawer.field_type")}</label>
                                <div data-type-picker class="mb-3">
                                    ${S().buildWorkoutTypePickerHtml(s.workout_type)}
                                </div>
                                <label class="chos-label">${t("schedule.drawer.field_focus")}</label>
                                <div data-focus-picker>
                                    ${S().buildPickerHtml(s.focus, s.workout_type, { placeholder: t("schedule.drawer.focus_placeholder") })}
                                </div>
                                <div class="form-text text-secondary small mt-1">${t("schedule.drawer.focus_hint")}</div>
                            </div>
                        </div>
                    </div>
                </div>`;
        });
        container.innerHTML = html;

        // Kick off template loads for any session that has a generated_template_id
        state.drawerSessions.forEach(function(s) {
            if (s.generated_template_id && !state.templateCache[s.generated_template_id]) {
                loadTemplate(s.generated_template_id);
            }
        });
    }

    function addSessionRow() {
        const usedOrders = state.drawerSessions.filter(function(s){return !s._deleted;}).map(function(s){return s.order_in_day;});
        let nextOrder = 1;
        while (usedOrders.includes(nextOrder) && nextOrder <= 5) nextOrder++;
        if (nextOrder > 5) { CHOS.toast.warning(t("schedule.toast.max_sessions_per_day")); return; }

        const newSession = {
            date: state.drawerDate,
            order_in_day: nextOrder,
            shift: "morning",
            start_time: "06:00",
            duration_minutes: getMacroDefaultDuration(),
            workout_type: "mixed",
            focus: "",
            _isNew: true,
            _deleted: false,
        };
        state.drawerSessions.push(newSession);
        const payload = {
            date: newSession.date,
            order_in_day: newSession.order_in_day,
            shift: newSession.shift,
            start_time: newSession.start_time,
            duration_minutes: newSession.duration_minutes,
            workout_type: newSession.workout_type,
            focus: null,
        };
        CHOS.api.post(`/api/v1/schedule/microcycles/${state.currentMicro.id}/sessions`, payload)
            .done(function (created) {
                Object.assign(newSession, created, { _isNew: false });
                renderDrawerSessions();
                renderWeek();
            })
            .fail(function (xhr) {
                CHOS.toast.error(xhr.responseJSON?.detail || t("schedule.toast.session_add_error"));
                state.drawerSessions = state.drawerSessions.filter(function (s) { return s !== newSession; });
                renderDrawerSessions();
            });
    }

    function deleteSessionRow(idx) {
        const s = state.drawerSessions[idx];
        if (!s.id) {
            state.drawerSessions.splice(idx, 1);
            renderDrawerSessions();
            return;
        }
        if (!confirm(t("schedule.confirm.delete_session"))) return;
        CHOS.api.delete(`/api/v1/schedule/planned-sessions/${s.id}`)
            .done(function () {
                s._deleted = true;
                renderDrawerSessions();
                renderWeek();
            })
            .fail(function () { CHOS.toast.error(t("schedule.toast.session_delete_error")); });
    }

    function persistSession(session) {
        if (!session.id) return;
        const payload = {
            shift: isValidShift(session.shift) ? session.shift : "morning",
            start_time: session.start_time,
            duration_minutes: session.duration_minutes,
            workout_type: session.workout_type,
            focus: session.focus || null,
        };
        CHOS.api.patch(`/api/v1/schedule/planned-sessions/${session.id}`, payload)
            .done(function () { renderWeek(); })
            .fail(function () { CHOS.toast.error(t("schedule.toast.session_save_error")); });
    }

    // ----- Generate / copy ---------------------------------------------------
    function generateWeek() {
        if (!state.currentMicro) return;
        CHOS.loading.button("#btn-generate-week", true);
        CHOS.api.post(`/api/v1/schedule/microcycles/${state.currentMicro.id}/generate`, {})
            .done(function (data) {
                CHOS.toast.success(t("schedule.toast.generated_count", { n: data.generated_sessions }));
                renderWeek();
            })
            .fail(function (xhr) {
                CHOS.toast.error(xhr.responseJSON?.detail || t("schedule.toast.generate_error"));
            })
            .always(function () { CHOS.loading.button("#btn-generate-week", false); });
    }

    function copyFromPreviousWeek() {
        if (!state.currentMicro) return;
        const prev = findAdjacentMicro(state.currentMicro, -1);
        if (!prev) return;
        if (!confirm(t("schedule.confirm.copy_previous"))) return;
        CHOS.api.post(`/api/v1/schedule/microcycles/${state.currentMicro.id}/copy-from/${prev.id}`, {})
            .done(function () { CHOS.toast.success(t("schedule.toast.copied")); renderWeek(); })
            .fail(function () { CHOS.toast.error(t("schedule.toast.copy_error")); });
    }

    function quickStart(sessionId, triggerEl) {
        const sessions = (state.currentMicro && state.currentMicro.sessions) || [];
        const s = sessions.find(function (x) { return String(x.id) === String(sessionId); });
        if (!s || !canQuickStartSession(s)) return;
        const btn = triggerEl || document.querySelector('[data-action="quickstart"][data-session-id="' + sessionId + '"]');
        if (btn) {
            btn.classList.add("is-loading");
            btn.setAttribute("aria-busy", "true");
            btn.disabled = true;
        }
        const done = function () {
            if (btn) {
                btn.classList.remove("is-loading");
                btn.removeAttribute("aria-busy");
                btn.disabled = false;
            }
        };
        const handoff = function (template) {
            CHOS.startWorkoutFromTemplate(
                Object.assign({}, template, { id: s.generated_template_id }),
                { planned_session_id: s.id }
            );
        };
        const cached = getTemplate(s.generated_template_id);
        if (cached) {
            handoff(cached);
            done();
            return;
        }
        CHOS.api.get(`/api/v1/training/templates/${s.generated_template_id}`)
            .done(function (template) {
                state.templateCache[s.generated_template_id] = template;
                handoff(template);
            })
            .fail(function () {
                done();
                CHOS.toast.error(t("schedule.toast.session_load_error"));
            });
    }

    function startSession(idx) {
        const s = state.drawerSessions[idx];
        if (!s || !s.generated_template_id) return;
        const handoff = function (template) {
            CHOS.startWorkoutFromTemplate(
                Object.assign({}, template, { id: s.generated_template_id }),
                { planned_session_id: s.id }
            );
        };
        const cached = getTemplate(s.generated_template_id);
        if (cached) {
            handoff(cached);
            return;
        }
        CHOS.api.get(`/api/v1/training/templates/${s.generated_template_id}`)
            .done(function (template) {
                state.templateCache[s.generated_template_id] = template;
                handoff(template);
            })
            .fail(function () {
                CHOS.toast.error(t("schedule.toast.session_load_error"));
            });
    }

    return {
        init: init,
        navigateWeek: navigateWeek,
        jumpToMicro: jumpToMicro,
        goToToday: goToToday,
        showCreateMacrocycle: showCreateMacrocycle,
        saveMacrocycle: saveMacrocycle,
        refreshBlockPlanPreview: refreshBlockPlanPreview,
        openDayDrawer: openDayDrawer,
        toggleRestDay: toggleRestDay,
        addSessionRow: addSessionRow,
        deleteSessionRow: deleteSessionRow,
        generateWeek: generateWeek,
        copyFromPreviousWeek: copyFromPreviousWeek,
        openCreateMacroPosterior: openCreateMacroPosterior,
        openCreateMacroSubstituir: openCreateMacroSubstituir,
        startSession: startSession,
        quickStart: quickStart,
    };
})();

// Expose the functions invoked from inline onclick handlers in schedule.html
function navigateWeek(d) { return ScheduleUI.navigateWeek(d); }
function goToToday() { return ScheduleUI.goToToday(); }
function showCreateMacrocycle() { return ScheduleUI.showCreateMacrocycle(); }
function saveMacrocycle() { return ScheduleUI.saveMacrocycle(); }
function refreshBlockPlanPreview() { return ScheduleUI.refreshBlockPlanPreview(); }
function toggleRestDay(iso) { return ScheduleUI.toggleRestDay(iso); }
function addSessionRow() { return ScheduleUI.addSessionRow(); }
function generateWeek() { return ScheduleUI.generateWeek(); }
function copyFromPreviousWeek() { return ScheduleUI.copyFromPreviousWeek(); }
function openCreateMacroPosterior() { return ScheduleUI.openCreateMacroPosterior(); }
function openCreateMacroSubstituir() { return ScheduleUI.openCreateMacroSubstituir(); }
