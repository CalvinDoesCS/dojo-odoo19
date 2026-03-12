/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class InstructorDashboard extends Component {
    static template = "dojo_instructor_dashboard.InstructorDashboard";

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");

        this.state = useState({
            loading: true,
            profile: null,
            sessionsToday: [],
            upcomingSessions: [],
            todos: [],
        });

        onWillStart(() => this._loadData());

        onMounted(() => {
            const el = this.rootRef.el;
            if (!el) return;
            let node = el.parentElement;
            while (node && node !== document.body) {
                const computed = getComputedStyle(node);
                if (computed.overflow === "hidden" || computed.overflowY === "hidden") {
                    node.style.overflowY = "auto";
                }
                node = node.parentElement;
            }
        });
    }

    async _loadData() {
        const pad  = (n) => String(n).padStart(2, "0");
        const iso  = (d) => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
        const now  = new Date();
        const today    = iso(now);
        const tomorrow = iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1));
        const twoWeeks = iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 14));

        // Server resolves the current user — no client-side UID needed
        const profile = await this.orm.call(
            "dojo.instructor.profile", "get_my_profile_data", []
        );

        if (!profile) {
            this.state.loading = false;
            return;
        }

        this.state.profile = profile;

        const [sessionsToday, upcomingSessions, todos] = await Promise.all([
            this.orm.searchRead(
                "dojo.class.session",
                [
                    ["instructor_profile_id", "=", profile.id],
                    ["start_datetime", ">=", today + " 00:00:00"],
                    ["start_datetime", "<=", today + " 23:59:59"],
                ],
                ["template_id", "start_datetime", "end_datetime",
                 "capacity", "seats_taken", "state"],
                { order: "start_datetime asc" }
            ),
            this.orm.searchRead(
                "dojo.class.session",
                [
                    ["instructor_profile_id", "=", profile.id],
                    ["start_datetime", ">=", tomorrow + " 00:00:00"],
                    ["start_datetime", "<=", twoWeeks + " 23:59:59"],
                ],
                ["template_id", "start_datetime", "capacity", "seats_taken", "state"],
                { order: "start_datetime asc" }
            ),
            this.orm.searchRead(
                "project.task",
                [
                    ["user_ids", "in", [profile.user_id]],
                    ["stage_id.fold", "=", false],
                ],
                ["name", "project_id", "date_deadline", "priority", "stage_id"],
                { order: "date_deadline asc", limit: 25 }
            ),
        ]);

        this.state.sessionsToday    = sessionsToday;
        this.state.upcomingSessions = upcomingSessions;
        this.state.todos            = todos;
        this.state.loading          = false;
    }

    /** "2025-03-15 09:00:00" (UTC) → "Mar 15 · 9:00 AM" local */
    fmtDt(dtStr) {
        if (!dtStr) return "—";
        const d = new Date(dtStr.replace(" ", "T") + "Z");
        return d.toLocaleString(undefined, {
            month: "short", day: "numeric",
            hour: "numeric", minute: "2-digit",
        });
    }

    /** "2025-03-15" → "Mar 15, 2025" */
    fmtDate(dateStr) {
        if (!dateStr) return "—";
        const [y, m, d] = dateStr.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
            month: "short", day: "numeric", year: "numeric",
        });
    }

    /** "2025-03-15 09:00:00" (UTC) → "9:00 AM" local time only */
    fmtTime(dtStr) {
        if (!dtStr) return "—";
        const d = new Date(dtStr.replace(" ", "T") + "Z");
        return d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
    }

    /** Today's greeting */
    get greeting() {
        const h = new Date().getHours();
        if (h < 12) return "Good morning";
        if (h < 17) return "Good afternoon";
        return "Good evening";
    }

    /** Today's display date */
    get todayLabel() {
        return new Date().toLocaleDateString(undefined, {
            weekday: "long", month: "long", day: "numeric", year: "numeric",
        });
    }

    /** Fill rate as integer 0-100 */
    fillPct(s) { return s.capacity ? Math.round((s.seats_taken / s.capacity) * 100) : 0; }

    stateBadgeClass(s) {
        return {
            draft: "o_di_badge_secondary",
            open: "o_di_badge_success",
            done: "o_di_badge_primary",
            cancelled: "o_di_badge_danger",
        }[s] || "o_di_badge_secondary";
    }

    stateLabel(s) {
        return { draft: "Draft", open: "Open", done: "Done", cancelled: "Cancelled" }[s] || s;
    }

    openTodaysClasses()  { this.action.doAction("dojo_instructor_dashboard.action_my_sessions_today"); }
    openMyStudents()     { this.action.doAction("dojo_instructor_dashboard.action_my_students"); }
    openCalendar()       { this.action.doAction("dojo_instructor_dashboard.action_my_sessions_calendar"); }
    openTodos()          { this.action.doAction("dojo_instructor_dashboard.action_my_todos"); }
    openMarkAttendance() { this.action.doAction("dojo_instructor_dashboard.action_my_sessions_today"); }

    pct(rate) {
        if (rate === undefined || rate === null) return "—";
        return Math.round(rate) + "%";
    }

    async _reload() {
        this.state.loading = true;
        await this._loadData();
    }

    async openQuickAttendance(sessionId) {
        // Pre-create the wizard server-side via orm.call so default_get fires
        // with default_session_id in context and persists all enrolled students
        // as real DB line records. The dialog only sends WRITE commands after
        // that — member_id is always set.
        const wizardId = await this.orm.call(
            "dojo.attendance.quick.wizard",
            "create",
            [{}],
            { context: { default_session_id: sessionId } },
        );
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Mark Attendance",
            res_model: "dojo.attendance.quick.wizard",
            res_id: wizardId,
            view_mode: "form",
            views: [[false, "form"]],
            target: "new",
        }, {
            onClose: () => this._loadData(),
        });
    }
}

registry.category("actions").add("dojo_instructor_dashboard", InstructorDashboard);
