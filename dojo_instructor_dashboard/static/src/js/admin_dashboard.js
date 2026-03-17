/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { DojoVoiceAssistant } from "./voice_assistant";

class AdminDashboard extends Component {
    static template = "dojo_instructor_dashboard.AdminDashboard";
    static components = { DojoVoiceAssistant };

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.rootRef = useRef("root");

        this.state = useState({
            loading: true,
            summary: null,
            instructors: [],
            droppedStudents: [],
            recentSessions: [],
            recentStudents: [],
            studentPage: 0,
            // which section is expanded in dropped table
            droppedExpanded: false,
            sessionsExpanded: false,
        });

        onWillStart(() => this._loadData());

        onMounted(() => {
            // Walk up ancestors and unlock any overflow:hidden clips
            // (Odoo's .o_action and .o_action_manager both clip by default)
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
        const data = await this.orm.call(
            "dojo.instructor.profile",
            "get_admin_dashboard_data",
            []
        );
        this.state.summary        = data.summary;
        this.state.instructors    = data.instructors;
        this.state.droppedStudents = data.dropped_students;
        this.state.recentSessions  = data.recent_sessions;
        this.state.recentStudents  = data.recent_students || [];
        this.state.studentPage     = 0;
        this.state.loading        = false;
    }

    async _reload() {
        this.state.loading = true;
        await this._loadData();
    }

    // ── Formatters ─────────────────────────────────────────────────────

    /** "2025-03-15" → "Mar 15, 2025" */
    fmtDate(dateStr) {
        if (!dateStr || dateStr === "—") return "—";
        const [y, m, d] = dateStr.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
            month: "short", day: "numeric", year: "numeric",
        });
    }

    /** 78.3 → "78%" */
    pct(v) {
        if (v === null || v === undefined) return "—";
        return Math.round(v) + "%";
    }

    /** 1234.56 → "$1,235" */
    currency(v) {
        if (v === null || v === undefined) return "—";
        return new Intl.NumberFormat(undefined, {
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 0,
        }).format(v);
    }

    /** CSS class for a percentage bar fill */
    barFill(v) {
        return `width:${Math.min(Math.round(v || 0), 100)}%`;
    }

    /** Color class based on rate threshold */
    rateClass(v) {
        if (v === null || v === undefined) return "o_ad_rate_neutral";
        if (v >= 75) return "o_ad_rate_good";
        if (v >= 50) return "o_ad_rate_ok";
        return "o_ad_rate_bad";
    }

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

    membershipBadgeClass(s) {
        return {
            lead: "o_di_badge_secondary",
            trial: "o_ad_badge_info",
            active: "o_di_badge_success",
            paused: "o_ad_badge_warning",
            cancelled: "o_di_badge_danger",
        }[s] || "o_di_badge_secondary";
    }

    membershipLabel(s) {
        return {
            lead: "Lead",
            trial: "Trial",
            active: "Active",
            paused: "Paused",
            cancelled: "Cancelled",
        }[s] || s;
    }

    get todayLabel() {
        return new Date().toLocaleDateString(undefined, {
            weekday: "long", month: "long", day: "numeric", year: "numeric",
        });
    }

    get visibleDropped() {
        return this.state.droppedExpanded
            ? this.state.droppedStudents
            : this.state.droppedStudents.slice(0, 10);
    }

    get visibleSessions() {
        return this.state.sessionsExpanded
            ? this.state.recentSessions
            : this.state.recentSessions.slice(0, 15);
    }

    // ── Navigation helpers ─────────────────────────────────────────────
    openAllStudents()       { this.action.doAction("dojo_instructor_dashboard.action_all_students"); }
    openTodaysSessions()    { this.action.doAction("dojo_instructor_dashboard.action_all_sessions_today"); }
    openCalendar()          { this.action.doAction("dojo_instructor_dashboard.action_all_sessions_calendar"); }
    openInstructorKpis()    { this.action.doAction("dojo_instructor_dashboard.action_all_instructor_kpis"); }
    openInvoices() {
        this.action.doAction({
            type: "ir.actions.act_window",
            name: "Invoices",
            res_model: "account.move",
            view_mode: "list,form",
            views: [[false, "list"], [false, "form"]],
            domain: [["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
            target: "current",
        });
    }

    openInstructorRecord(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dojo.instructor.profile",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    toggleDropped()  { this.state.droppedExpanded  = !this.state.droppedExpanded; }
    toggleSessions() { this.state.sessionsExpanded = !this.state.sessionsExpanded; }

    openOnboarding() {
        this.action.doAction("dojo_onboarding.action_dojo_onboarding_wizard");
    }
    openNewMember() {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dojo.member",
            views: [[false, "form"]],
            target: "current",
        });
    }
    openBeltTests() {
        this.action.doAction("dojo_belt_progression.action_dojo_belt_tests");
    }
    openSubscriptions() {
        this.action.doAction("dojo_subscriptions.action_dojo_member_subscriptions");
    }
    openCommunications() {
        this.action.doAction("dojo_communications.action_dojo_send_message_wizard");
    }

    // ── Student carousel ──────────────────────────────────────────────
    static STUDENT_PAGE_SIZE = 8;

    get visibleStudents() {
        const ps = AdminDashboard.STUDENT_PAGE_SIZE;
        return this.state.recentStudents.slice(
            this.state.studentPage * ps,
            (this.state.studentPage + 1) * ps
        );
    }

    get totalStudentPages() {
        return Math.max(
            1,
            Math.ceil(this.state.recentStudents.length / AdminDashboard.STUDENT_PAGE_SIZE)
        );
    }

    prevStudentPage() {
        if (this.state.studentPage > 0) this.state.studentPage--;
    }

    nextStudentPage() {
        if (this.state.studentPage < this.totalStudentPages - 1) this.state.studentPage++;
    }

    openStudentProfile(memberId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dojo.member",
            res_id: memberId,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("dojo_admin_dashboard", AdminDashboard);
