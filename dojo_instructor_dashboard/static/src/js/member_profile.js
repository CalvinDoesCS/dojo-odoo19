/** @odoo-module **/

import { Component, useState, onWillStart, onMounted, useRef } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

class MemberProfile extends Component {
    static template = "dojo_instructor_dashboard.MemberProfile";
    static props = ["action", "actionType?"];

    setup() {
        this.orm    = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.rootRef = useRef("root");

        this.state = useState({
            loading: true,
            member: null,
            editOverlay: {
                open: false,
                saving: false,
                error: null,
                form: {
                    name: "",
                    email: "",
                    phone: "",
                    date_of_birth: "",
                    role: "",
                    blood_type: "",
                    allergies: "",
                    medical_notes: "",
                    emergency_note: "",
                },
            },
            subOverlay:  { open: false },
            beltOverlay: { open: false, saving: false },
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
        const memberId = this.props.action?.context?.active_id;
        if (!memberId) {
            this.state.loading = false;
            return;
        }
        const member = await this.orm.call(
            "dojo.member", "get_member_profile_data", [memberId]
        );
        this.state.member = (member && member.id) ? member : null;
        this.state.loading = false;
    }

    get memberId() {
        return this.props.action?.context?.active_id;
    }

    goBack() {
        window.history.back();
    }

    // ── Quick Actions ────────────────────────────────────────────────

    editMember() {
        if (!this.memberId) return;
        this.openEditOverlay();
    }

    openEditOverlay() {
        const m = this.state.member;
        if (!m) return;
        Object.assign(this.state.editOverlay.form, {
            name: m.name || "",
            email: m.email || "",
            phone: m.phone || "",
            date_of_birth: m.date_of_birth || "",
            role: m.role || "",
            blood_type: m.blood_type || "",
            allergies: m.allergies || "",
            medical_notes: m.medical_notes || "",
            emergency_note: m.emergency_note || "",
        });
        this.state.editOverlay.error = null;
        this.state.editOverlay.open = true;
    }

    closeEditOverlay() {
        this.state.editOverlay.open = false;
        this.state.editOverlay.error = null;
        this.state.editOverlay.saving = false;
    }

    async saveEditOverlay() {
        if (!this.memberId) return;
        this.state.editOverlay.saving = true;
        this.state.editOverlay.error = null;
        try {
            const f = this.state.editOverlay.form;
            await this.orm.write("dojo.member", [this.memberId], {
                name: f.name || false,
                email: f.email || false,
                phone: f.phone || false,
                date_of_birth: f.date_of_birth || false,
                role: f.role || "student",
                blood_type: f.blood_type || false,
                allergies: f.allergies || false,
                medical_notes: f.medical_notes || false,
                emergency_note: f.emergency_note || false,
            });
            await this._loadData();
            this.closeEditOverlay();
            this.notification.add("Member updated.", { type: "success" });
        } catch (e) {
            this.state.editOverlay.error = e.message || "An error occurred while saving.";
            this.state.editOverlay.saving = false;
        }
    }

    onEditFieldChange(ev) {
        const field = ev.target.dataset.field;
        if (field) {
            this.state.editOverlay.form[field] = ev.target.value;
        }
    }

    stopProp(ev) {
        ev.stopPropagation();
    }

    async addCredits() {
        if (!this.memberId) return;
        try {
            await this.action.doAction("dojo_credits.action_dojo_credit_grant_wizard", {
                additionalContext: { active_id: this.memberId, active_model: "dojo.member" },
            });
        } catch {
            this.notification.add("Credits module not configured.", { type: "warning" });
        }
    }

    viewSubscription() {
        if (!this.memberId) return;
        this.openSubOverlay();
    }

    openSubOverlay() {
        this.state.subOverlay.open = true;
    }

    closeSubOverlay() {
        this.state.subOverlay.open = false;
    }

    openSubFull() {
        const subId = this.state.member?.subscription?.id;
        if (subId) {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "dojo.member.subscription",
                res_id: subId,
                views: [[false, "form"]],
                target: "new",
            });
        } else {
            this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "dojo.member.subscription",
                views: [[false, "list"], [false, "form"]],
                domain: [["member_id", "=", this.memberId]],
                target: "new",
            });
        }
    }

    logAttendance() {
        if (!this.memberId) return;
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "dojo.attendance.log",
            views: [[false, "form"]],
            target: "new",
            context: { default_member_id: this.memberId },
        });
    }

    inviteBeltTest() {
        if (!this.memberId) return;
        this.openBeltOverlay();
    }

    openBeltOverlay() {
        this.state.beltOverlay.open = true;
    }

    closeBeltOverlay() {
        this.state.beltOverlay.open = false;
        this.state.beltOverlay.saving = false;
    }

    async toggleBeltTestInvite() {
        if (!this.memberId) return;
        this.state.beltOverlay.saving = true;
        try {
            const current = this.state.member?.test_invite_pending || false;
            await this.orm.write("dojo.member", [this.memberId], {
                test_invite_pending: !current,
            });
            await this._loadData();
            this.notification.add(
                !current ? "Belt test invite sent." : "Belt test invite removed.",
                { type: "success" }
            );
        } catch (e) {
            this.notification.add(
                e.message || "Could not update belt test invite.",
                { type: "danger" }
            );
        } finally {
            this.state.beltOverlay.saving = false;
        }
    }

    sendMessage() {
        this.contactGuardian(this.memberId);
    }

    contactGuardian(memberId) {
        const id = (memberId !== undefined && memberId !== null) ? memberId : this.memberId;
        if (!id) return;
        try {
            this.action.doAction("dojo_communications.action_dojo_send_message_wizard", {
                additionalContext: {
                    active_id: id,
                    active_model: "dojo.member",
                    active_ids: [id],
                    default_member_ids: [id],
                },
            });
        } catch {
            this.notification.add("Send message action not available.", { type: "warning" });
        }
    }

    // ── Date / Time helpers ──────────────────────────────────────────

    /** "2025-03-15 09:00:00" (UTC) → "Mar 15 · 9:00 AM" local */
    fmtDt(dtStr) {
        if (!dtStr) return "—";
        const d = new Date(dtStr.replace(" ", "T") + "Z");
        return d.toLocaleString(undefined, {
            month: "short", day: "numeric",
            hour: "numeric", minute: "2-digit",
        });
    }

    /** "YYYY-MM-DD" → "March 15, 2025" */
    fmtDate(dateStr) {
        if (!dateStr) return "—";
        const [y, m, d] = dateStr.split("-").map(Number);
        return new Date(y, m - 1, d).toLocaleDateString(undefined, {
            month: "long", day: "numeric", year: "numeric",
        });
    }

    // ── Label helpers ────────────────────────────────────────────────

    roleLabel(role) {
        return (
            { student: "Student", parent: "Parent", both: "Parent & Student" }[role]
            || role
        );
    }

    stateLabel(state) {
        return (
            { lead: "Lead", trial: "Trial", active: "Active", paused: "Paused", cancelled: "Cancelled" }[state]
            || state
        );
    }

    stateClass(state) {
        return (
            {
                lead:      "o_mp_state_lead",
                trial:     "o_mp_state_trial",
                active:    "o_mp_state_active",
                paused:    "o_mp_state_paused",
                cancelled: "o_mp_state_cancelled",
            }[state] || "o_mp_state_lead"
        );
    }

    subStateLabel(state) {
        return (
            {
                draft:     "Draft",
                active:    "Active",
                paused:    "Paused",
                cancelled: "Cancelled",
                expired:   "Expired",
            }[state] || state
        );
    }

    subStateClass(state) {
        return (
            {
                draft:     "o_di_badge_secondary",
                active:    "o_di_badge_success",
                paused:    "o_ad_badge_warning",
                cancelled: "o_di_badge_danger",
                expired:   "o_di_badge_danger",
            }[state] || "o_di_badge_secondary"
        );
    }

    attendanceClass(state) {
        return (
            {
                present: "o_di_badge_success",
                late:    "o_ad_badge_warning",
                absent:  "o_di_badge_danger",
                excused: "o_ad_badge_info",
                pending: "o_di_badge_secondary",
            }[state] || "o_di_badge_secondary"
        );
    }

    attendanceLabel(state) {
        return (
            { present: "Present", late: "Late", absent: "Absent", excused: "Excused", pending: "Pending" }[state]
            || state
        );
    }

    enrollmentLabel(status) {
        return (
            { registered: "Registered", waitlist: "Waitlist", cancelled: "Cancelled" }[status]
            || status
        );
    }

    creditTypeLabel(t) {
        return (
            { grant: "Grant", hold: "Hold", expiry: "Expiry", adjustment: "Adjustment" }[t]
            || t
        );
    }

    creditTypeClass(t) {
        return (
            {
                grant:      "o_di_badge_success",
                hold:       "o_ad_badge_warning",
                expiry:     "o_di_badge_danger",
                adjustment: "o_ad_badge_info",
            }[t] || "o_di_badge_secondary"
        );
    }

    creditStatusLabel(s) {
        return (
            { pending: "Pending", confirmed: "Confirmed", cancelled: "Cancelled" }[s]
            || s
        );
    }

    creditStatusClass(s) {
        return (
            {
                pending:   "o_ad_badge_warning",
                confirmed: "o_di_badge_success",
                cancelled: "o_di_badge_secondary",
            }[s] || "o_di_badge_secondary"
        );
    }

    // ── Belt helpers ─────────────────────────────────────────────────

    /**
     * Convert a belt color (hex or named) to a semi-transparent background
     * suitable for the hero badge.
     */
    rankBgColor(color) {
        if (!color) return "rgba(255,255,255,0.08)";
        // Simple opacity trick: wrap hex or named color with a fallback
        return "rgba(0,0,0,0.35)";
    }

    rankPct(done, threshold) {
        if (!threshold || threshold <= 0) return 0;
        return Math.min(100, Math.round((done / threshold) * 100));
    }

    rankProgressClass(done, threshold) {
        const pct = this.rankPct(done, threshold);
        if (pct >= 75) return "o_ad_bar_fill o_ad_rate_good";
        if (pct >= 40) return "o_ad_bar_fill o_ad_rate_ok";
        return "o_ad_bar_fill o_ad_rate_bad";
    }

    get imageUrl() {
        if (!this.state.member) return "";
        return `/web/image/dojo.member/${this.state.member.id}/image_1920`;
    }
}

registry.category("actions").add("dojo_member_profile", MemberProfile);

