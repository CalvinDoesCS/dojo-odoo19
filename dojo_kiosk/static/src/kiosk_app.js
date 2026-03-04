/**
 * Dojo Kiosk — OWL Single Page Application (v2)
 * Loaded as a plain script (no Odoo module loader).
 * Depends on /web/static/lib/owl/owl.js being loaded first.
 * Mounts to #kiosk-root on /kiosk/<token>
 */
/* global owl */
const { Component, useState, onMounted, onWillUnmount, mount, xml } = owl;

// ─── Config identity (per-tablet token from URL) ─────────────────────────────
const KIOSK_TOKEN = window.KIOSK_TOKEN || null;

// ─── Utilities ────────────────────────────────────────────────────────────────

async function jsonPost(url, params = {}) {
    if (KIOSK_TOKEN) params = { token: KIOSK_TOKEN, ...params };
    const resp = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", method: "call", params }),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error.data?.message || data.error.message);
    return data.result;
}

function avatarUrl(memberId) {
    return `/web/image/dojo.member/${memberId}/image_128`;
}

function initials(name) {
    if (!name) return "?";
    const parts = name.trim().split(/\s+/);
    return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function formatTime(dtStr) {
    if (!dtStr) return "";
    const d = new Date(dtStr.replace(" ", "T") + "Z");
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(dtStr) {
    if (!dtStr) return "";
    const d = new Date(dtStr.replace(" ", "T") + "Z");
    const today = new Date();
    const isToday = d.toDateString() === today.toDateString();
    const tomorrow = new Date(today);
    tomorrow.setDate(today.getDate() + 1);
    const isTomorrow = d.toDateString() === tomorrow.toDateString();
    const timeStr = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (isToday) return "Today " + timeStr;
    if (isTomorrow) return "Tomorrow " + timeStr;
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + timeStr;
}

function todayIso() {
    const d = new Date();
    return d.getFullYear() + "-" +
        String(d.getMonth() + 1).padStart(2, "0") + "-" +
        String(d.getDate()).padStart(2, "0");
}

function contrastColor(hexColor) {
    if (!hexColor || hexColor.length < 6) return "#1a1a1a";
    const hex = hexColor.replace("#", "");
    const r = parseInt(hex.substring(0, 2), 16);
    const g = parseInt(hex.substring(2, 4), 16);
    const b = parseInt(hex.substring(4, 6), 16);
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    return lum > 0.5 ? "#1a1a1a" : "#ffffff";
}

// ─── PinModal ─────────────────────────────────────────────────────────────────

class PinModal extends Component {
    static template = xml`
        <div class="k-modal-overlay" t-on-click.self="props.onClose">
            <div class="k-modal k-modal--sm" style="max-width:360px;">
                <button class="k-modal__close" style="position:absolute;top:14px;right:14px;" t-on-click="props.onClose">✕</button>
                <p class="k-pin-title">Instructor Mode</p>
                <p class="k-pin-subtitle">Enter 6-digit PIN to unlock</p>

                <div class="k-pin-boxes">
                    <t t-foreach="[0,1,2,3,4,5]" t-as="i" t-key="i">
                        <div t-attf-class="k-pin-box
                            #{state.pin.length === i ? ' k-pin-box--active' : ''}
                            #{state.pin.length > i ? ' k-pin-box--filled' : ''}">
                            <t t-if="state.pin.length > i">●</t>
                        </div>
                    </t>
                </div>

                <div class="k-pin-numpad">
                    <t t-foreach="['1','2','3','4','5','6','7','8','9']" t-as="d" t-key="d">
                        <button class="k-pin-key" t-on-click="() => this.pressKey(d)">
                            <t t-esc="d"/>
                        </button>
                    </t>
                    <button class="k-pin-key k-pin-key--wide" t-on-click="() => this.pressKey('0')">0</button>
                    <button class="k-pin-key k-pin-key--backspace" t-on-click="backspace">⌫</button>
                </div>

                <p class="k-pin-error">
                    <t t-if="state.error" t-esc="state.error"/>
                </p>
            </div>
        </div>
    `;

    static props = ["onClose", "onSuccess"];

    setup() {
        this.state = useState({ pin: "", error: "" });
    }

    pressKey(digit) {
        if (this.state.pin.length >= 6) return;
        this.state.pin += digit;
        this.state.error = "";
        if (this.state.pin.length === 6) this._verify();
    }

    backspace() {
        this.state.pin = this.state.pin.slice(0, -1);
        this.state.error = "";
    }

    async _verify() {
        try {
            const result = await jsonPost("/kiosk/auth/pin", { pin: this.state.pin });
            if (result.success) {
                this.props.onSuccess();
            } else if (result.error === "locked") {
                const mins = result.retry_in_minutes || 15;
                this.state.error = `Too many attempts. Locked for ${mins} min.`;
                this.state.pin = "";
            } else {
                const tries = result.remaining_tries;
                this.state.error = tries
                    ? `Incorrect PIN. ${tries} attempt${tries === 1 ? "" : "s"} remaining.`
                    : "Incorrect PIN. Try again.";
                this.state.pin = "";
            }
        } catch {
            this.state.error = "Could not verify PIN. Check connection.";
            this.state.pin = "";
        }
    }
}

// ─── CheckinSuccessView ───────────────────────────────────────────────────────

class CheckinSuccessView extends Component {
    static template = xml`
        <div t-attf-class="k-success-view #{!props.success ? 'k-success-view--error' : ''}">
            <div class="k-success-icon">
                <t t-if="props.success">✅</t>
                <t t-else="">❌</t>
            </div>
            <div class="k-success-name" t-esc="props.memberName"/>
            <t t-if="props.success">
                <div class="k-success-session">
                    Checked in to <strong t-esc="props.sessionName"/>
                </div>
                <t t-if="props.programName">
                    <div class="k-success-program" t-esc="props.programName"/>
                </t>
                <t t-if="props.status === 'late'">
                    <div class="k-success-note k-success-note--late">⚠ Checked in late</div>
                </t>
                <t t-else="">
                    <div class="k-success-note">On time 🎉</div>
                </t>
            </t>
            <t t-else="">
                <div class="k-success-error" t-esc="props.errorMessage"/>
            </t>
            <div class="k-success-returning">Returning to kiosk…</div>
        </div>
    `;

    static props = ["success", "memberName", "sessionName", "programName", "status", "errorMessage", "onDone"];

    setup() {
        onMounted(() => { this._timer = setTimeout(() => this.props.onDone(), 4000); });
        onWillUnmount(() => clearTimeout(this._timer));
    }
}

// ─── IdleScreen ───────────────────────────────────────────────────────────────

class IdleScreen extends Component {
    static template = xml`
        <div class="k-idle-screen" t-on-click="wake" t-on-keydown="wake">
            <div class="k-idle-content">
                <t t-if="props.announcements and props.announcements.length">
                    <div class="k-idle-slide">
                        <div class="k-idle-slide__title" t-esc="currentAnnouncement().title"/>
                        <t t-if="currentAnnouncement().body">
                            <div class="k-idle-slide__body" t-esc="currentAnnouncement().body"/>
                        </t>
                    </div>
                    <div class="k-idle-dots">
                        <t t-foreach="props.announcements" t-as="a" t-key="a.id">
                            <div t-attf-class="k-idle-dot #{state.idx === a_index ? 'k-idle-dot--active' : ''}"/>
                        </t>
                    </div>
                </t>
                <t t-else="">
                    <div class="k-idle-slide">
                        <div class="k-idle-slide__dojo">🥋</div>
                        <div class="k-idle-slide__title">Welcome</div>
                        <div class="k-idle-slide__body">Tap to check in</div>
                    </div>
                </t>
                <div class="k-idle-tap-hint">Tap anywhere to continue</div>
            </div>
        </div>
    `;

    static props = ["announcements", "onWake"];

    setup() {
        this.state = useState({ idx: 0 });
        this._carouselTimer = null;
        onMounted(() => this._startCarousel());
        onWillUnmount(() => clearInterval(this._carouselTimer));
    }

    currentAnnouncement() {
        const ann = this.props.announcements;
        if (!ann || !ann.length) return { title: "Welcome", body: "Tap to check in" };
        return ann[this.state.idx % ann.length];
    }

    _startCarousel() {
        if (!this.props.announcements || this.props.announcements.length <= 1) return;
        this._carouselTimer = setInterval(() => {
            this.state.idx = (this.state.idx + 1) % this.props.announcements.length;
        }, 5000);
    }

    wake() { this.props.onWake(); }
}

// ─── MemberProfileCard ────────────────────────────────────────────────────────

class MemberProfileCard extends Component {
    static template = xml`
        <div class="k-modal-overlay" t-on-click.self="props.onClose">
            <div class="k-modal k-modal--profile">
                <button class="k-modal__close" style="position:absolute;top:14px;right:14px;z-index:1;" t-on-click="props.onClose">✕</button>

                <!-- ── Head ── -->
                <div class="k-profile__head">
                    <div class="k-profile__avatar-wrap">
                        <t t-if="props.member.image_url">
                            <img class="k-profile__avatar"
                                t-att-src="props.member.image_url"
                                t-att-alt="props.member.name"
                                t-on-error="onImgError"/>
                        </t>
                        <t t-else="">
                            <div class="k-profile__avatar-placeholder">
                                <t t-esc="initials(props.member.name)"/>
                            </div>
                        </t>
                    </div>
                    <div class="k-profile__head-info">
                        <div class="k-profile__name" t-esc="props.member.name"/>
                        <div class="k-profile__belt" t-esc="props.member.belt_rank || 'No Rank'"/>
                        <t t-if="props.member.membership_state">
                            <span t-attf-class="k-membership-badge k-membership-badge--#{props.member.membership_state}"
                                t-esc="props.member.membership_state"/>
                        </t>
                    </div>
                </div>

                <!-- ── Tab bar ── -->
                <div class="k-profile-tabs">
                    <button t-attf-class="k-profile-tab #{state.tab === 'profile' ? 'k-profile-tab--active' : ''}"
                        t-on-click="() => this.state.tab = 'profile'">Profile</button>
                    <button t-attf-class="k-profile-tab #{state.tab === 'progress' ? 'k-profile-tab--active' : ''}"
                        t-on-click="() => this.state.tab = 'progress'">Progress</button>
                    <button t-attf-class="k-profile-tab #{state.tab === 'household' ? 'k-profile-tab--active' : ''}"
                        t-on-click="() => this.state.tab = 'household'">Household</button>
                </div>

                <!-- ══ Profile tab ══ -->
                <t t-if="state.tab === 'profile'">
                    <div class="k-profile__scroll-body">
                        <t t-if="props.member.issues and props.member.issues.length">
                            <div class="k-warning-banner">
                                <div class="k-warning-banner__icon">!</div>
                                <div class="k-warning-banner__list">
                                    <t t-foreach="props.member.issues" t-as="issue" t-key="issue.code">
                                        <div class="k-warning-banner__item" t-esc="issue.label"/>
                                    </t>
                                </div>
                            </div>
                        </t>

                        <div class="k-profile__stats">
                            <div class="k-stat">
                                <span class="k-stat__value" t-esc="props.member.total_attendance"/>
                                <span class="k-stat__label">Total Classes</span>
                            </div>
                            <div class="k-stat">
                                <span class="k-stat__value">
                                    <t t-esc="props.member.sessions_used_this_week"/>
                                    <t t-if="props.member.sessions_allowed_per_week > 0">
                                        <span style="font-size:13px;font-weight:400;color:var(--k-text-3);">
                                            / <t t-esc="props.member.sessions_allowed_per_week"/>
                                        </span>
                                    </t>
                                </span>
                                <span class="k-stat__label">This Week</span>
                            </div>
                        </div>

                        <div class="k-profile-info">
                            <t t-if="props.member.date_of_birth">
                                <div class="k-info-row">
                                    <span class="k-info-row__label">Date of Birth</span>
                                    <span class="k-info-row__value" t-esc="props.member.date_of_birth"/>
                                </div>
                            </t>
                            <t t-if="props.member.plan_name">
                                <div class="k-info-row">
                                    <span class="k-info-row__label">Plan</span>
                                    <span class="k-info-row__value" t-esc="props.member.plan_name"/>
                                </div>
                            </t>
                            <t t-if="props.member.email">
                                <div class="k-info-row">
                                    <span class="k-info-row__label">Email</span>
                                    <span class="k-info-row__value" t-esc="props.member.email"/>
                                </div>
                            </t>
                            <t t-if="props.member.phone">
                                <div class="k-info-row">
                                    <span class="k-info-row__label">Phone</span>
                                    <span class="k-info-row__value" t-esc="props.member.phone"/>
                                </div>
                            </t>
                        </div>

                        <t t-if="props.member.appointments and props.member.appointments.length">
                            <div class="k-appointments">
                                <div class="k-appointments__title">Upcoming Classes</div>
                                <t t-foreach="props.member.appointments" t-as="appt" t-key="appt.session_id">
                                    <div class="k-appt-row">
                                        <div class="k-appt-row__name" t-esc="appt.name"/>
                                        <div class="k-appt-row__time" t-esc="formatDateTime(appt.start)"/>
                                    </div>
                                </t>
                            </div>
                        </t>
                    </div>

                    <div class="k-profile__actions">
                        <t t-if="props.instructorMode">
                            <div class="k-att-section">
                                <div class="k-att-section__label">Mark Attendance</div>
                                <div class="k-att-toggle--lg">
                                    <button
                                        t-attf-class="k-att-btn--lg #{props.member.attendance_state === 'present' ? 'k-att-btn--active-present' : ''}"
                                        t-on-click="() => this.markAttendance('present')">✓ Present</button>
                                    <button
                                        t-attf-class="k-att-btn--lg #{props.member.attendance_state === 'late' ? 'k-att-btn--active-late' : ''}"
                                        t-on-click="() => this.markAttendance('late')">~ Late</button>
                                    <button
                                        t-attf-class="k-att-btn--lg #{props.member.attendance_state === 'absent' ? 'k-att-btn--active-absent' : ''}"
                                        t-on-click="() => this.markAttendance('absent')">✕ Absent</button>
                                </div>
                            </div>
                            <div class="k-profile__roster-row">
                                <t t-if="!props.member.enrolled_in_session">
                                    <button class="k-btn k-btn--secondary" t-on-click="onRosterAdd">+ Add to Roster</button>
                                </t>
                                <t t-else="">
                                    <button class="k-btn k-btn--danger" t-on-click="onRosterRemove">− Remove from Roster</button>
                                </t>
                            </div>
                        </t>
                        <t t-else="">
                            <t t-if="props.member.attendance_state === 'present' or props.member.attendance_state === 'late'">
                                <div class="k-checkout-section">
                                    <div class="k-checkout-checkedin">✓ Already checked in</div>
                                    <button class="k-btn k-btn--checkout" t-on-click="onCheckout">Check Out</button>
                                </div>
                            </t>
                            <t t-elif="!props.sessionId">
                                <p style="text-align:center;color:var(--k-text-3);font-size:13px;">
                                    Select a session to check in.
                                </p>
                            </t>
                            <t t-elif="props.member.issues and props.member.issues.length">
                                <button class="k-btn k-btn--primary" t-on-click="onCheckin">Check In Anyway</button>
                            </t>
                            <t t-else="">
                                <button class="k-btn k-btn--primary" t-on-click="onCheckin">Check In</button>
                            </t>
                        </t>
                    </div>
                </t>

                <!-- ══ Progress tab ══ -->
                <t t-if="state.tab === 'progress'">
                    <div class="k-profile__scroll-body">
                        <div class="k-progress">
                            <div class="k-progress__stat">
                                <span class="k-progress__stat-value" t-esc="props.member.attendance_since_last_rank || 0"/>
                                <span class="k-progress__stat-label">Classes Since Last Belt Test</span>
                            </div>
                            <t t-if="props.member.programs and props.member.programs.length">
                                <div class="k-progress__programs-title">Programs</div>
                                <t t-foreach="props.member.programs" t-as="prog" t-key="prog.program_name">
                                    <div class="k-progress__prog-row">
                                        <div class="k-progress__prog-name" t-esc="prog.program_name"/>
                                        <div class="k-progress__prog-right">
                                            <t t-if="prog.rank_name">
                                                <span class="k-progress__rank-badge"
                                                    t-attf-style="background:#{prog.rank_color || '#e5e7eb'};color:#{computeContrast(prog.rank_color)};"
                                                    t-esc="prog.rank_name"/>
                                            </t>
                                            <span class="k-progress__att-count">
                                                <t t-esc="prog.attendance_count"/> classes
                                            </span>
                                        </div>
                                    </div>
                                </t>
                            </t>
                            <t t-else="">
                                <div class="k-empty" style="padding:24px 0;">
                                    <div class="k-empty__icon">🥋</div>
                                    <div class="k-empty__text">No rank history</div>
                                </div>
                            </t>
                        </div>
                    </div>
                </t>

                <!-- ══ Household tab ══ -->
                <t t-if="state.tab === 'household'">
                    <div class="k-profile__scroll-body">
                        <t t-if="props.member.household">
                            <div class="k-hh">
                                <div class="k-hh__name">🏠 <t t-esc="props.member.household.name"/></div>
                                <div class="k-hh__section-title">Members</div>
                                <div class="k-hh__members">
                                    <t t-foreach="props.member.household.members" t-as="hm" t-key="hm.id">
                                        <div class="k-hh__member-row">
                                            <div class="k-hh__member-avatar">
                                                <t t-esc="initials(hm.name)"/>
                                            </div>
                                            <div class="k-hh__member-info">
                                                <div class="k-hh__member-name" t-esc="hm.name"/>
                                                <div class="k-hh__member-role" t-esc="hm.role || ''"/>
                                            </div>
                                        </div>
                                    </t>
                                </div>
                                <t t-if="props.member.household.emergency_contacts and props.member.household.emergency_contacts.length">
                                    <div class="k-hh__section-title">Emergency Contacts</div>
                                    <div class="k-hh__contacts">
                                        <t t-foreach="props.member.household.emergency_contacts" t-as="ec" t-key="ec_index">
                                            <div class="k-hh__contact">
                                                <div class="k-hh__contact-header">
                                                    <span class="k-hh__contact-name" t-esc="ec.name"/>
                                                    <t t-if="ec.is_primary">
                                                        <span class="k-hh__contact-primary">Primary</span>
                                                    </t>
                                                </div>
                                                <div class="k-hh__contact-rel" t-esc="ec.relationship"/>
                                                <t t-if="ec.phone">
                                                    <a t-att-href="'tel:' + ec.phone" class="k-hh__contact-phone">
                                                        📞 <t t-esc="ec.phone"/>
                                                    </a>
                                                </t>
                                            </div>
                                        </t>
                                    </div>
                                </t>
                            </div>
                        </t>
                        <t t-else="">
                            <div class="k-empty" style="padding:40px 0;">
                                <div class="k-empty__icon">🏠</div>
                                <div class="k-empty__text">No household on file</div>
                            </div>
                        </t>
                    </div>
                </t>

            </div>
        </div>
    `;

    static props = ["member", "sessionId", "instructorMode", "onClose", "onCheckin", "onMarkAttendance", "onRosterAdd", "onRosterRemove", "onCheckout"];

    setup() {
        this.state = useState({ tab: "profile" });
    }

    initials(name) { return initials(name); }
    formatDateTime(dt) { return formatDateTime(dt); }
    computeContrast(hex) { return contrastColor(hex); }
    onImgError(ev) { ev.target.style.display = "none"; }
    markAttendance(status) { this.props.onMarkAttendance(this.props.member, this.props.sessionId, status); }
    onCheckin() { this.props.onCheckin(this.props.member, this.props.sessionId); }
    onCheckout() { this.props.onCheckout(this.props.member, this.props.sessionId); }
    onRosterAdd() { this.props.onRosterAdd(this.props.member, this.props.sessionId); this.props.onClose(); }
    onRosterRemove() { this.props.onRosterRemove(this.props.member, this.props.sessionId); this.props.onClose(); }
}

// ─── HomeContent ──────────────────────────────────────────────────────────────

class HomeContent extends Component {
    static template = xml`
        <div class="k-home">
            <t t-if="!props.query and !props.loading">
                <div class="k-home__prompt">
                    <div class="k-home__prompt-icon">🥋</div>
                    <div class="k-home__prompt-title">Welcome!</div>
                    <div class="k-home__prompt-sub">Type your name in the search bar above to check in</div>
                </div>
            </t>
            <t t-elif="props.loading">
                <div class="k-home__searching">
                    <div class="k-spinner k-spinner--lg"/>
                </div>
            </t>
            <t t-elif="props.results.length">
                <div class="k-results-grid">
                    <t t-foreach="props.results" t-as="m" t-key="m.member_id">
                        <MemberCard member="m" onSelect="props.onSelect"/>
                    </t>
                </div>
            </t>
            <t t-else="">
                <div class="k-home__no-results">
                    <div class="k-home__no-results-icon">🔍</div>
                    <div>No members found for "<span t-esc="props.query"/>"</div>
                </div>
            </t>
        </div>
    `;
    static props = ["query", "results", "loading", "onSelect"];
    static components = {};
}

// ─── MemberCard (icon tile) ──────────────────────────────────────────────────

class MemberCard extends Component {
    static template = xml`
        <div class="k-member-tile" t-on-click="() => props.onSelect(props.member)">
            <div class="k-member-tile__avatar-wrap">
                <img class="k-member-tile__avatar"
                    t-att-src="avatarUrl(props.member.member_id)"
                    t-att-alt="props.member.name"
                    t-on-error="onImgError"/>
            </div>
            <div class="k-member-tile__name" t-esc="props.member.name"/>
        </div>
    `;
    static props = ["member", "onSelect"];
    avatarUrl(id) { return avatarUrl(id); }
    onImgError(ev) {
        const img = ev.target;
        const ph = document.createElement("div");
        ph.className = "k-member-tile__initials";
        ph.textContent = initials(this.props.member.name);
        img.parentElement.replaceChild(ph, img);
    }
}

HomeContent.components = { MemberCard };

// ─── StudentCheckinModal ─────────────────────────────────────────────────────

class StudentCheckinModal extends Component {
    static template = xml`
        <div class="k-modal-overlay" t-on-click.self="onOverlayClick">
            <div class="k-modal k-modal--checkin">

                <!-- Member head (always shown) -->
                <div class="k-checkin-modal__head">
                    <div class="k-checkin-modal__avatar-wrap">
                        <img class="k-checkin-modal__avatar"
                            t-att-src="avatarUrl(props.member.member_id)"
                            t-att-alt="props.member.name"
                            t-on-error="onImgError"/>
                    </div>
                    <div class="k-checkin-modal__name" t-esc="props.member.name"/>
                    <t t-if="props.member.belt_rank">
                        <div class="k-checkin-modal__belt" t-esc="props.member.belt_rank"/>
                    </t>
                </div>

                <!-- ── Result view (checkin or checkout success/error) ── -->
                <t t-if="props.result">
                    <div class="k-checkin-modal__success">
                        <t t-if="props.result.success">
                            <div class="k-checkin-modal__success-msg">
                                <t t-if="props.result.type === 'checkout'">✓ You have been checked out</t>
                                <t t-else="">✓ You have been checked in</t>
                            </div>
                            <div class="k-checkin-modal__success-session" t-esc="props.result.sessionName"/>
                            <t t-if="props.result.type !== 'checkout'">
                                <div class="k-checkin-modal__success-chips">
                                    <t t-if="props.result.programName">
                                        <span class="k-checkin-modal__success-chip" t-esc="props.result.programName"/>
                                    </t>
                                    <t t-if="props.member.belt_rank">
                                        <span class="k-checkin-modal__success-chip" t-esc="props.member.belt_rank"/>
                                    </t>
                                </div>
                            </t>
                        </t>
                        <t t-else="">
                            <div class="k-checkin-modal__success-msg k-checkin-modal__success-msg--error">
                                ✕ <t t-esc="props.result.error || 'Action failed'"/>
                            </div>
                        </t>
                        <div class="k-checkin-modal__success-returning">Returning to kiosk…</div>
                    </div>
                </t>

                <!-- ── Checkout confirmation (already checked in) ── -->
                <t t-elif="props.checkedInSession">
                    <div class="k-checkin-modal__checkout">
                        <div class="k-checkin-modal__checkout-status">✓ Already checked in</div>
                        <div class="k-checkin-modal__checkout-session" t-esc="props.checkedInSession.template_name || props.checkedInSession.name"/>
                        <t t-if="props.checkedInSession.program_name">
                            <div class="k-checkin-modal__checkout-program" t-esc="props.checkedInSession.program_name"/>
                        </t>
                        <div class="k-checkin-modal__checkout-time">
                            <t t-esc="formatTime(props.checkedInSession.start)"/> – <t t-esc="formatTime(props.checkedInSession.end)"/>
                        </div>
                        <button class="k-btn k-checkin-modal__checkout-btn"
                            t-on-click="() => props.onCheckout(props.checkedInSession)">
                            Check Out
                        </button>
                    </div>
                    <div class="k-checkin-modal__notme-wrap">
                        <button class="k-btn k-checkin-modal__notme-btn" t-on-click="props.onClose">
                            That's not me
                        </button>
                    </div>
                </t>

                <!-- ── Class selection ── -->
                <t t-else="">
                    <div class="k-checkin-modal__prompt">Please select your class:</div>

                    <t t-if="props.loading">
                        <div class="k-checkin-modal__loading">
                            <div class="k-spinner k-spinner--lg"/>
                        </div>
                    </t>
                    <t t-elif="!props.sessions.length">
                        <div class="k-checkin-modal__empty">
                            <div style="font-size:2.5rem;margin-bottom:8px;">📅</div>
                            <div>No classes scheduled for today.</div>
                        </div>
                    </t>
                    <t t-else="">
                        <div class="k-checkin-modal__sessions">
                            <t t-foreach="props.sessions" t-as="s" t-key="s.id">
                                <button class="k-checkin-session-btn" t-on-click="() => props.onSelect(s)">
                                    <div class="k-checkin-session-btn__name" t-esc="s.template_name || s.name"/>
                                    <t t-if="s.program_name">
                                        <div class="k-checkin-session-btn__program" t-esc="s.program_name"/>
                                    </t>
                                    <div class="k-checkin-session-btn__time">
                                        <t t-esc="formatTime(s.start)"/> – <t t-esc="formatTime(s.end)"/>
                                    </div>
                                    <t t-if="s.instructor">
                                        <div class="k-checkin-session-btn__instructor">👤 <t t-esc="s.instructor"/></div>
                                    </t>
                                </button>
                            </t>
                        </div>
                    </t>

                    <!-- Not me button -->
                    <div class="k-checkin-modal__notme-wrap">
                        <button class="k-btn k-checkin-modal__notme-btn" t-on-click="props.onClose">
                            That's not me
                        </button>
                    </div>
                </t>

            </div>
        </div>
    `;

    static props = ["member", "sessions", "loading", "result", "checkedInSession", "onSelect", "onCheckout", "onClose"];
    onOverlayClick() { if (!this.props.result) this.props.onClose(); }
    avatarUrl(id) { return avatarUrl(id); }
    formatTime(dt) { return formatTime(dt); }
    onImgError(ev) {
        const img = ev.target;
        const ph = document.createElement("div");
        ph.className = "k-checkin-modal__avatar-placeholder";
        ph.textContent = initials(this.props.member.name);
        img.parentElement.replaceChild(ph, img);
    }
}

// ─── InstructorRosterTile ─────────────────────────────────────────────────────

class InstructorRosterTile extends Component {
    static template = xml`
        <div t-attf-class="k-roster-tile k-roster-tile--#{props.entry.attendance_state || 'pending'}"
             t-on-pointerdown="onPointerDown"
             t-on-pointerup="onPointerUp"
             t-on-pointercancel="onPointerUp"
             t-on-contextmenu.prevent="">

            <!-- Warning badge: top-right — membership issue or known flags -->
            <t t-if="hasWarning()">
                <div class="k-roster-tile__warn" title="Account issues">⚠</div>
            </t>

            <!-- Remove button: top-left (when present or late) -->
            <t t-if="props.entry.attendance_state === 'present' or props.entry.attendance_state === 'late'">
                <button class="k-roster-tile__remove"
                    t-on-click.stop="onRemove"
                    t-on-pointerdown.stop=""
                    title="Remove attendance">✕</button>
            </t>

            <!-- Mark present button: bottom-right (when pending/absent) -->
            <t t-elif="props.entry.attendance_state === 'pending' or props.entry.attendance_state === 'absent' or !props.entry.attendance_state">
                <button class="k-roster-tile__check"
                    t-on-click.stop="onCheck"
                    t-on-pointerdown.stop=""
                    title="Mark present">✓</button>
            </t>

            <div class="k-roster-tile__photo-wrap">
                <img class="k-roster-tile__photo"
                    t-att-src="avatarUrl(props.entry.member_id)"
                    t-att-alt="props.entry.name"
                    t-on-error="onImgError"/>
            </div>

            <div class="k-roster-tile__name" t-esc="props.entry.name"/>
        </div>
    `;

    static props = ["entry", "sessionId", "onMark", "onProfile", "onRemoveAttendance"];

    setup() { this._pressTimer = null; }

    avatarUrl(id) { return avatarUrl(id); }

    hasWarning() {
        // Check explicit issue flags first
        if (this.props.entry.issues && this.props.entry.issues.length) return true;
        // Fall back to checking membership_state if present in roster entry
        const state = this.props.entry.membership_state;
        return state && state !== "active" && state !== "trial";
    }

    onPointerDown(ev) {
        if (ev.target.closest(".k-roster-tile__check, .k-roster-tile__remove")) return;
        clearTimeout(this._pressTimer);
        this._pressTimer = setTimeout(() => {
            this._pressTimer = null;
            this.props.onProfile(this.props.entry.member_id);
        }, 500);
    }

    onPointerUp() {
        clearTimeout(this._pressTimer);
        this._pressTimer = null;
    }

    onCheck() { this.props.onMark(this.props.entry.member_id, "present"); }
    onRemove() { this.props.onRemoveAttendance(this.props.entry.member_id); }

    onImgError(ev) {
        const img = ev.target;
        const ph = document.createElement("div");
        ph.className = "k-roster-tile__initials";
        ph.textContent = initials(this.props.entry.name);
        img.parentElement.replaceChild(ph, img);
    }
}

// ─── InstructorSessionCard ────────────────────────────────────────────────────

class InstructorSessionCard extends Component {
    static template = xml`
        <div class="k-session-card">
            <div class="k-session-card__header">
                <div class="k-session-card__title" t-esc="props.session.template_name"/>
                <div class="k-session-card__meta">
                    <span class="k-session-card__time">
                        <t t-esc="formatTime(props.session.start)"/> – <t t-esc="formatTime(props.session.end)"/>
                    </span>
                    <t t-if="props.session.instructor">
                        <span class="k-session-card__instructor">👤 <t t-esc="props.session.instructor"/></span>
                    </t>
                    <span class="k-session-card__count">
                        <t t-esc="props.session.seats_taken"/>
                        <t t-if="props.session.capacity"> / <t t-esc="props.session.capacity"/></t>
                        <t t-else=""> enrolled</t>
                    </span>
                </div>
            </div>

            <t t-if="props.loading">
                <div class="k-session-card__loading"><div class="k-spinner"/></div>
            </t>
            <t t-elif="!props.roster.length">
                <div class="k-session-card__empty">No students enrolled yet</div>
            </t>
            <t t-else="">
                <div class="k-roster-grid">
                    <t t-foreach="props.roster" t-as="entry" t-key="entry.member_id">
                        <InstructorRosterTile
                            entry="entry"
                            sessionId="props.session.id"
                            onMark="(memberId, status) => props.onMark(memberId, props.session.id, status)"
                            onProfile="(memberId) => props.onProfile(memberId, props.session.id)"
                            onRemoveAttendance="(memberId) => props.onRemoveAttendance(memberId, props.session.id)"/>
                    </t>
                </div>
            </t>

            <div class="k-session-card__footer">
                <button class="k-btn k-session-action k-session-action--assign"
                    t-on-click="() => props.onAssignRoster(props.session)">
                    👥 Assign Roster
                </button>
                <button class="k-btn k-session-action k-session-action--edit"
                    t-on-click="() => props.onEdit(props.session)">
                    ✎ Edit
                </button>
                <button class="k-btn k-session-action k-session-action--done"
                    t-on-click="() => props.onClose(props.session.id)">
                    ✓ Mark Done
                </button>
                <button class="k-btn k-session-action k-session-action--delete"
                    t-on-click="() => props.onDelete(props.session.id)">
                    🗑 Delete
                </button>
            </div>
        </div>
    `;

    static props = ["session", "roster", "loading", "onMark", "onProfile", "onRemoveAttendance", "onClose", "onDelete", "onEdit", "onAssignRoster"];
    static components = { InstructorRosterTile };
    formatTime(dt) { return formatTime(dt); }
}

// ─── AttendanceRemoveConfirm ──────────────────────────────────────────────────

class AttendanceRemoveConfirm extends Component {
    static template = xml`
        <div class="k-modal-overlay" t-on-click.self="props.onCancel">
            <div class="k-modal k-modal--sm">
                <div class="k-modal__body" style="text-align:center;padding:32px 24px;">
                    <div style="font-size:40px;margin-bottom:10px;">🔄</div>
                    <div style="font-weight:700;font-size:17px;margin-bottom:6px;color:var(--k-text);">
                        Remove Attendance?
                    </div>
                    <div style="color:var(--k-text-2);font-size:14px;margin-bottom:24px;">
                        <strong t-esc="props.memberName"/> will be set back to Pending.
                    </div>
                    <div style="display:flex;gap:12px;justify-content:center;">
                        <button class="k-btn k-btn--secondary" t-on-click="props.onCancel">Cancel</button>
                        <button class="k-btn k-btn--danger" t-on-click="props.onConfirm">Remove</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    static props = ["memberName", "onCancel", "onConfirm"];
}

// ─── DeleteSessionConfirm ───────────────────────────────────────────────────────

class DeleteSessionConfirm extends Component {
    static template = xml`
        <div class="k-modal-overlay" t-on-click.self="props.onCancel">
            <div class="k-modal k-modal--sm">
                <div class="k-modal__body" style="text-align:center;padding:32px 24px;">
                    <div style="font-size:40px;margin-bottom:10px;">🗑️</div>
                    <div style="font-weight:700;font-size:17px;margin-bottom:6px;color:var(--k-text);">
                        Delete Session?
                    </div>
                    <div style="color:var(--k-text-2);font-size:14px;margin-bottom:24px;">
                        This will cancel all enrollments and cannot be undone.
                    </div>
                    <div style="display:flex;gap:12px;justify-content:center;">
                        <button class="k-btn k-btn--secondary" t-on-click="props.onCancel">Cancel</button>
                        <button class="k-btn k-btn--danger" t-on-click="props.onConfirm">Delete</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    static props = ["onCancel", "onConfirm"];
}

// ─── SessionEditModal ─────────────────────────────────────────────────────────

class SessionEditModal extends Component {
    static template = xml`
        <div class="k-modal-backdrop" t-on-click.self="props.onClose">
            <div class="k-modal k-modal--edit-session">
                <div class="k-modal__header">
                    <span class="k-modal__title">Edit Session</span>
                    <button class="k-modal__close" t-on-click="props.onClose">✕</button>
                </div>
                <div class="k-modal__body">
                    <div class="k-field">
                        <label class="k-field__label">Session</label>
                        <div class="k-field__value" t-esc="props.session.template_name"/>
                    </div>
                    <div class="k-field">
                        <label class="k-field__label">Time</label>
                        <div class="k-field__value">
                            <t t-esc="formatTime(props.session.start)"/> – <t t-esc="formatTime(props.session.end)"/>
                        </div>
                    </div>
                    <div class="k-field">
                        <label class="k-field__label">Capacity</label>
                        <input class="k-field__input"
                            type="number"
                            min="0"
                            t-att-value="state.capacity"
                            t-on-input="onCapacityInput"
                            placeholder="Unlimited"/>
                    </div>
                    <t t-if="state.error">
                        <div class="k-field-error" t-esc="state.error"/>
                    </t>
                </div>
                <div class="k-modal__footer">
                    <button class="k-btn k-btn--secondary" t-on-click="props.onClose">Cancel</button>
                    <button class="k-btn k-btn--primary" t-on-click="save" t-att-disabled="state.saving or undefined">
                        <t t-if="state.saving">Saving…</t>
                        <t t-else="">Save</t>
                    </button>
                </div>
            </div>
        </div>
    `;

    static props = ["session", "onClose", "onSaved"];

    setup() {
        this.state = useState({
            capacity: this.props.session.capacity || "",
            saving: false,
            error: "",
        });
    }

    formatTime(dt) { return formatTime(dt); }
    onCapacityInput(ev) { this.state.capacity = ev.target.value; this.state.error = ""; }

    async save() {
        this.state.saving = true;
        this.state.error = "";
        try {
            const cap = this.state.capacity === "" ? null : parseInt(this.state.capacity, 10);
            const result = await jsonPost("/kiosk/instructor/session/update", {
                session_id: this.props.session.id,
                capacity: cap,
            });
            if (result.success) {
                this.props.onSaved();
            } else {
                this.state.error = result.error || "Failed to save.";
            }
        } catch {
            this.state.error = "Network error.";
        } finally {
            this.state.saving = false;
        }
    }
}

// ─── AssignRosterModal ────────────────────────────────────────────────────────

class AssignRosterModal extends Component {
    static template = xml`
        <div class="k-modal-backdrop" t-on-click.self="props.onClose">
            <div class="k-modal k-modal--assign-roster">
                <div class="k-modal__header">
                    <span class="k-modal__title">
                        <t t-if="state.step === 1">👥 Select Members</t>
                        <t t-else="">📋 Confirm &amp; Add</t>
                    </span>
                    <button class="k-modal__close" t-on-click="props.onClose">✕</button>
                </div>

                <!-- ══ Step 1: member search ══ -->
                <t t-if="state.step === 1">
                    <div class="k-modal__body">
                        <div class="k-am-search">
                            <input class="k-field__input"
                                type="text"
                                placeholder="Search member name…"
                                autofocus="true"
                                t-model="state.query"
                                t-on-input="onInput"
                                autocomplete="off"/>
                        </div>
                        <t t-if="state.chips.length">
                            <div class="k-chips-wrap">
                                <t t-foreach="state.chips" t-as="chip" t-key="chip.member_id">
                                    <div class="k-chip">
                                        <span t-esc="chip.name"/>
                                        <button class="k-chip__remove"
                                            t-on-click="() => this.removeChip(chip.member_id)">✕</button>
                                    </div>
                                </t>
                            </div>
                        </t>
                        <t t-if="state.loading">
                            <div class="k-am-loading"><div class="k-spinner"/></div>
                        </t>
                        <t t-elif="state.results.length">
                            <div class="k-am-results">
                                <t t-foreach="state.results" t-as="m" t-key="m.member_id">
                                    <div t-attf-class="k-am-result #{isSelected(m.member_id) ? 'k-am-result--selected' : ''}"
                                        t-on-click="() => this.toggleMember(m)">
                                        <img class="k-am-result__avatar"
                                            t-att-src="m.image_url"
                                            t-att-alt="m.name"
                                            t-on-error="(ev) => ev.target.style.display='none'"/>
                                        <div class="k-am-result__info">
                                            <span class="k-am-result__name" t-esc="m.name"/>
                                            <t t-if="m.belt_rank">
                                                <span class="k-am-result__belt" t-esc="m.belt_rank"/>
                                            </t>
                                        </div>
                                        <div class="k-am-result__check">✓</div>
                                    </div>
                                </t>
                            </div>
                        </t>
                        <t t-elif="state.query.length >= 2 and !state.loading">
                            <div class="k-am-empty">No members found</div>
                        </t>
                    </div>
                    <div class="k-modal__footer">
                        <button class="k-btn k-btn--secondary" t-on-click="props.onClose">Cancel</button>
                        <button class="k-btn k-btn--primary"
                            t-on-click="goToStep2"
                            t-att-disabled="!state.chips.length or undefined">
                            Next →
                        </button>
                    </div>
                </t>

                <!-- ══ Step 2: session + options + submit ══ -->
                <t t-else="">
                    <div class="k-modal__body">
                        <div class="k-field">
                            <label class="k-field__label">Session</label>
                            <select class="k-field__input" t-on-change="onSessionChange">
                                <t t-foreach="props.sessions" t-as="s" t-key="s.id">
                                    <option t-att-value="s.id"
                                        t-att-selected="state.sessionId === s.id or undefined">
                                        <t t-esc="s.template_name"/> (<t t-esc="formatTime(s.start)"/>)
                                    </option>
                                </t>
                            </select>
                        </div>

                        <div class="k-field">
                            <label class="k-field__label">Enrollment Type</label>
                            <div class="k-enroll-pills">
                                <button t-attf-class="k-enroll-pill #{state.enrollType === 'single' ? 'k-enroll-pill--active' : ''}"
                                    t-on-click="() => this.state.enrollType = 'single'">
                                    Single Day
                                </button>
                                <button t-attf-class="k-enroll-pill #{state.enrollType === 'multiday' ? 'k-enroll-pill--active' : ''}"
                                    t-on-click="() => this.state.enrollType = 'multiday'">
                                    Multiday Range
                                </button>
                                <button t-attf-class="k-enroll-pill #{state.enrollType === 'permanent' ? 'k-enroll-pill--active' : ''}"
                                    t-on-click="() => this.state.enrollType = 'permanent'">
                                    Never Remove
                                </button>
                            </div>
                        </div>

                        <t t-if="state.enrollType === 'multiday'">
                            <div class="k-field">
                                <label class="k-field__label">Date Range</label>
                                <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                                    <input type="date" class="k-field__input"
                                        style="flex:1;min-width:130px"
                                        t-att-value="state.dateFrom"
                                        t-on-change="(ev) => this.state.dateFrom = ev.target.value"/>
                                    <span style="color:var(--k-text-muted,#aaa);font-size:.85rem">to</span>
                                    <input type="date" class="k-field__input"
                                        style="flex:1;min-width:130px"
                                        t-att-value="state.dateTo"
                                        t-on-change="(ev) => this.state.dateTo = ev.target.value"/>
                                </div>
                            </div>
                        </t>

                        <t t-if="state.enrollType === 'multiday' or state.enrollType === 'permanent'">
                            <div class="k-field">
                                <label class="k-field__label">Days of Week <span style="font-weight:400;font-size:.8rem;color:var(--k-text-muted,#aaa)">(leave all off = every day the class runs)</span></label>
                                <div class="k-enroll-pills" style="flex-wrap:wrap">
                                    <t t-foreach="[['mon','Mon'],['tue','Tue'],['wed','Wed'],['thu','Thu'],['fri','Fri'],['sat','Sat'],['sun','Sun']]" t-as="day" t-key="day[0]">
                                        <button t-attf-class="k-enroll-pill #{state.prefDays[day[0]] ? 'k-enroll-pill--active' : ''}"
                                            t-on-click="() => this.state.prefDays[day[0]] = !this.state.prefDays[day[0]]">
                                            <t t-esc="day[1]"/>
                                        </button>
                                    </t>
                                </div>
                            </div>
                        </t>

                        <div class="k-field">
                            <label class="k-check-label">
                                <input type="checkbox"
                                    t-att-checked="state.overrideCapacity or undefined"
                                    t-on-change="(ev) => this.state.overrideCapacity = ev.target.checked"/>
                                Override session capacity limit
                            </label>
                        </div>

                        <div class="k-field">
                            <label class="k-check-label">
                                <input type="checkbox"
                                    t-att-checked="state.overrideSettings or undefined"
                                    t-on-change="(ev) => this.state.overrideSettings = ev.target.checked"/>
                                Override roster settings
                            </label>
                        </div>

                        <div style="margin-bottom:14px;">
                            <div class="k-field__label" style="margin-bottom:8px;">
                                Adding <strong><t t-esc="state.chips.length"/> member(s)</strong>:
                            </div>
                            <div class="k-chips-wrap">
                                <t t-foreach="state.chips" t-as="chip" t-key="chip.member_id">
                                    <div class="k-chip"><span t-esc="chip.name"/></div>
                                </t>
                            </div>
                        </div>

                        <t t-if="state.error">
                            <div class="k-field-error" t-esc="state.error"/>
                        </t>
                    </div>
                    <div class="k-modal__footer">
                        <button class="k-btn k-btn--secondary"
                            t-on-click="() => this.state.step = 1">← Back</button>
                        <button class="k-btn k-btn--primary"
                            t-on-click="submit"
                            t-att-disabled="state.saving or undefined">
                            <t t-if="state.saving">Adding…</t>
                            <t t-else="">Add to Roster</t>
                        </button>
                    </div>
                </t>
            </div>
        </div>
    `;

    static props = ["session", "sessions", "onClose", "onAssigned"];

    setup() {
        this.state = useState({
            step: 1,
            query: "",
            results: [],
            loading: false,
            chips: [],
            sessionId: this.props.session
                ? this.props.session.id
                : (this.props.sessions[0] ? this.props.sessions[0].id : null),
            enrollType: "single",
            dateFrom: "",
            dateTo: "",
            prefDays: { mon: false, tue: false, wed: false, thu: false, fri: false, sat: false, sun: false },
            overrideCapacity: false,
            overrideSettings: false,
            saving: false,
            error: "",
        });
        this._timer = null;
    }

    formatTime(dt) { return formatTime(dt); }

    isSelected(memberId) {
        return this.state.chips.some(c => c.member_id === memberId);
    }

    toggleMember(member) {
        const idx = this.state.chips.findIndex(c => c.member_id === member.member_id);
        if (idx !== -1) {
            this.state.chips.splice(idx, 1);
        } else {
            this.state.chips.push({ member_id: member.member_id, name: member.name });
        }
    }

    removeChip(memberId) {
        const idx = this.state.chips.findIndex(c => c.member_id === memberId);
        if (idx !== -1) this.state.chips.splice(idx, 1);
    }

    onInput() {
        clearTimeout(this._timer);
        const q = this.state.query.trim();
        if (q.length < 2) { this.state.results = []; return; }
        this.state.loading = true;
        this._timer = setTimeout(async () => {
            try {
                const res = await jsonPost("/kiosk/search", { query: q });
                this.state.results = res || [];
            } catch {
                this.state.results = [];
            } finally {
                this.state.loading = false;
            }
        }, 300);
    }

    onSessionChange(ev) {
        const val = ev.target.value;
        this.state.sessionId = val ? parseInt(val, 10) : null;
    }

    goToStep2() {
        if (!this.state.chips.length) return;
        this.state.step = 2;
        this.state.error = "";
    }

    async submit() {
        if (!this.state.sessionId || !this.state.chips.length) return;
        if (this.state.enrollType === 'multiday') {
            if (!this.state.dateFrom || !this.state.dateTo) {
                this.state.error = "Please select both a From and To date for Multiday Range.";
                return;
            }
            if (this.state.dateFrom > this.state.dateTo) {
                this.state.error = "'From' date must be on or before the 'To' date.";
                return;
            }
        }
        this.state.saving = true;
        this.state.error = "";
        try {
            const memberIds = this.state.chips.map(c => c.member_id);
            const result = await jsonPost("/kiosk/instructor/roster/bulk_add", {
                session_id: this.state.sessionId,
                member_ids: memberIds,
                override_capacity: this.state.overrideCapacity,
                override_settings: this.state.overrideSettings,
                enroll_type: this.state.enrollType,
                date_from: this.state.enrollType === 'multiday' ? this.state.dateFrom : undefined,
                date_to: this.state.enrollType === 'multiday' ? this.state.dateTo : undefined,
                pref_mon: this.state.prefDays.mon,
                pref_tue: this.state.prefDays.tue,
                pref_wed: this.state.prefDays.wed,
                pref_thu: this.state.prefDays.thu,
                pref_fri: this.state.prefDays.fri,
                pref_sat: this.state.prefDays.sat,
                pref_sun: this.state.prefDays.sun,
            });
            if (result.success) {
                this.props.onAssigned(this.state.sessionId);
            } else {
                this.state.error = result.error || "Could not add members.";
            }
        } catch {
            this.state.error = "Network error.";
        } finally {
            this.state.saving = false;
        }
    }
}

// ─── KioskSettingsModal ───────────────────────────────────────────────────────

class KioskSettingsModal extends Component {
    static template = xml`
        <div class="k-modal-backdrop" t-on-click.self="props.onClose">
            <div class="k-modal k-modal--settings">
                <div class="k-modal__header">
                    <span class="k-modal__title">⚙ Kiosk Settings</span>
                    <button class="k-modal__close" t-on-click="props.onClose">✕</button>
                </div>
                <div class="k-modal__body">
                    <div class="k-field">
                        <label class="k-field__label">Font Size</label>
                        <div class="k-settings-row">
                            <button t-attf-class="k-sz-btn #{props.fontSize === 'normal' ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onFontSize('normal')">Normal</button>
                            <button t-attf-class="k-sz-btn #{props.fontSize === 'large' ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onFontSize('large')">Large</button>
                            <button t-attf-class="k-sz-btn #{props.fontSize === 'xl' ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onFontSize('xl')">X-Large</button>
                        </div>
                    </div>

                    <div class="k-field">
                        <label class="k-field__label">Theme</label>
                        <div class="k-settings-row">
                            <button t-attf-class="k-sz-btn #{props.theme === 'light' ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onTheme('light')">☀ Light</button>
                            <button t-attf-class="k-sz-btn #{props.theme === 'dark' ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onTheme('dark')">🌙 Dark</button>
                        </div>
                    </div>

                    <div class="k-field">
                        <label class="k-field__label">Idle Timeout</label>
                        <div class="k-settings-row">
                            <button t-attf-class="k-sz-btn #{props.idleMinutes === 1 ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onIdleMinutes(1)">1 min</button>
                            <button t-attf-class="k-sz-btn #{props.idleMinutes === 3 ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onIdleMinutes(3)">3 min</button>
                            <button t-attf-class="k-sz-btn #{props.idleMinutes === 5 ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onIdleMinutes(5)">5 min</button>
                            <button t-attf-class="k-sz-btn #{props.idleMinutes === 10 ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onIdleMinutes(10)">10 min</button>
                        </div>
                    </div>

                    <div class="k-field">
                        <label class="k-field__label">Header Title</label>
                        <div class="k-settings-row">
                            <button t-attf-class="k-sz-btn #{props.showTitle ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onShowTitle(true)">Show</button>
                            <button t-attf-class="k-sz-btn #{!props.showTitle ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onShowTitle(false)">Hide</button>
                        </div>
                    </div>
                </div>
                <div class="k-modal__footer">
                    <button class="k-btn k-btn--primary" t-on-click="props.onClose">Done</button>
                </div>
            </div>
        </div>
    `;

    static props = ["onClose", "fontSize", "theme", "idleMinutes", "showTitle", "onFontSize", "onTheme", "onIdleMinutes", "onShowTitle"];
}

// ─── KioskApp (root) ─────────────────────────────────────────────────────────

class KioskApp extends Component {
    static template = xml`
        <div class="k-app">

            <!-- ── Idle screen ── -->
            <t t-if="state.idle">
                <IdleScreen
                    announcements="state.announcements"
                    onWake="() => this.wakeFromIdle()"/>
            </t>

            <!-- ── Check-in success overlay ── -->
            <t t-if="state.checkinResult">
                <CheckinSuccessView
                    success="state.checkinResult.success"
                    memberName="state.checkinResult.memberName || ''"
                    sessionName="state.checkinResult.sessionName || ''"
                    programName="state.checkinResult.programName || ''"
                    status="state.checkinResult.status || ''"
                    errorMessage="state.checkinResult.error || ''"
                    onDone="() => this.clearCheckinResult()"/>
            </t>

            <!-- ── Header (single, conditional modifier class) ── -->
            <div t-attf-class="k-header #{state.instructorMode ? 'k-header--instructor' : ''}">
                <t t-if="state.showTitle">
                    <span class="k-header__logo">🥋 Dojo</span>
                </t>

                <!-- Student mode: search bar -->
                <t t-if="!state.instructorMode">
                    <div class="k-header__search-wrap">
                        <span class="k-header__search-icon">🔍</span>
                        <input class="k-header__search"
                            type="text"
                            placeholder="Type your name to check in…"
                            t-model="state.searchQuery"
                            t-on-input="onSearchInput"
                            autocomplete="off"
                            autocorrect="off"
                            spellcheck="false"/>
                        <t t-if="state.searchQuery">
                            <button class="k-header__search-clear" t-on-click="clearSearch">✕</button>
                        </t>
                    </div>
                </t>

                <!-- Instructor mode: pill + session filter + date -->
                <t t-if="state.instructorMode">
                    <span class="k-instructor-pill">🔓 Instructor Mode</span>
                    <div class="k-header__spacer"/>
                    <select class="k-svh-select" t-on-change="onSessionViewFilter">
                        <option value="">All Sessions</option>
                        <t t-foreach="state.sessions" t-as="s" t-key="s.id">
                            <option t-att-value="s.id"
                                t-att-selected="state.sessionViewId === s.id or undefined">
                                <t t-esc="s.template_name"/> (<t t-esc="formatTime(s.start)"/>)
                            </option>
                        </t>
                    </select>
                    <input class="k-svh-date"
                        type="date"
                        t-att-value="state.filterDate"
                        t-on-change="onDateChange"/>
                </t>

                <div class="k-header__actions">
                    <!-- Karate toggle — only in student mode -->
                    <t t-if="!state.instructorMode">
                        <button class="k-header__instructor-btn"
                            t-on-click="onInstructorToggle"
                            title="Switch to Instructor Mode">🥋</button>
                    </t>
                    <!-- Reload -->
                    <button class="k-header__action-btn" t-on-click="reloadSessions" title="Reload">
                        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2v6h-6"/><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M3 22v-6h6"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/></svg>
                    </button>
                    <!-- Settings -->
                    <button class="k-header__action-btn" t-on-click="openSettings" title="Settings">⚙</button>
                    <!-- Exit instructor mode -->
                    <t t-if="state.instructorMode">
                        <button class="k-header__action-btn" t-on-click="onInstructorToggle" title="Exit Instructor Mode" style="font-size:14px;font-weight:700;">✕ Exit</button>
                    </t>
                </div>
            </div>

            <!-- ── Body ── -->
            <div class="k-body">

                <!-- ════ STUDENT FLOW ════ -->
                <t t-if="!state.instructorMode">
                    <HomeContent
                        query="state.searchQuery"
                        results="state.searchResults"
                        loading="state.searchLoading"
                        onSelect="(member) => this.studentConfirm(member)"/>
                </t>

                <!-- ════ INSTRUCTOR VIEW ════ -->
                <t t-else="">
                    <t t-if="!filteredSessions().length">
                        <div class="k-empty">
                            <div class="k-empty__icon">📅</div>
                            <div class="k-empty__text">No open sessions today</div>
                        </div>
                    </t>
                    <t t-else="">
                        <div class="k-sessions-list">
                            <t t-foreach="filteredSessions()" t-as="session" t-key="session.id">
                                <InstructorSessionCard
                                    session="session"
                                    roster="state.sessionRosters[session.id] || []"
                                    loading="!!state.loadingRosters[session.id]"
                                    onMark="(memberId, sessionId, status) => this.markAttendance(memberId, sessionId, status)"
                                    onProfile="(memberId, sessionId) => this.openProfile(memberId, sessionId)"
                                    onRemoveAttendance="(memberId, sessionId) => this.promptRemoveAttendance(memberId, sessionId)"
                                    onClose="(sessionId) => this.closeSessionById(sessionId)"
                                    onDelete="(sessionId) => this.deleteSessionById(sessionId)"
                                    onEdit="(session) => this.openEditSession(session)"
                                    onAssignRoster="(session) => this.openAssignRoster(session)"/>
                            </t>
                        </div>
                    </t>
                </t>

            </div>

            <!-- ── Student checkin modal ── -->
            <t t-if="state.checkinModal">
                <StudentCheckinModal
                    member="state.checkinModal.member"
                    sessions="state.checkinModal.sessions"
                    loading="state.checkinModal.loading"
                    result="state.checkinModal.result"
                    checkedInSession="state.checkinModal.checkedInSession"
                    onSelect="(session) => this.studentCheckin(session)"
                    onCheckout="(session) => this.studentCheckout(session)"
                    onClose="() => this.state.checkinModal = null"/>
            </t>

            <!-- ── Member profile modal ── -->
            <t t-if="state.profileMember">
                <MemberProfileCard
                    member="state.profileMember"
                    sessionId="state.profileSessionId"
                    instructorMode="state.instructorMode"
                    onClose="() => this.closeProfile()"
                    onCheckin="(member, sessionId) => this.doCheckinFromProfile(member, sessionId)"
                    onCheckout="(member, sessionId) => this.doCheckout(member, sessionId)"
                    onMarkAttendance="(member, sessionId, status) => this.markAttendanceFromProfile(member, sessionId, status)"
                    onRosterAdd="(member, sessionId) => this.rosterAdd(member, sessionId)"
                    onRosterRemove="(member, sessionId) => this.rosterRemove(member, sessionId)"/>
            </t>

            <!-- ── Remove attendance confirm ── -->
            <t t-if="state.removeAttendancePending">
                <AttendanceRemoveConfirm
                    memberName="state.removeAttendancePending.name"
                    onCancel="() => this.state.removeAttendancePending = null"
                    onConfirm="() => this.confirmRemoveAttendance()"/>
            </t>

            <!-- ── Delete session confirm ── -->
            <t t-if="state.deleteSessionPending">
                <DeleteSessionConfirm
                    onCancel="() => this.state.deleteSessionPending = null"
                    onConfirm="() => this.confirmDeleteSession()"/>
            </t>

            <!-- ── PIN modal ── -->
            <t t-if="state.showPin">
                <PinModal onClose="() => this.closePin()" onSuccess="() => this.onPinSuccess()"/>
            </t>

            <!-- ── Edit session modal ── -->
            <t t-if="state.editingSession">
                <SessionEditModal
                    session="state.editingSession"
                    onClose="() => this.closeEditSession()"
                    onSaved="() => this.onSessionSaved()"/>
            </t>

            <!-- ── Assign roster modal ── -->
            <t t-if="state.assignRosterSession">
                <AssignRosterModal
                    session="state.assignRosterSession"
                    sessions="state.sessions"
                    onClose="() => this.closeAssignRoster()"
                    onAssigned="(sid) => this.onRosterAssigned(sid)"/>
            </t>

            <!-- ── Settings modal ── -->
            <t t-if="state.showSettings">
                <KioskSettingsModal
                    fontSize="state.fontSize"
                    theme="state.theme"
                    idleMinutes="state.idleMinutes"
                    showTitle="state.showTitle"
                    onClose="() => this.closeSettings()"
                    onFontSize="(s) => this.onFontSize(s)"
                    onTheme="(t) => this.onTheme(t)"
                    onIdleMinutes="(m) => this.onIdleMinutes(m)"
                    onShowTitle="(v) => this.onShowTitle(v)"/>
            </t>

        </div>
    `;

    static components = {
        HomeContent,
        MemberCard,
        StudentCheckinModal,
        InstructorSessionCard,
        InstructorRosterTile,
        AttendanceRemoveConfirm,
        DeleteSessionConfirm,
        AssignRosterModal,
        MemberProfileCard,
        PinModal,
        CheckinSuccessView,
        IdleScreen,
        SessionEditModal,
        KioskSettingsModal,
    };

    setup() {
        this.state = useState({
            // Student flow
            searchQuery: "",
            searchResults: [],
            searchLoading: false,
            checkinModal: null,   // { member, sessions, loading }
            checkinResult: null,

            // Sessions (instructor)
            sessions: [],
            sessionViewId: null,
            filterDate: todayIso(),
            sessionRosters: {},
            loadingRosters: {},

            // Config
            showTitle: true,

            // Instructor
            instructorMode: false,
            showPin: false,
            profileMember: null,
            profileSessionId: null,
            removeAttendancePending: null,
            deleteSessionPending: null,

            // Modals
            showSettings: false,
            editingSession: null,
            assignRosterSession: null,

            // Misc
            idle: false,
            announcements: [],
            fontSize: "normal",
            theme: "dark",
            idleMinutes: 3,
        });

        this._searchTimer = null;
        this._barcodeBuffer = "";
        this._barcodeTimer = null;
        this._idleTimer = null;
        this._interactionHandler = this._resetIdleTimer.bind(this);

        onMounted(() => {
            this._bootstrap();
            this._startBarcodeListener();
            document.addEventListener("click", this._interactionHandler, true);
            document.addEventListener("keydown", this._interactionHandler, true);
            document.addEventListener("touchstart", this._interactionHandler, true);
            this._resetIdleTimer();
        });
        onWillUnmount(() => {
            this._stopBarcodeListener();
            document.removeEventListener("click", this._interactionHandler, true);
            document.removeEventListener("keydown", this._interactionHandler, true);
            document.removeEventListener("touchstart", this._interactionHandler, true);
            clearTimeout(this._idleTimer);
        });
    }

    formatTime(dt) { return formatTime(dt); }

    // ── Idle timer ─────────────────────────────────────────────

    _resetIdleTimer() {
        if (this.state.idle) this.state.idle = false;
        clearTimeout(this._idleTimer);
        this._idleTimer = setTimeout(() => {
            this.state.idle = true;
        }, this.state.idleMinutes * 60_000);
    }

    wakeFromIdle() {
        this.state.idle = false;
        this._resetIdleTimer();
    }

    // ── Bootstrap ──────────────────────────────────────────────

    async _bootstrap() {
        if (document.body.classList.contains("kiosk-theme-light")) {
            this.state.theme = "light";
        } else {
            this.state.theme = "dark";
        }
        try {
            const data = await jsonPost("/kiosk/api/bootstrap");
            if (data && !data.error) {
                this.state.announcements = data.announcements || [];
                this.state.sessions = data.sessions || [];
                this.state.showTitle = data.show_title !== false;
                if (data.theme_mode && data.theme_mode !== this.state.theme) {
                    this.onTheme(data.theme_mode);
                }
            } else {
                await this._loadSessions();
            }
        } catch (e) {
            console.error("Kiosk: bootstrap failed", e);
            await this._loadSessions();
        }
    }

    // ── Sessions ───────────────────────────────────────────────

    async _loadSessions(date = null) {
        try {
            const params = date ? { date } : {};
            const sessions = await jsonPost("/kiosk/sessions", params);
            this.state.sessions = sessions || [];
        } catch (e) {
            console.error("Kiosk: failed to load sessions", e);
        }
    }

    async reloadSessions() {
        await this._loadSessions(this.state.filterDate || null);
        if (this.state.instructorMode) this._loadAllSessionRosters();
    }

    filteredSessions() {
        if (this.state.sessionViewId) {
            return this.state.sessions.filter(s => s.id === this.state.sessionViewId);
        }
        return this.state.sessions;
    }

    onSessionViewFilter(ev) {
        const val = ev.target.value;
        this.state.sessionViewId = val ? parseInt(val, 10) : null;
    }

    async onDateChange(ev) {
        const date = ev.target.value;
        this.state.filterDate = date;
        this.state.sessionViewId = null;
        this.state.sessionRosters = {};
        await this._loadSessions(date || null);
        this._loadAllSessionRosters();
    }

    // ── Rosters ────────────────────────────────────────────────

    _loadAllSessionRosters() {
        for (const session of this.state.sessions) {
            if (!this.state.sessionRosters[session.id] && !this.state.loadingRosters[session.id]) {
                this._loadSessionRoster(session.id);
            }
        }
    }

    async _loadSessionRoster(sessionId) {
        this.state.loadingRosters[sessionId] = true;
        try {
            const roster = await jsonPost("/kiosk/roster", { session_id: sessionId });
            this.state.sessionRosters[sessionId] = roster || [];
        } catch (e) {
            console.error("Kiosk: failed to load session roster", sessionId, e);
            this.state.sessionRosters[sessionId] = [];
        } finally {
            this.state.loadingRosters[sessionId] = false;
        }
    }

    _updateSessionRosterEntry(sessionId, memberId, changes) {
        const roster = this.state.sessionRosters[sessionId];
        if (!roster) return;
        const idx = roster.findIndex(r => r.member_id === memberId);
        if (idx !== -1) Object.assign(roster[idx], changes);
    }

    // ── Student flow ───────────────────────────────────────────

    onSearchInput() {
        clearTimeout(this._searchTimer);
        const q = this.state.searchQuery.trim();
        if (q.length < 2) { this.state.searchResults = []; return; }
        this.state.searchLoading = true;
        this._searchTimer = setTimeout(async () => {
            try {
                const results = await jsonPost("/kiosk/search", { query: q });
                this.state.searchResults = results || [];
            } catch {
                this.state.searchResults = [];
            } finally {
                this.state.searchLoading = false;
            }
        }, 300);
    }

    clearSearch() {
        this.state.searchQuery = "";
        this.state.searchResults = [];
    }

    async studentConfirm(member) {
        // Open the modal immediately with a spinner, then load the member's enrolled sessions
        this.state.checkinModal = { member, sessions: [], loading: true, result: null, checkedInSession: null };
        try {
            const sessions = await jsonPost("/kiosk/member/enrolled_sessions", {
                member_id: member.member_id,
                date: this.state.filterDate || todayIso(),
            });
            if (!this.state.checkinModal) return;
            const all = sessions || [];
            this.state.checkinModal.sessions = all;
            // Detect if already checked in to any session today
            const active = all.find(s => s.attendance_state === "present" || s.attendance_state === "late");
            this.state.checkinModal.checkedInSession = active || null;
        } catch (e) {
            console.error("Kiosk: failed to load enrolled sessions", e);
            if (this.state.checkinModal) this.state.checkinModal.sessions = [];
        } finally {
            if (this.state.checkinModal) this.state.checkinModal.loading = false;
        }
    }

    async studentCheckout(session) {
        const modal = this.state.checkinModal;
        if (!modal) return;
        const member = modal.member;
        try {
            const result = await jsonPost("/kiosk/checkout", {
                member_id: member.member_id,
                session_id: session.id,
            });
            if (result.success) {
                this._updateSessionRosterEntry(session.id, member.member_id, { attendance_state: "checked_out" });
            }
            modal.result = {
                success: result.success,
                type: "checkout",
                sessionName: session.template_name || session.name,
                programName: "",
                error: result.error || "",
            };
        } catch {
            modal.result = {
                success: false,
                type: "checkout",
                sessionName: "",
                programName: "",
                error: "Network error. Please try again.",
            };
        }
        setTimeout(() => {
            this.state.checkinModal = null;
            this.state.searchQuery = "";
            this.state.searchResults = [];
        }, 3000);
    }

    async studentCheckin(session) {
        const modal = this.state.checkinModal;
        if (!modal) return;
        const member = modal.member;
        try {
            const result = await jsonPost("/kiosk/checkin", {
                member_id: member.member_id,
                session_id: session.id,
            });
            if (result.success) {
                this._updateSessionRosterEntry(session.id, member.member_id, { attendance_state: result.status });
            }
            // Show result inside the modal itself
            modal.result = {
                success: result.success,
                sessionName: result.session_name || session.template_name || session.name,
                programName: session.program_name || "",
                error: result.error || "",
            };
            // Auto-dismiss after 3.5s
            setTimeout(() => {
                this.state.checkinModal = null;
                this.state.searchQuery = "";
                this.state.searchResults = [];
            }, 3500);
        } catch {
            modal.result = {
                success: false,
                sessionName: "",
                programName: "",
                error: "Network error. Please try again.",
            };
            setTimeout(() => { this.state.checkinModal = null; }, 3500);
        }
    }

    clearCheckinResult() {
        this.state.checkinResult = null;
    }

    // ── Instructor — profile ───────────────────────────────────

    async openProfile(memberId, sessionId = null) {
        try {
            const profile = await jsonPost("/kiosk/member/profile", {
                member_id: memberId,
                session_id: sessionId,
            });
            this.state.profileMember = profile;
            this.state.profileSessionId = sessionId;
        } catch (e) {
            console.error("Kiosk: failed to load profile", e);
        }
    }

    closeProfile() {
        this.state.profileMember = null;
        this.state.profileSessionId = null;
    }

    // ── Instructor — check-in from profile ────────────────────

    async doCheckinFromProfile(member, sessionId) {
        this.closeProfile();
        try {
            const result = await jsonPost("/kiosk/checkin", {
                member_id: member.member_id,
                session_id: sessionId,
            });
            if (result.success) {
                this._updateSessionRosterEntry(sessionId, member.member_id, { attendance_state: result.status });
            }
            this.state.checkinResult = {
                success: result.success,
                memberName: member.name,
                sessionName: result.session_name || "",
                programName: "",
                status: result.status || "",
                error: result.error || "",
            };
        } catch (e) {
            console.error("Kiosk: checkin from profile failed", e);
        }
    }

    // ── Instructor — checkout ─────────────────────────────────

    async doCheckout(member, sessionId) {
        this.closeProfile();
        try {
            const result = await jsonPost("/kiosk/checkout", {
                member_id: member.member_id,
                session_id: sessionId,
            });
            if (result.success) {
                // "checked_out" is a display-only state; the log record keeps present/late
                this._updateSessionRosterEntry(sessionId, member.member_id, { attendance_state: "checked_out" });
            }
        } catch (e) {
            console.error("Kiosk: checkout failed", e);
        }
    }

    // ── Instructor — attendance ───────────────────────────────

    async markAttendance(memberId, sessionId, status) {
        try {
            await jsonPost("/kiosk/instructor/attendance", {
                session_id: sessionId,
                member_id: memberId,
                status,
            });
            this._updateSessionRosterEntry(sessionId, memberId, { attendance_state: status });
        } catch (e) {
            console.error("Kiosk: mark attendance failed", e);
        }
    }

    async markAttendanceFromProfile(member, sessionId, status) {
        this.closeProfile();
        await this.markAttendance(member.member_id, sessionId, status);
    }

    promptRemoveAttendance(memberId, sessionId) {
        const roster = this.state.sessionRosters[sessionId] || [];
        const entry = roster.find(r => r.member_id === memberId);
        this.state.removeAttendancePending = {
            memberId,
            sessionId,
            name: entry ? entry.name : "this member",
        };
    }

    async confirmRemoveAttendance() {
        const { memberId, sessionId } = this.state.removeAttendancePending;
        this.state.removeAttendancePending = null;
        await this.markAttendance(memberId, sessionId, "pending");
    }

    // ── Instructor — roster ───────────────────────────────────

    async rosterAdd(member, sessionId) {
        try {
            const result = await jsonPost("/kiosk/instructor/roster/add", {
                session_id: sessionId,
                member_id: member.member_id,
            });
            if (result.success) await this._loadSessionRoster(sessionId);
        } catch (e) {
            console.error("Kiosk: roster add failed", e);
        }
    }

    async rosterRemove(member, sessionId) {
        try {
            await jsonPost("/kiosk/instructor/roster/remove", {
                session_id: sessionId,
                member_id: member.member_id,
            });
            await this._loadSessionRoster(sessionId);
        } catch (e) {
            console.error("Kiosk: roster remove failed", e);
        }
    }

    openAssignRoster(session) { this.state.assignRosterSession = session; }
    closeAssignRoster() { this.state.assignRosterSession = null; }

    async onRosterAssigned(sessionId) {
        this.state.assignRosterSession = null;
        await this._loadSessionRoster(sessionId);
        await this._loadSessions(this.state.filterDate || null);
    }

    // ── Instructor — session management ──────────────────────

    async closeSessionById(sessionId) {
        try {
            await jsonPost("/kiosk/instructor/session/close", { session_id: sessionId });
            delete this.state.sessionRosters[sessionId];
            await this._loadSessions(this.state.filterDate || null);
        } catch (e) {
            console.error("Kiosk: close session failed", e);
        }
    }

    deleteSessionById(sessionId) {
        this.state.deleteSessionPending = sessionId;
    }

    async confirmDeleteSession() {
        const sessionId = this.state.deleteSessionPending;
        this.state.deleteSessionPending = null;
        try {
            await jsonPost("/kiosk/instructor/session/delete", { session_id: sessionId });
            delete this.state.sessionRosters[sessionId];
            if (this.state.sessionViewId === sessionId) this.state.sessionViewId = null;
            await this._loadSessions(this.state.filterDate || null);
        } catch (e) {
            console.error("Kiosk: delete session failed", e);
        }
    }

    openEditSession(session) { this.state.editingSession = session; }
    closeEditSession() { this.state.editingSession = null; }

    async onSessionSaved() {
        this.state.editingSession = null;
        await this._loadSessions(this.state.filterDate || null);
        this._loadAllSessionRosters();
    }

    // ── PIN / instructor mode ─────────────────────────────────

    openPin() { this.state.showPin = true; }
    closePin() { this.state.showPin = false; }

    onPinSuccess() {
        this.state.showPin = false;
        this.state.instructorMode = true;
        this._loadAllSessionRosters();
    }

    onInstructorToggle() {
        if (!this.state.instructorMode) {
            this.openPin();
        } else {
            this.state.instructorMode = false;
            this.state.studentView = "home";
            this.state.confirmedMember = null;
        }
    }

    // ── Settings ──────────────────────────────────────────────

    openSettings() { this.state.showSettings = true; }
    closeSettings() { this.state.showSettings = false; }

    onFontSize(size) {
        this.state.fontSize = size;
        document.body.classList.remove("kiosk-font-large", "kiosk-font-xl");
        if (size === "large") document.body.classList.add("kiosk-font-large");
        if (size === "xl") document.body.classList.add("kiosk-font-xl");
    }

    onTheme(theme) {
        this.state.theme = theme;
        document.body.classList.remove("kiosk-theme-light", "kiosk-theme-dark");
        document.body.classList.add(`kiosk-theme-${theme}`);
    }

    onShowTitle(val) {
        this.state.showTitle = val;
    }

    onIdleMinutes(mins) {
        this.state.idleMinutes = mins;
        this._resetIdleTimer();
    }

    // ── Barcode scanner (HID keyboard emulation) ──────────────

    _startBarcodeListener() {
        this._barcodeHandler = this._onKeyPress.bind(this);
        document.addEventListener("keypress", this._barcodeHandler);
    }

    _stopBarcodeListener() {
        if (this._barcodeHandler) document.removeEventListener("keypress", this._barcodeHandler);
    }

    _onKeyPress(ev) {
        if (["INPUT", "SELECT", "TEXTAREA"].includes(ev.target.tagName)) return;
        clearTimeout(this._barcodeTimer);
        if (ev.key === "Enter") {
            const barcode = this._barcodeBuffer.trim();
            this._barcodeBuffer = "";
            if (barcode.length >= 3) this._handleBarcode(barcode);
            return;
        }
        if (ev.key.length === 1) this._barcodeBuffer += ev.key;
        this._barcodeTimer = setTimeout(() => {
            if (this._barcodeBuffer.length < 6) this._barcodeBuffer = "";
        }, 100);
    }

    async _handleBarcode(barcode) {
        try {
            const result = await jsonPost("/kiosk/lookup", { barcode });
            if (result.found && result.member) {
                if (!this.state.instructorMode) {
                    this.studentConfirm(result.member);
                } else {
                    await this.openProfile(result.member.member_id);
                }
            }
        } catch (e) {
            console.error("Kiosk: barcode lookup failed", e);
        }
    }
}

// ─── Mount ────────────────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    const root = document.getElementById("kiosk-root");
    if (!root) return;
    mount(KioskApp, root, { dev: false }).catch(e => {
        root.innerHTML =
            '<pre style="color:red;background:#111;padding:20px;font-size:13px;white-space:pre-wrap">'
            + "OWL MOUNT ERROR:\n" + (e && e.message || e)
            + (e && e.stack ? "\n\n" + e.stack : "") + "</pre>";
    });
});
