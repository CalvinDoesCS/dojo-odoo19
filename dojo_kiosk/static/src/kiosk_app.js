/**
 * Dojo Kiosk — OWL Single Page Application
 * Loaded as a plain script (no Odoo module loader).
 * Depends on /web/static/lib/owl/owl.js being loaded first.
 * Mounts to #kiosk-root on /kiosk
 */
/* global owl */
const { Component, useState, onMounted, onWillUnmount, mount, xml } = owl;

// ─── Config identity (per-tablet token from URL) ─────────────────────────────
const KIOSK_TOKEN = window.KIOSK_TOKEN || null;

// ─── Utility ─────────────────────────────────────────────────────────────────

async function jsonPost(url, params = {}) {
    // Automatically attach the device token to every request
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

// ─── PinModal ─────────────────────────────────────────────────────────────────

class PinModal extends Component {
    static template = xml`
        <div class="k-modal-overlay" t-on-click.self="props.onClose">
            <div class="k-modal">
                <button class="k-modal__close" t-on-click="props.onClose">✕</button>
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

// ─── CheckinConfirmation ──────────────────────────────────────────────────────

class CheckinConfirmation extends Component {
    static template = xml`
        <div t-attf-class="k-confirm-screen #{!props.success ? 'k-confirm-screen--error' : ''}">
            <div class="k-confirm-icon">
                <t t-if="props.success">✅</t>
                <t t-else="">❌</t>
            </div>
            <t t-if="props.success">
                <div class="k-confirm-name" t-esc="props.member.name"/>
                <div class="k-confirm-session">
                    Checked in to <strong t-esc="props.sessionName"/>
                </div>
                <div t-attf-class="k-confirm-status k-confirm-status--#{props.status}">
                    <t t-if="props.status === 'late'">⚠ Checked in late</t>
                    <t t-else="">On time</t>
                </div>
            </t>
            <t t-else="">
                <div class="k-confirm-name">Check-in Failed</div>
                <div class="k-confirm-session" t-esc="props.errorMessage"/>
            </t>
            <div class="k-confirm-returning">Returning to kiosk…</div>
        </div>
    `;

    static props = ["success", "member", "sessionName", "status", "errorMessage", "onDone"];

    setup() {
        onMounted(() => { this._timer = setTimeout(() => this.props.onDone(), 4000); });
        onWillUnmount(() => clearTimeout(this._timer));
    }
}

// ─── IdleScreen — shown after inactivity timeout ──────────────────────────────

const IDLE_TIMEOUT_MS = 90_000; // 90 seconds

class IdleScreen extends Component {
    static template = xml`
        <div class="k-idle-screen" t-on-click="wake" t-on-keydown="wake">
            <div class="k-idle-content">
                <t t-if="props.announcements &amp;&amp; props.announcements.length">
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
                <button class="k-modal__close" t-on-click="props.onClose">✕</button>

                <!-- ── Header ── -->
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
                    <!-- Warning banner — shown prominently for both student and instructor -->
                    <t t-if="props.member.issues &amp;&amp; props.member.issues.length">
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
                                    <span style="font-size:13px;font-weight:400;color:#888;">
                                        / <t t-esc="props.member.sessions_allowed_per_week"/>
                                    </span>
                                </t>
                            </span>
                            <span class="k-stat__label">This Week</span>
                        </div>
                    </div>

                    <!-- Member info rows: DOB, plan, contact -->
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

                    <!-- Upcoming appointments -->
                    <t t-if="props.member.appointments &amp;&amp; props.member.appointments.length">
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
                    </div><!-- /k-profile__scroll-body -->

                    <div class="k-profile__actions">
                        <t t-if="props.instructorMode">
                            <!-- Attendance state toggle -->
                            <div class="k-att-section">
                                <div class="k-att-section__label">Mark Attendance</div>
                                <div class="k-att-toggle k-att-toggle--lg">
                                    <button
                                        t-attf-class="k-att-btn k-att-btn--lg #{props.member.attendance_state === 'present' ? 'k-att-btn--active-present' : ''}"
                                        t-on-click="() => this.markAttendance('present')">+ Present</button>
                                    <button
                                        t-attf-class="k-att-btn k-att-btn--lg #{props.member.attendance_state === 'late' ? 'k-att-btn--active-late' : ''}"
                                        t-on-click="() => this.markAttendance('late')">~ Late</button>
                                    <button
                                        t-attf-class="k-att-btn k-att-btn--lg #{props.member.attendance_state === 'absent' ? 'k-att-btn--active-absent' : ''}"
                                        t-on-click="() => this.markAttendance('absent')">x Absent</button>
                                </div>
                            </div>
                            <!-- Roster action -->
                            <div class="k-profile__roster-row">
                                <t t-if="!props.member.enrolled_in_session">
                                    <button class="k-btn k-btn--secondary" t-on-click="onRosterAdd">+ Add to Roster</button>
                                </t>
                                <t t-else="">
                                    <button class="k-btn k-btn--danger" t-on-click="onRosterRemove">- Remove from Roster</button>
                                </t>
                            </div>
                        </t>
                        <t t-else="">
                            <t t-if="props.member.attendance_state === 'present' || props.member.attendance_state === 'late'">
                                <div class="k-checkout-section">
                                    <div class="k-checkout-checkedin">Already checked in</div>
                                    <button class="k-btn k-btn--checkout" t-on-click="onCheckout">
                                        Check Out
                                    </button>
                                </div>
                            </t>
                            <t t-elif="!props.sessionId">
                                <p style="text-align:center;color:#aaa;font-size:13px;">Select a session to check in.</p>
                            </t>
                            <t t-elif="props.member.issues &amp;&amp; props.member.issues.length">
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
                        <t t-if="props.member.programs &amp;&amp; props.member.programs.length">
                            <div class="k-progress__programs-title">Programs</div>
                            <t t-foreach="props.member.programs" t-as="prog" t-key="prog.program_name">
                                <div class="k-progress__prog-row">
                                    <div class="k-progress__prog-name" t-esc="prog.program_name"/>
                                    <div class="k-progress__prog-right">
                                        <t t-if="prog.rank_name">
                                            <span class="k-progress__rank-badge"
                                                t-attf-style="background:#{prog.rank_color || '#e5e7eb'};color:#{contrastColor(prog.rank_color)};"
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
                    </div><!-- /k-profile__scroll-body -->
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
                                        <div class="k-hh__member-avatar"><t t-esc="initials(hm.name)"/></div>
                                        <div class="k-hh__member-info">
                                            <div class="k-hh__member-name" t-esc="hm.name"/>
                                            <div class="k-hh__member-role" t-esc="hm.role || ''"/>
                                        </div>
                                    </div>
                                </t>
                            </div>

                            <t t-if="props.member.household.emergency_contacts &amp;&amp; props.member.household.emergency_contacts.length">
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
                                                <a t-att-href="'tel:' + ec.phone" class="k-hh__contact-phone">📞 <t t-esc="ec.phone"/></a>
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
                    </div><!-- /k-profile__scroll-body -->
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
    onImgError(ev) { ev.target.style.display = "none"; }
    markAttendance(status) { this.props.onMarkAttendance(this.props.member, this.props.sessionId, status); }
    onCheckin() { this.props.onCheckin(this.props.member, this.props.sessionId); }
    onCheckout() { this.props.onCheckout(this.props.member, this.props.sessionId); }
    onRosterAdd() { this.props.onRosterAdd(this.props.member, this.props.sessionId); this.props.onClose(); }
    onRosterRemove() { this.props.onRosterRemove(this.props.member, this.props.sessionId); this.props.onClose(); }
    contrastColor(hexColor) {
        if (!hexColor || hexColor.length < 6) return "#1a1a1a";
        const hex = hexColor.replace("#", "");
        const r = parseInt(hex.substring(0, 2), 16);
        const g = parseInt(hex.substring(2, 4), 16);
        const b = parseInt(hex.substring(4, 6), 16);
        const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
        return lum > 0.5 ? "#1a1a1a" : "#ffffff";
    }
}

// ─── AttendanceRow (instructor list in scan mode) ─────────────────────────────

class AttendanceRow extends Component {
    static template = xml`
        <div class="k-attrow">
            <img class="k-attrow__avatar"
                t-att-src="avatarUrl(entry.member_id)"
                t-att-alt="entry.name"
                t-on-error="onImgError"/>
            <span class="k-attrow__name" t-esc="entry.name"/>
            <div class="k-att-toggle">
                <button t-attf-class="k-att-btn #{entry.attendance_state === 'present' ? 'k-att-btn--active-present' : ''}"
                    t-on-click="() => this.mark('present')">P</button>
                <button t-attf-class="k-att-btn #{entry.attendance_state === 'late' ? 'k-att-btn--active-late' : ''}"
                    t-on-click="() => this.mark('late')">L</button>
                <button t-attf-class="k-att-btn #{entry.attendance_state === 'absent' ? 'k-att-btn--active-absent' : ''}"
                    t-on-click="() => this.mark('absent')">A</button>
            </div>
        </div>
    `;

    static props = ["entry", "sessionId", "onMark"];
    get entry() { return this.props.entry; }
    avatarUrl(id) { return avatarUrl(id); }
    onImgError(ev) { ev.target.style.display = "none"; }
    mark(status) { this.props.onMark(this.props.entry.member_id, status); }
}

// ─── MemberSearchCard — large card shown in scan-mode body ───────────────────

class MemberSearchCard extends Component {
    static template = xml`
        <div class="k-search-card" t-on-click="() => props.onSelect(props.member)">
            <div class="k-search-card__avatar-wrap">
                <img class="k-search-card__avatar"
                    t-att-src="props.member.image_url"
                    t-att-alt="props.member.name"
                    t-on-error="onImgError"/>
            </div>
            <div class="k-search-card__name" t-esc="props.member.name"/>
            <div class="k-search-card__sub">
                <t t-if="props.member.belt_rank">
                    <span class="k-search-card__belt" t-esc="props.member.belt_rank"/>
                </t>
            </div>
        </div>
    `;

    static props = ["member", "onSelect"];

    onImgError(ev) {
        const img = ev.target;
        const wrap = img.parentElement;
        img.style.display = "none";
        const ph = document.createElement("div");
        ph.className = "k-search-card__placeholder";
        ph.textContent = initials(this.props.member.name);
        wrap.prepend(ph);
    }
}

// ─── SessionFaceTile — one student face inside a session card ─────────────────

class SessionFaceTile extends Component {
    static template = xml`
        <div t-attf-class="k-face-tile k-face-tile--#{props.entry.attendance_state || 'pending'}"
             t-on-click="() => props.onSelect(props.entry.member_id)">
            <div class="k-face-wrap">
                <img class="k-face-avatar"
                    t-att-src="avatarUrl(props.entry.member_id)"
                    t-att-alt="props.entry.name"
                    t-on-error.stop="onImgError"/>
                <t t-if="props.entry.attendance_state &amp;&amp; props.entry.attendance_state !== 'pending'">
                    <span t-attf-class="k-status-dot k-status-dot--#{props.entry.attendance_state}"/>
                </t>
            </div>
            <span class="k-face-name" t-esc="props.entry.name"/>
        </div>
    `;

    static props = ["entry", "onSelect"];
    avatarUrl(id) { return avatarUrl(id); }

    onImgError(ev) {
        const img = ev.target;
        const wrap = img.parentElement;
        img.style.display = "none";
        const ph = document.createElement("div");
        ph.className = "k-face-placeholder";
        ph.textContent = initials(this.props.entry.name);
        wrap.prepend(ph);
    }
}

// ─── SessionCard — one session block in sessions view ────────────────────────

class SessionCard extends Component {
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
                        <t t-esc="props.session.seats_taken"/> enrolled
                        <t t-if="props.session.capacity"> / <t t-esc="props.session.capacity"/></t>
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
                <div class="k-session-card__faces">
                    <t t-foreach="props.roster" t-as="entry" t-key="entry.member_id">
                        <SessionFaceTile
                            entry="entry"
                            onSelect="(memberId) => props.onSelect(memberId, props.session.id)"/>
                    </t>
                </div>
            </t>

            <t t-if="props.instructorMode">
                <div class="k-session-card__footer">
                    <button class="k-btn k-session-action k-session-action--add"
                        t-on-click="() => props.onAddMember(props.session)">
                        + Add Member
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
            </t>
        </div>
    `;

    static props = ["session", "roster", "loading", "instructorMode", "onSelect", "onClose", "onDelete", "onEdit", "onAddMember"];
    static components = { SessionFaceTile };
    formatTime(dt) { return formatTime(dt); }
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
                    <button class="k-btn k-btn--primary" t-on-click="save" t-att-disabled="state.saving">
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

    onCapacityInput(ev) {
        this.state.capacity = ev.target.value;
        this.state.error = "";
    }

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
        } catch (e) {
            this.state.error = "Network error.";
        } finally {
            this.state.saving = false;
        }
    }
}

// ─── AddMemberModal ───────────────────────────────────────────────────────────

class AddMemberModal extends Component {
    static template = xml`
        <div class="k-modal-backdrop" t-on-click.self="props.onClose">
            <div class="k-modal k-modal--add-member">
                <div class="k-modal__header">
                    <span class="k-modal__title">Add Member to Session</span>
                    <button class="k-modal__close" t-on-click="props.onClose">✕</button>
                </div>
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
                    <t t-if="state.loading">
                        <div class="k-am-loading"><div class="k-spinner"/></div>
                    </t>
                    <t t-elif="state.results.length">
                        <div class="k-am-results">
                            <t t-foreach="state.results" t-as="m" t-key="m.member_id">
                                <div class="k-am-result" t-on-click="() => this.addMember(m)">
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
                                </div>
                            </t>
                        </div>
                    </t>
                    <t t-elif="state.query.length >= 2 and !state.loading">
                        <div class="k-am-empty">No members found</div>
                    </t>
                    <t t-if="state.error">
                        <div class="k-field-error" t-esc="state.error"/>
                    </t>
                </div>
                <div class="k-modal__footer">
                    <button class="k-btn k-btn--secondary" t-on-click="props.onClose">Cancel</button>
                </div>
            </div>
        </div>
    `;

    static props = ["session", "onClose", "onAdded"];

    setup() {
        this.state = useState({
            query: "",
            results: [],
            loading: false,
            error: "",
        });
        this._timer = null;
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

    async addMember(member) {
        this.state.error = "";
        try {
            const result = await jsonPost("/kiosk/instructor/roster/add", {
                session_id: this.props.session.id,
                member_id: member.member_id,
            });
            if (result.success) {
                this.props.onAdded(member);
            } else {
                this.state.error = result.error || "Could not add member.";
            }
        } catch (e) {
            this.state.error = "Network error.";
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
                                t-on-click="() => props.onTheme('light')">Light</button>
                            <button t-attf-class="k-sz-btn #{props.theme === 'dark' ? 'k-sz-btn--active' : ''}"
                                t-on-click="() => props.onTheme('dark')">Dark</button>
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
                </div>
                <div class="k-modal__footer">
                    <button class="k-btn k-btn--primary" t-on-click="props.onClose">Done</button>
                </div>
            </div>
        </div>
    `;

    static props = ["onClose", "fontSize", "theme", "idleMinutes", "onFontSize", "onTheme", "onIdleMinutes"];
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

            <!-- ── Confirmation overlay ── -->
            <t t-if="state.confirmation">
                <CheckinConfirmation
                    success="state.confirmation.success"
                    member="state.confirmation.member || {}"
                    sessionName="state.confirmation.sessionName || ''"
                    status="state.confirmation.status || ''"
                    errorMessage="state.confirmation.error || ''"
                    onDone="() => this.clearConfirmation()"/>
            </t>

            <!-- ── Header ── -->
            <div class="k-header">
                <span class="k-header__logo">🥋 Dojo</span>

                <div class="k-mode-tabs">
                    <button t-attf-class="k-mode-tab #{state.mode === 'barcode' ? 'k-mode-tab--active' : ''}"
                        t-on-click="() => this.setMode('barcode')">
                        Barcode
                    </button>
                    <button t-attf-class="k-mode-tab #{state.mode === 'session' ? 'k-mode-tab--active' : ''}"
                        t-on-click="() => this.setMode('session')">
                        Session
                    </button>
                </div>

                <!-- Instructor mode — absolutely centred in the header row -->
                <div class="k-instructor-group">
                    <span class="k-instructor-label">Instructor Mode</span>
                    <label class="k-toggle-switch">
                        <input type="checkbox"
                            t-att-checked="state.instructorMode"
                            t-on-change="onInstructorToggle"/>
                        <span class="k-toggle-track"><span class="k-toggle-knob"/></span>
                    </label>
                </div>

                <div class="k-header__spacer"/>
            </div>

            <!-- ── Body ── -->
            <div class="k-body">

                <!-- ════════════ BARCODE VIEW ════════════ -->
                <t t-if="state.mode === 'barcode'">
                    <div class="k-barcode-view">
                        <svg class="k-barcode-svg k-barcode-svg--large" viewBox="0 0 140 90" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                            <rect x="7"   y="6" width="5"  height="58"/>
                            <rect x="16"  y="6" width="9"  height="58"/>
                            <rect x="29"  y="6" width="4"  height="58"/>
                            <rect x="37"  y="6" width="10" height="58"/>
                            <rect x="51"  y="6" width="5"  height="58"/>
                            <rect x="60"  y="6" width="4"  height="58"/>
                            <rect x="68"  y="6" width="8"  height="58"/>
                            <rect x="80"  y="6" width="5"  height="58"/>
                            <rect x="89"  y="6" width="10" height="58"/>
                            <rect x="103" y="6" width="4"  height="58"/>
                            <rect x="111" y="6" width="6"  height="58"/>
                            <rect x="121" y="6" width="12" height="58"/>
                            <text x="70" y="80" text-anchor="middle" font-size="9" font-family="monospace" letter-spacing="2">SCAN BADGE</text>
                        </svg>
                        <p class="k-barcode-hint">Scan your card to check in</p>
                    </div>
                </t>

                <!-- ════════════ SESSION VIEW ════════════ -->
                <t t-else="">
                    <!-- Controls row -->
                    <div class="k-session-view-header">
                        <!-- Member name search -->
                        <div class="k-svh-search">
                            <span class="k-svh-search__icon">🔍</span>
                            <input class="k-svh-search__input"
                                type="text"
                                placeholder="Search member…"
                                t-model="state.searchQuery"
                                t-on-input="onSearchInput"
                                t-on-keydown="onSearchKeydown"
                                autocomplete="off"
                                autocorrect="off"
                                spellcheck="false"/>
                            <t t-if="state.searchQuery">
                                <button class="k-svh-search__clear" t-on-click="clearSearch">✕</button>
                            </t>
                            <t t-if="state.searchResults.length">
                                <div class="k-svh-dropdown">
                                    <t t-foreach="state.searchResults" t-as="m" t-key="m.member_id">
                                        <div class="k-svh-dropdown__item" t-on-click="() => this.selectSearchResult(m)">
                                            <img class="k-svh-dropdown__avatar"
                                                t-att-src="m.image_url"
                                                t-att-alt="m.name"
                                                t-on-error="(ev) => ev.target.style.display='none'"/>
                                            <div class="k-svh-dropdown__info">
                                                <span class="k-svh-dropdown__name" t-esc="m.name"/>
                                                <t t-if="m.belt_rank">
                                                    <span class="k-svh-dropdown__belt" t-esc="m.belt_rank"/>
                                                </t>
                                            </div>
                                        </div>
                                    </t>
                                </div>
                            </t>
                        </div>

                        <!-- Session filter -->
                        <select class="k-svh-select" t-on-change="onSessionViewFilter">
                            <option value="">All Sessions</option>
                            <t t-foreach="state.sessions" t-as="s" t-key="s.id">
                                <option t-att-value="s.id" t-att-selected="state.sessionViewId === s.id">
                                    <t t-esc="s.template_name"/> (<t t-esc="formatTime(s.start)"/>)
                                </option>
                            </t>
                        </select>

                        <!-- Date picker -->
                        <input class="k-svh-date"
                            type="date"
                            t-att-value="state.filterDate"
                            t-on-change="onDateChange"/>

                        <!-- Settings -->
                        <button class="k-svh-settings k-btn k-btn--secondary k-btn--sm" t-on-click="openSettings">⚙</button>
                    </div>

                    <!-- Sessions list -->
                    <t t-if="!filteredSessions().length">
                        <div class="k-empty">
                            <div class="k-empty__icon">📅</div>
                            <div class="k-empty__text">No open sessions</div>
                        </div>
                    </t>
                    <t t-else="">
                        <div class="k-sessions-list">
                            <t t-foreach="filteredSessions()" t-as="session" t-key="session.id">
                                <SessionCard
                                    session="session"
                                    roster="state.sessionRosters[session.id] || []"
                                    loading="!!state.loadingRosters[session.id]"
                                    instructorMode="state.instructorMode"
                                    onSelect="(memberId, sessionId) => this.openProfile(memberId, sessionId)"
                                    onClose="(sessionId) => this.closeSessionById(sessionId)"
                                    onDelete="(sessionId) => this.deleteSessionById(sessionId)"
                                    onEdit="(session) => this.openEditSession(session)"
                                    onAddMember="(session) => this.openAddMember(session)"/>
                            </t>
                        </div>
                    </t>
                </t>

            </div>

            <!-- ── Member profile modal ── -->
            <t t-if="state.profileMember">
                <MemberProfileCard
                    member="state.profileMember"
                    sessionId="state.profileSessionId"
                    instructorMode="state.instructorMode"
                    onClose="() => this.closeProfile()"
                    onCheckin="(member, sessionId) => this.doCheckin(member, sessionId)"
                    onCheckout="(member, sessionId) => this.doCheckout(member, sessionId)"
                    onMarkAttendance="(member, sessionId, status) => this.markAttendanceFromProfile(member, sessionId, status)"
                    onRosterAdd="(member, sessionId) => this.rosterAdd(member, sessionId)"
                    onRosterRemove="(member, sessionId) => this.rosterRemove(member, sessionId)"/>
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

            <!-- ── Add member modal ── -->
            <t t-if="state.addMemberSession">
                <AddMemberModal
                    session="state.addMemberSession"
                    onClose="() => this.closeAddMember()"
                    onAdded="(m) => this.onMemberAdded(m)"/>
            </t>

            <!-- ── Kiosk settings modal ── -->
            <t t-if="state.showSettings">
                <KioskSettingsModal
                    fontSize="state.fontSize"
                    theme="state.theme"
                    idleMinutes="state.idleMinutes"
                    onClose="() => this.closeSettings()"
                    onFontSize="(s) => this.onFontSize(s)"
                    onTheme="(t) => this.onTheme(t)"
                    onIdleMinutes="(m) => this.onIdleMinutes(m)"/>
            </t>

        </div>
    `;

    static components = {
        AttendanceRow,
        MemberSearchCard,
        MemberProfileCard,
        SessionCard,
        PinModal,
        CheckinConfirmation,
        IdleScreen,
        SessionEditModal,
        AddMemberModal,
        KioskSettingsModal,
    };

    setup() {
        this.state = useState({
            mode: "barcode",         // "barcode" | "session"
            sessions: [],
            sessionId: null,         // active session for barcode check-in
            sessionViewId: null,     // session view filter (null = all)
            roster: [],
            loading: false,
            instructorMode: false,
            showPin: false,
            showSettings: false,
            profileMember: null,
            profileSessionId: null,
            searchQuery: "",
            searchResults: [],
            searchLoading: false,
            confirmation: null,
            sessionRosters: {},
            loadingRosters: {},
            idle: false,
            announcements: [],
            filterDate: todayIso(),
            // Kiosk display settings
            fontSize: "normal",      // "normal" | "large" | "xl"
            theme: "dark",           // "light" | "dark"
            idleMinutes: 3,          // idle timeout in minutes
            // Instructor CRUD
            editingSession: null,    // session object being edited
            addMemberSession: null,  // session object for add-member flow
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

    // ── Idle timer ───────────────────────────────────────────────

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

    // ── Mode ─────────────────────────────────────────────────────

    setMode(mode) {
        if (this.state.mode === mode) return;
        this.state.mode = mode;
        if (mode === "session") this._loadAllSessionRosters();
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
        if (this.state.sessionViewId) {
            this.state.sessionId = this.state.sessionViewId;
            if (!this.state.sessionRosters[this.state.sessionViewId]) {
                this._loadSessionRoster(this.state.sessionViewId);
            }
        }
    }

    async onDateChange(ev) {
        const date = ev.target.value;
        this.state.filterDate = date;
        this.state.sessionViewId = null;
        this.state.sessionRosters = {};
        await this._loadSessions(date || null);
        if (this.state.mode === "session") this._loadAllSessionRosters();
    }

    openSettings() {
        this.state.showSettings = true;
    }

    closeSettings() {
        this.state.showSettings = false;
    }

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

    onIdleMinutes(mins) {
        this.state.idleMinutes = mins;
        this._resetIdleTimer();
    }

    onInstructorToggle(ev) {
        if (ev.target.checked && !this.state.instructorMode) {
            ev.target.checked = false; // revert — PIN success will set instructorMode
            this.openPin();
        } else if (!ev.target.checked && this.state.instructorMode) {
            this.exitInstructorMode();
        }
    }

    // ── Bootstrap ────────────────────────────────────────────────

    async _bootstrap() {
        // Sync initial theme state with whatever class the server put on <body>
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
                // Apply theme from config (may differ from initial body class if toggled)
                if (data.theme_mode && data.theme_mode !== this.state.theme) {
                    this.onTheme(data.theme_mode);
                }
                if (this.state.sessions.length === 1) {
                    this.state.sessionId = this.state.sessions[0].id;
                    await this._loadScanRoster();
                }
            } else {
                // Fallback: fetch sessions directly (no token configured yet)
                await this._loadSessions();
            }
        } catch (e) {
            console.error("Kiosk: bootstrap failed, falling back to sessions", e);
            await this._loadSessions();
        }
    }

    // ── Sessions ─────────────────────────────────────────────────

    async _loadSessions(date = null) {
        try {
            const params = date ? { date } : {};
            const sessions = await jsonPost("/kiosk/sessions", params);
            this.state.sessions = sessions || [];
            if (this.state.sessions.length === 1 && !this.state.sessionViewId) {
                this.state.sessionId = this.state.sessions[0].id;
                await this._loadScanRoster();
            }
        } catch (e) {
            console.error("Kiosk: failed to load sessions", e);
        }
    }

    async onSessionChange(ev) {
        const val = ev.target.value;
        this.state.sessionId = val ? parseInt(val, 10) : null;
        this.state.roster = [];
        if (this.state.sessionId) await this._loadScanRoster();
    }

    // ── Roster (scan mode / instructor) ──────────────────────────

    async _loadScanRoster() {
        if (!this.state.sessionId) return;
        this.state.loading = true;
        try {
            const roster = await jsonPost("/kiosk/roster", { session_id: this.state.sessionId });
            this.state.roster = roster || [];
        } catch (e) {
            console.error("Kiosk: failed to load scan roster", e);
        } finally {
            this.state.loading = false;
        }
    }

    _updateScanRosterEntry(memberId, changes) {
        const idx = this.state.roster.findIndex((r) => r.member_id === memberId);
        if (idx !== -1) Object.assign(this.state.roster[idx], changes);
    }

    // ── Rosters (sessions mode) ───────────────────────────────────

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
        const idx = roster.findIndex((r) => r.member_id === memberId);
        if (idx !== -1) Object.assign(roster[idx], changes);
    }

    // ── Profile modal ────────────────────────────────────────────

    async openProfile(memberId, sessionId = null) {
        const sid = sessionId !== null ? sessionId : this.state.sessionId;
        try {
            const profile = await jsonPost("/kiosk/member/profile", {
                member_id: memberId,
                session_id: sid,
            });
            this.state.profileMember = profile;
            this.state.profileSessionId = sid;
        } catch (e) {
            console.error("Kiosk: failed to load profile", e);
        }
    }

    closeProfile() {
        this.state.profileMember = null;
        this.state.profileSessionId = null;
    }

    // ── Check-in ─────────────────────────────────────────────────

    async doCheckin(member, sessionId) {
        this.state.profileMember = null;
        this.state.profileSessionId = null;
        try {
            const result = await jsonPost("/kiosk/checkin", {
                member_id: member.member_id,
                session_id: sessionId,
            });
            if (result.success) {
                this._updateScanRosterEntry(member.member_id, { attendance_state: result.status });
                this._updateSessionRosterEntry(sessionId, member.member_id, { attendance_state: result.status });
            }
            this.state.confirmation = {
                success: result.success,
                member: result.success ? result.member : member,
                sessionName: result.session_name || "",
                status: result.status || "",
                error: result.error || "",
            };
        } catch (e) {
            this.state.confirmation = { success: false, member, error: "Network error. Try again." };
        }
    }

    clearConfirmation() { this.state.confirmation = null; }

    // ── Check-out ────────────────────────────────────────────────

    async doCheckout(member, sessionId) {
        this.state.profileMember = null;
        this.state.profileSessionId = null;
        try {
            const result = await jsonPost("/kiosk/checkout", {
                member_id: member.member_id,
                session_id: sessionId,
            });
            if (result.success) {
                this._updateScanRosterEntry(member.member_id, { attendance_state: "absent" });
                this._updateSessionRosterEntry(sessionId, member.member_id, { attendance_state: "absent" });
                this.state.confirmation = {
                    success: true,
                    member,
                    sessionName: "",
                    status: "checkout",
                    error: "",
                };
            }
        } catch (e) {
            console.error("Kiosk: checkout failed", e);
        }
    }

    // ── Instructor — attendance (scan mode) ──────────────────────

    async markAttendance(memberId, status) {
        try {
            await jsonPost("/kiosk/instructor/attendance", {
                session_id: this.state.sessionId,
                member_id: memberId,
                status,
            });
            this._updateScanRosterEntry(memberId, { attendance_state: status });
        } catch (e) {
            console.error("Kiosk: mark attendance failed", e);
        }
    }

    // Mark attendance from profile modal (works for both scan + sessions modes)
    async markAttendanceFromProfile(member, sessionId, status) {
        this.closeProfile();
        try {
            await jsonPost("/kiosk/instructor/attendance", {
                session_id: sessionId,
                member_id: member.member_id,
                status,
            });
            this._updateScanRosterEntry(member.member_id, { attendance_state: status });
            this._updateSessionRosterEntry(sessionId, member.member_id, { attendance_state: status });
        } catch (e) {
            console.error("Kiosk: mark attendance from profile failed", e);
        }
    }

    // ── Instructor — roster ───────────────────────────────────────

    async rosterAdd(member, sessionId) {
        try {
            const result = await jsonPost("/kiosk/instructor/roster/add", {
                session_id: sessionId,
                member_id: member.member_id,
            });
            if (result.success) {
                if (sessionId === this.state.sessionId) await this._loadScanRoster();
                if (this.state.sessionRosters[sessionId] !== undefined) await this._loadSessionRoster(sessionId);
            }
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
            if (sessionId === this.state.sessionId) await this._loadScanRoster();
            if (this.state.sessionRosters[sessionId] !== undefined) await this._loadSessionRoster(sessionId);
        } catch (e) {
            console.error("Kiosk: roster remove failed", e);
        }
    }

    // ── Instructor — close session ────────────────────────────────

    async closeSession() {
        if (!this.state.sessionId) return;
        await this._closeSession(this.state.sessionId);
        this.state.sessionId = null;
        this.state.roster = [];
    }

    async closeSessionById(sessionId) {
        await this._closeSession(sessionId);
    }

    async _closeSession(sessionId) {
        try {
            await jsonPost("/kiosk/instructor/session/close", { session_id: sessionId });
            delete this.state.sessionRosters[sessionId];
            await this._loadSessions();
        } catch (e) {
            console.error("Kiosk: close session failed", e);
        }
    }

    // ── Instructor — delete session ───────────────────────────────

    async deleteSessionById(sessionId) {
        if (!confirm("Delete this session? This will cancel all enrollments.")) return;
        try {
            await jsonPost("/kiosk/instructor/session/delete", { session_id: sessionId });
            delete this.state.sessionRosters[sessionId];
            if (this.state.sessionViewId === sessionId) this.state.sessionViewId = null;
            await this._loadSessions();
        } catch (e) {
            console.error("Kiosk: delete session failed", e);
        }
    }

    // ── Instructor — edit session ─────────────────────────────────

    openEditSession(session) {
        this.state.editingSession = session;
    }

    closeEditSession() {
        this.state.editingSession = null;
    }

    async onSessionSaved() {
        this.state.editingSession = null;
        await this._loadSessions();
        if (this.state.mode === "session") this._loadAllSessionRosters();
    }

    // ── Instructor — add member ───────────────────────────────────

    openAddMember(session) {
        this.state.addMemberSession = session;
    }

    closeAddMember() {
        this.state.addMemberSession = null;
    }

    async onMemberAdded(member) {
        const sid = this.state.addMemberSession && this.state.addMemberSession.id;
        this.state.addMemberSession = null;
        if (sid) await this._loadSessionRoster(sid);
        await this._loadSessions();
    }

    // ── PIN / instructor mode ────────────────────────────────────

    openPin() { this.state.showPin = true; }
    closePin() { this.state.showPin = false; }

    onPinSuccess() {
        this.state.showPin = false;
        this.state.instructorMode = true;
        if (this.state.sessionId) this._loadScanRoster();
    }

    exitInstructorMode() { this.state.instructorMode = false; }

    // ── Search ──────────────────────────────────────────────────

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

    onSearchKeydown(ev) {
        if (ev.key === "Escape") this.clearSearch();
    }

    clearSearch() {
        this.state.searchQuery = "";
        this.state.searchResults = [];
    }

    async selectSearchResult(member) {
        this.clearSearch();
        await this.openProfile(member.member_id);
    }

    // ── Barcode scanner (HID keyboard emulation) ─────────────────

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
            if (result.found && result.member) await this.openProfile(result.member.member_id);
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
            + 'OWL MOUNT ERROR:\n' + (e && e.message || e)
            + (e && e.stack ? '\n\n' + e.stack : '') + '</pre>';
    });
});
