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

    function shiftLabel(shift) {
        if (!shift) return "";
        return t("schedule.shift." + shift) || shift;
    }
    // Back-compat: existing code reads SHIFT_LABELS[s.shift]; resolve via t() so
    // values stay in sync with the active locale.
    const SHIFT_LABELS = new Proxy({}, {
        get: function (_target, prop) { return shiftLabel(prop); },
    });

    let state = {
        macrocycle: null,   // active macrocycle (with microcycles)
        currentMicro: null, // microcycle being displayed
        viewDate: null,     // a date inside the currently-displayed week
        drawerSessions: [], // sessions in the open drawer
        drawerDate: null,
        templateCache: {},  // template_id -> workout template data
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
        loadActiveMacro();
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
                    const shift = SHIFT_LABELS[s.shift] || (s.start_time ? s.start_time.slice(0, 5) : "");
                    const stateBadge = s.status === "generated"
                        ? `<span class="chos-badge chos-badge-success ms-1" title="${t("schedule.session.generated_tooltip")}"><i class="fas fa-check"></i></span>`
                        : s.status === "skipped"
                        ? `<span class="chos-badge ms-1" style="background: var(--surface-sunken); color: var(--color-text-secondary);" title="${t("schedule.session.rest_tooltip")}"><i class="fas fa-bed"></i></span>`
                        : "";
                    const wtLabel = s.workout_type ? t("schedule.workout_type." + s.workout_type) : "?";
                    const safeFocus = s.focus ? CHOS.escape(s.focus) : "";
                    const isRest = s.status === "skipped";
                    const catCls = isRest ? '' : (catModifier[s.workout_type] || 'is-recovery');
                    return `
                        <div class="chos-session-item ${catCls} ${isRest ? 'is-rest' : ''}" data-session-id="${s.id}">
                            <div class="d-flex align-items-center justify-content-between">
                                <span class="chos-cat ${catCls}" style="font-size: 0.75rem;">${wtLabel.toUpperCase()}</span>
                                ${stateBadge}
                            </div>
                            <div class="text-secondary small mt-1"><i class="fas fa-clock me-1"></i>${shift} · ${s.duration_minutes || "?"}${t("schedule.session.duration_min")}</div>
                            ${safeFocus ? `<div class="fst-italic small text-body mt-1">${safeFocus}</div>` : ""}
                        </div>`;
                }).join("")
                : `<div class="d-flex flex-column align-items-center justify-content-center h-100" style="min-height: 80px;">
                       <div class="text-secondary small fst-italic mb-2">${t("schedule.session.rest")}</div>
                       <button class="chos-btn chos-btn-ghost chos-btn-sm" onclick="event.stopPropagation(); ScheduleUI.toggleRestDay('${iso}')" title="${t("schedule.btn.mark_rest_day")}"><i class="fas fa-bed me-1"></i>${t("schedule.btn.rest_label")}</button>
                   </div>`;

            const dragEnabled = sessions.length <= 1;
            const todayCls = isToday ? 'chos-day-today' : '';
            html += `
                <div class="col-md">
                    <div class="chos-card chos-day-card ${todayCls} h-100" onclick="ScheduleUI.openDayDrawer('${iso}')" style="cursor:pointer">
                        <div class="card-body" style="padding: var(--space-3);">
                            <div class="d-flex align-items-center justify-content-between mb-2">
                                <span class="fw-semibold small ${isToday ? 'text-primary' : 'text-secondary'}" style="text-transform: uppercase; letter-spacing: 0.04em; font-size: 0.7rem;">${formatShortPt(d)}</span>
                                ${isToday ? `<span class="chos-badge chos-badge-primary" style="font-size: 0.65rem;">${t("schedule.today_suffix")}</span>` : ""}
                            </div>
                            <div class="chos-day-dropzone" data-date="${iso}" data-drag-enabled="${dragEnabled}">${sessionHtml}</div>
                        </div>
                    </div>
                </div>`;
        }
        document.getElementById("calendar-grid").innerHTML = html;
        wireDragAndDrop();

        // Enable "copy previous" only if there is a previous microcycle
        const prevMicro = findAdjacentMicro(micro, -1);
        document.getElementById("btn-copy-prev").disabled = !prevMicro;
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
                    <span class="chos-badge chos-badge-primary">${b.type}</span>
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
        document.getElementById("drawer-title").textContent = formatLongPt(d);

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
            meta.push(`<div class="d-flex align-items-start gap-2">
                <i class="fas fa-bullseye text-secondary mt-1" style="width: 16px;"></i>
                <div><div class="small text-secondary fw-medium">${t("schedule.drawer.stimulus")}</div>
                <div class="text-body small">${e(stimulus)}</div></div>
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

        const wtOptions = ["strength", "metcon", "skill", "conditioning", "mixed"];
        const shiftOptions = ["morning", "afternoon", "evening", "custom"];

        let html = "";
        state.drawerSessions.forEach(function (s, idx) {
            if (s._deleted) return;

            const template = s.generated_template_id ? getTemplate(s.generated_template_id) : null;
            const templateLoading = s.generated_template_id && !state.templateCache[s.generated_template_id];
            const workoutDetail = template ? renderWorkoutDetail(template) : '';
            const loadingSpinner = templateLoading
                ? '<div class="spinner-border spinner-border-sm text-primary ms-2" role="status" aria-hidden="true"></div>'
                : '';

            // Color the session header by workout type so the eye groups them.
            const catModifier = {
                strength: 'is-strength', metcon: 'is-cardio', conditioning: 'is-recovery',
                skill: 'is-nutrition', mixed: 'is-recovery'
            };
            const catCls = catModifier[s.workout_type] || 'is-recovery';

            // Start button — only meaningful when a workout template has
            // been generated for this session. Clicking it stashes the
            // template in sessionStorage and routes to /dashboard/workouts
            // which auto-opens the tracking modal.
            const startBtn = s.generated_template_id
                ? `<button class="chos-btn chos-btn-primary chos-btn-sm" onclick="ScheduleUI.startSession(${idx})" aria-label="${t("schedule.drawer.start_session")}" title="${t("schedule.drawer.start_session")}">
                       <i class="fas fa-play me-1"></i><span class="d-none d-sm-inline">${t("schedule.drawer.start_session")}</span>
                   </button>`
                : '';

            html += `
                <div class="chos-card mb-3" data-idx="${idx}">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center mb-3">
                            <span class="chos-cat ${catCls} fw-semibold">
                                ${t("schedule.drawer.session_n", { n: s.order_in_day })}
                                ${loadingSpinner}
                            </span>
                            <div class="d-flex align-items-center gap-2">
                                ${startBtn}
                                <button class="chos-btn chos-btn-ghost chos-btn-sm" onclick="ScheduleUI.deleteSessionRow(${idx})" aria-label="${t("schedule.drawer.delete_session")}">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>

                        ${workoutDetail}

                        <div class="small text-secondary fw-medium mt-3 mb-2" style="text-transform: uppercase; letter-spacing: 0.04em;">${t("schedule.drawer.session_settings")}</div>
                        <div class="row g-3">
                            <div class="col-md-3 col-6">
                                <label class="chos-label">${t("schedule.drawer.field_shift")}</label>
                                <select class="form-select" data-field="shift">
                                    ${shiftOptions.map(v => `<option value="${v}" ${s.shift === v ? "selected" : ""}>${t("schedule.shift." + v)}</option>`).join("")}
                                </select>
                            </div>
                            <div class="col-md-3 col-6">
                                <label class="chos-label">${t("schedule.drawer.field_start_time")}</label>
                                <input type="time" class="form-control" data-field="start_time" value="${s.start_time ? s.start_time.slice(0,5) : ""}">
                            </div>
                            <div class="col-md-3 col-6">
                                <label class="chos-label">${t("schedule.drawer.field_duration")}</label>
                                <div class="position-relative">
                                    <input type="number" class="form-control" data-field="duration_minutes" min="15" max="240" step="5" value="${s.duration_minutes || 60}" style="padding-right: 3.25rem;">
                                    <span class="position-absolute text-secondary small" style="right: 0.875rem; top: 50%; transform: translateY(-50%); pointer-events: none;">min</span>
                                </div>
                            </div>
                            <div class="col-md-3 col-6">
                                <label class="chos-label">${t("schedule.drawer.field_type")}</label>
                                <select class="form-select" data-field="workout_type">
                                    ${wtOptions.map(v => `<option value="${v}" ${s.workout_type === v ? "selected" : ""}>${t("schedule.workout_type." + v)}</option>`).join("")}
                                </select>
                            </div>
                            <div class="col-12">
                                <label class="chos-label">${t("schedule.drawer.field_focus")}</label>
                                <input type="text" class="form-control" data-field="focus" value="${CHOS.escape(s.focus || "")}" placeholder="${t("schedule.drawer.focus_placeholder")}">
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

        // Auto-save on field change
        container.querySelectorAll("[data-field]").forEach(function (el) {
            el.addEventListener("change", function (e) {
                const wrapper = e.target.closest("[data-idx]");
                const idx = parseInt(wrapper.dataset.idx, 10);
                const field = e.target.dataset.field;
                let value = e.target.value;
                if (field === "duration_minutes") value = parseInt(value, 10);
                state.drawerSessions[idx][field] = value || null;
                persistSession(state.drawerSessions[idx]);
            });
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
            duration_minutes: 60,
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
            shift: session.shift,
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

    // ----- Start a session from the drawer ----------------------------------
    function startSession(idx) {
        const s = state.drawerSessions[idx];
        if (!s || !s.generated_template_id) return;
        const cached = getTemplate(s.generated_template_id);
        if (cached) {
            CHOS.startWorkoutFromTemplate(cached);
            return;
        }
        // Template not in cache yet — fetch on demand, then handoff.
        CHOS.api.get(`/api/v1/training/templates/${s.generated_template_id}`)
            .done(function (template) {
                state.templateCache[s.generated_template_id] = template;
                CHOS.startWorkoutFromTemplate(template);
            })
            .fail(function () {
                CHOS.toast.error(t("schedule.toast.session_load_error"));
            });
    }

    return {
        init: init,
        navigateWeek: navigateWeek,
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
