(function () {
    "use strict";

    /* ── Constants ──────────────────────────────────────────────────────── */
    var LEVEL = {
        beginner:     { label: "Beginner",     cls: "dojo-chip dojo-chip--success" },
        intermediate: { label: "Intermediate", cls: "dojo-chip dojo-chip--warning" },
        advanced:     { label: "Advanced",     cls: "dojo-chip dojo-chip--danger"  },
        all:          { label: "All Levels",   cls: "dojo-chip dojo-chip--neutral" },
    };
    var STATUS = {
        registered: { label: "Registered", cls: "dojo-chip dojo-chip--success" },
        waitlist:   { label: "Waitlist",    cls: "dojo-chip dojo-chip--warning" },
        cancelled:  { label: "Cancelled",   cls: "dojo-chip dojo-chip--neutral" },
    };
    var ATT_STATE = {
        pending: { label: "Pending", cls: "dojo-chip dojo-chip--neutral" },
        present: { label: "Present", cls: "dojo-chip dojo-chip--success" },
        absent:  { label: "Absent",  cls: "dojo-chip dojo-chip--danger"  },
        excused: { label: "Excused", cls: "dojo-chip dojo-chip--warning" },
    };
    var LOG_STATUS = {
        present: { label: "Present", cls: "dojo-chip dojo-chip--success" },
        late:    { label: "Late",    cls: "dojo-chip dojo-chip--warning" },
        absent:  { label: "Absent",  cls: "dojo-chip dojo-chip--danger"  },
        excused: { label: "Excused", cls: "dojo-chip dojo-chip--neutral" },
    };
    var LEVEL_CLR  = { beginner:"#188038", intermediate:"#e37400", advanced:"#d93025", all:"#5f6368" };
    var STATUS_CLR = { registered:"#188038", waitlist:"#e37400", cancelled:"#5f6368" };
    var LOG_CLR    = { present:"#188038", late:"#e37400", absent:"#d93025", excused:"#5f6368" };

    var TAB_TITLES = { programs:"Programs", classes:"Classes", attendance:"Attendance History", household:"My Household", billing:"Billing" };

    function b(map, key)  { return map[key] || { label: key || '—', cls: 'dojo-chip dojo-chip--neutral' }; }
    function esc(s)       { return String(s == null ? "" : s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
    function getCsrfToken() {
        var el = document.getElementById('dojo_activities_mount');
        return (el && el.dataset.csrf) || '';
    }
    function fmtDt(iso) {
        if (!iso) return "\u2014";
        var d = new Date(iso.indexOf("T") !== -1 ? iso + "Z" : iso);
        if (isNaN(d)) return iso;
        return d.toLocaleString("en-US", { weekday:"short", month:"short", day:"numeric", year:"numeric", hour:"numeric", minute:"2-digit" });
    }
    function fmtDate(iso) {
        if (!iso) return "\u2014";
        var d = new Date(iso.indexOf("T") !== -1 ? iso : iso + "T00:00:00");
        if (isNaN(d)) return iso;
        return d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
    }
    function fmtMoney(amount, currency) {
        if (amount == null) return "\u2014";
        try { return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(amount); }
        catch(e) { return (currency || "") + " " + Number(amount).toFixed(2); }
    }
    function fetchJson(url) {
        return fetch(url, { credentials: "same-origin" })
            .then(function(r){ return r.ok ? r.json() : {}; })
            .catch(function()  { return {}; });
    }

    /* ── Card builders ──────────────────────────────────────────────────── */
    function sessionCard(s) {
        var lvl = b(LEVEL, s.level);
        var clr = LEVEL_CLR[s.level] || "#5f6368";
        var pct = s.capacity ? Math.round(s.seats_taken / s.capacity * 100) : 0;
        return '<div class="col">' +
          '<div class="dojo-md3-card dojo-md3-card--clickable h-100" style="border-left:3px solid ' + esc(clr) + '" data-type="session" data-id="' + s.id + '">' +
            '<div class="d-flex flex-column p-3" style="height:100%">' +
              '<div class="d-flex justify-content-between align-items-center mb-2">' +
                '<span class="' + esc(lvl.cls) + '">' + esc(lvl.label) + '</span>' +
                '<div class="d-flex align-items-center gap-2">' +
                  (s.credits_per_class ? '<span class="dojo-chip dojo-chip--info"><i class="fa fa-circle-o me-1"></i>' + esc(s.credits_per_class) + ' cr</span>' : '<span class="dojo-chip dojo-chip--success"><i class="fa fa-unlock me-1"></i>Unlimited</span>') +
                  (s.duration_minutes ? '<small style="color:#5f6368;font-weight:600">' + esc(s.duration_minutes) + '&nbsp;min</small>' : '') +
                '</div>' +
              '</div>' +
              '<h6 class="fw-bold mb-2 lh-sm" style="color:#202124">' + esc(s.name) + '</h6>' +
              '<div class="vstack gap-1 mb-3" style="color:#5f6368;font-size:.85rem">' +
                '<div><i class="fa fa-calendar-o me-1"></i>' + esc(fmtDt(s.start_datetime)) + '</div>' +
                (s.instructor ? '<div><i class="fa fa-user me-1"></i>' + esc(s.instructor) + '</div>' : '') +
              '</div>' +
              '<div class="mt-auto">' +
                '<div class="d-flex justify-content-between mb-1">' +
                  '<small style="color:#5f6368">Seats</small>' +
                  '<small style="color:#5f6368;font-weight:600">' + esc(s.seats_taken) + '/' + esc(s.capacity) + '</small>' +
                '</div>' +
                '<div class="dojo-progress"><div class="dojo-progress-bar" role="progressbar" style="width:' + pct + '%;background:' + esc(clr) + '"></div></div>' +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>';
    }

    function enrollmentCard(e) {
        var st  = b(STATUS, e.status);
        var at  = b(ATT_STATE, e.attendance_state);
        var clr = STATUS_CLR[e.status] || "#5f6368";
        return '<div class="col">' +
          '<div class="dojo-md3-card dojo-md3-card--clickable h-100" style="border-left:3px solid ' + esc(clr) + '" data-type="enrollment" data-id="' + e.id + '">' +
            '<div class="p-3">' +
              '<div class="d-flex justify-content-between align-items-start mb-2">' +
                '<span class="' + esc(st.cls) + '">' + esc(st.label) + '</span>' +
                '<span class="' + esc(at.cls) + '">' + esc(at.label) + '</span>' +
              '</div>' +
              '<h6 class="fw-bold mb-2 lh-sm" style="color:#202124">' + esc(e.session_name) + '</h6>' +
              '<div class="vstack gap-1" style="color:#5f6368;font-size:.85rem">' +
                '<div><i class="fa fa-calendar-o me-1"></i>' + esc(fmtDt(e.start_datetime)) + '</div>' +
                (e.instructor  ? '<div><i class="fa fa-user me-1"></i>'           + esc(e.instructor)  + '</div>' : '') +
                (e.member_name ? '<div><i class="fa fa-graduation-cap me-1"></i>' + esc(e.member_name) + '</div>' : '') +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>';
    }

    function attendanceCard(log) {
        var ls  = b(LOG_STATUS, log.status);
        var clr = LOG_CLR[log.status] || "#5f6368";
        return '<div class="col">' +
          '<div class="dojo-md3-card dojo-md3-card--clickable h-100" style="border-left:3px solid ' + esc(clr) + '" data-type="attendance" data-id="' + log.id + '">' +
            '<div class="p-3">' +
              '<div class="mb-2"><span class="' + esc(ls.cls) + '">' + esc(ls.label) + '</span></div>' +
              '<h6 class="fw-bold mb-2 lh-sm" style="color:#202124">' + esc(log.session_name || "Session") + '</h6>' +
              '<div class="vstack gap-1" style="color:#5f6368;font-size:.85rem">' +
                '<div><i class="fa fa-clock-o me-1"></i>' + esc(fmtDt(log.checkin_datetime)) + '</div>' +
                (log.member_name ? '<div><i class="fa fa-graduation-cap me-1"></i>' + esc(log.member_name) + '</div>' : '') +
                (log.note        ? '<div class="fst-italic"><i class="fa fa-comment-o me-1"></i>' + esc(log.note) + '</div>' : '') +
              '</div>' +
            '</div>' +
          '</div>' +
        '</div>';
    }

    /* ── Household tab ───────────────────────────────────────────────────── */
    function householdTabHtml(data, isParent) {
        if (!data || data.error || !data.members) {
            return '<div class="alert alert-info">Household information unavailable.</div>';
        }
        var html = '<div class="d-flex justify-content-between align-items-center mb-3">';
        if (data.household_name) {
            html += '<h6 class="fw-semibold mb-0"><i class="fa fa-home me-2"></i>' + esc(data.household_name) + '</h6>';
        } else {
            html += '<h6 class="fw-semibold mb-0 text-muted">Household</h6>';
        }
        if (isParent) {
            html += '<button class="btn btn-outline-secondary btn-sm" id="dojoEditHouseholdBtn"><i class="fa fa-pencil me-1"></i>Edit</button>';
        }
        html += '</div>';
        if (!data.members.length) {
            return html + '<div class="alert alert-info">No members found.</div>';
        }
        html += '<div class="row row-cols-1 row-cols-md-2 g-3">';
        data.members.forEach(function(m) {
            html += '<div class="col"><div class="dojo-member-card h-100">';
            html += '<div class="dojo-member-card-hd">';
            html += '<div class="dojo-member-avatar">' + esc((m.name || '?')[0].toUpperCase()) + '</div>';
            html += '<div class="flex-grow-1">';
            html += '<div class="fw-semibold" style="color:#202124;font-size:.9rem">' + esc(m.name) + '</div>';
            html += '<div class="text-capitalize" style="color:#5f6368;font-size:.75rem">' + esc(m.is_guardian ? (m.is_student ? 'Standalone' : 'Parent') : 'Student') + '</div>';
            html += '</div></div>';
            html += '<div class="p-3">';
            // ── Subscription plan ──────────────────────────────────────────────
            var plan = m.plan;
            html += '<p class="dojo-field-lbl mb-1">Membership Plan</p>';
            if (plan) {
                var PLAN_STATE_CLS = { active:'dojo-chip--success', paused:'dojo-chip--warning', cancelled:'dojo-chip--neutral', draft:'dojo-chip--info', expired:'dojo-chip--danger' };
                html += '<div class="d-flex align-items-center gap-2 mb-3 flex-wrap">';
                html += '<span class="fw-semibold" style="font-size:.875rem;color:#202124">' + esc(plan.name) + '</span>';
                html += '<span class="dojo-chip ' + esc(PLAN_STATE_CLS[plan.state] || 'dojo-chip--neutral') + '">' + esc((plan.state || '').replace(/_/g,' ')) + '</span>';
                if (plan.billing_period) {
                    html += '<span style="color:#5f6368;font-size:.8rem">' + esc(fmtMoney(plan.price, plan.currency)) + ' / ' + esc(plan.billing_period) + '</span>';
                }
                html += '</div>';
            } else {
                html += '<p style="color:#5f6368;font-size:.85rem;font-style:italic;margin-bottom:.75rem">No active plan.</p>';
            }
            // ── Credit balance ─────────────────────────────────────────────
            var creditsPerPeriod = (plan && plan.credits_per_period) || 0;
            if (plan && creditsPerPeriod === 0) {
                html += '<p class="dojo-field-lbl mb-1">Credits</p>';
                html += '<div class="d-flex align-items-center gap-2 mb-3">';
                html += '<span class="dojo-chip dojo-chip--success"><i class="fa fa-unlock me-1"></i>Unlimited</span>';
                html += '<small style="color:#5f6368">No credit gate on this plan.</small>';
                html += '</div>';
            } else if (creditsPerPeriod > 0) {
                var balance  = m.credit_balance  || 0;
                var pending  = m.credit_pending  || 0;  // already negative
                var confirmed = m.credit_confirmed || 0;
                html += '<p class="dojo-field-lbl mb-1">Credits Remaining</p>';
                var chipCls = balance <= 0 ? 'dojo-chip--danger' : balance <= 2 ? 'dojo-chip--warning' : 'dojo-chip--success';
                var barClr  = balance <= 0 ? '#d93025' : balance <= 2 ? '#e37400' : '#188038';
                html += '<div class="d-flex align-items-center gap-2 mb-1">';
                html += '<span class="dojo-chip ' + chipCls + '">' + balance + ' / ' + creditsPerPeriod + '</span>';
                var pct = Math.min(100, Math.round(balance / creditsPerPeriod * 100));
                html += '<div class="dojo-progress flex-grow-1"><div class="dojo-progress-bar" role="progressbar" style="width:' + pct + '%;background:' + barClr + '"></div></div>';
                html += '</div>';
                if (pending < 0) {
                    html += '<small style="color:#5f6368;display:block;margin-bottom:.5rem"><i class="fa fa-clock-o me-1"></i>' + Math.abs(pending) + ' held for upcoming sessions</small>';
                }
                if (balance <= 0) {
                    html += '<small style="color:#d93025;display:block;margin-bottom:.5rem"><i class="fa fa-exclamation-triangle me-1"></i>No credits remaining</small>';
                }
            }

            // ── Enrolled courses ──────────────────────────────────────────
            if (m.courses && m.courses.length) {
                html += '<p class="dojo-field-lbl mb-1 mt-2">Enrolled Courses</p>';
                html += '<div class="d-flex flex-wrap gap-1 mb-3">';
                m.courses.forEach(function(c) {
                    var lvl = b(LEVEL, c.level);
                    html += '<span class="' + esc(lvl.cls) + '" title="' + esc(lvl.label) + '">' + esc(c.name) + '</span>';
                });
                html += '</div>';
            } else {
                html += '<p style="color:#5f6368;font-size:.85rem;font-style:italic;margin-bottom:.5rem">Not enrolled in any courses yet.</p>';
            }

            // ── Emergency contacts ────────────────────────────────────────
            if (m.emergency_contacts && m.emergency_contacts.length) {
                html += '<p class="dojo-field-lbl mb-2 mt-2">Emergency Contacts</p>';
                m.emergency_contacts.forEach(function(ec) {
                    html += '<div class="mb-2">';
                    html += '<div class="fw-semibold" style="font-size:.85rem">' + esc(ec.name);
                    if (ec.is_primary) html += ' <span class="dojo-chip dojo-chip--success">Primary</span>';
                    html += '</div>';
                    html += '<div style="color:#5f6368;font-size:.8rem">' + esc(ec.relationship || '') + (ec.relationship && ec.phone ? ' &bull; ' : '') + esc(ec.phone || '') + '</div>';
                    if (ec.email) html += '<div style="color:#5f6368;font-size:.8rem">' + esc(ec.email) + '</div>';
                    html += '</div>';
                });
            } else {
                html += '<p style="color:#5f6368;font-size:.85rem;margin-bottom:0">No emergency contacts on file.</p>';
            }
            html += '</div></div></div>';
        });
        html += '</div>';
        return html;
    }

    /* ── Household edit overlay ──────────────────────────────────────────── */
    function openHouseholdEditOverlay(data, members, onSave) {
        var memberOpts = (data.members || []).map(function(m) {
            return '<option value="' + m.id + '">' + esc(m.name) + '</option>';
        }).join('');

        var html = '<h4 class="fw-bold mb-3">Edit Household</h4>';
        html += '<div class="mb-3"><label class="form-label fw-semibold">Household Name</label>';
        html += '<input type="text" class="form-control" id="dojoHHName" value="' + esc(data.household_name || '') + '"/></div>';
        html += '<hr class="my-3"/>';
        html += '<h6 class="fw-semibold mb-2">Add Emergency Contact</h6>';
        if (members.length > 1) {
            html += '<div class="mb-2"><label class="form-label small">For Member</label>';
            html += '<select class="form-select form-select-sm" id="dojoHHMemberSel">' + memberOpts + '</select></div>';
        }
        html += '<div class="row g-2 mb-3">';
        html += '<div class="col-6"><label class="form-label small">Name *</label><input type="text" class="form-control form-control-sm" id="dojoHHCName" placeholder="Full name"/></div>';
        html += '<div class="col-6"><label class="form-label small">Relationship</label><input type="text" class="form-control form-control-sm" id="dojoHHCRel" placeholder="e.g. Mother"/></div>';
        html += '<div class="col-6"><label class="form-label small">Phone *</label><input type="tel" class="form-control form-control-sm" id="dojoHHCPhone" placeholder="+1 555 000 0000"/></div>';
        html += '<div class="col-6"><label class="form-label small">Email</label><input type="email" class="form-control form-control-sm" id="dojoHHCEmail" placeholder="optional"/></div>';
        html += '</div>';
        html += '<div id="dojoHHMsg" class="mb-2 small"></div>';
        html += '<div class="d-flex gap-2"><button class="btn btn-primary btn-sm" id="dojoHHSaveBtn">Save Changes</button><button class="btn btn-secondary btn-sm" id="dojoHHCancelBtn">Cancel</button></div>';

        var el = document.createElement("div");
        el.id = "dojoOverlay"; el.className = "dojo-overlay-backdrop";
        el.innerHTML = '<div class="dojo-overlay-panel" role="dialog" aria-modal="true">' +
            '<button type="button" class="btn-close position-absolute top-0 end-0 m-3" id="dojoOverlayClose" aria-label="Close"></button>' +
            html + '</div>';
        document.body.appendChild(el);
        document.body.classList.add("dojo-overlay-open");
        el.addEventListener("click", function(ev){ if (ev.target === el) closeOverlay(); });
        document.getElementById("dojoOverlayClose").addEventListener("click", closeOverlay);
        document.getElementById("dojoHHCancelBtn").addEventListener("click", closeOverlay);
        document.getElementById("dojoHHSaveBtn").addEventListener("click", function() {
            var saveBtn = document.getElementById("dojoHHSaveBtn");
            var hhName = (document.getElementById("dojoHHName") || {}).value || '';
            var cName  = (document.getElementById("dojoHHCName") || {}).value || '';
            var cRel   = (document.getElementById("dojoHHCRel") || {}).value || '';
            var cPhone = (document.getElementById("dojoHHCPhone") || {}).value || '';
            var cEmail = (document.getElementById("dojoHHCEmail") || {}).value || '';
            var mSel   = document.getElementById("dojoHHMemberSel");
            var mId    = mSel ? parseInt(mSel.value, 10) : (members.length ? members[0].id : null);
            var payload = { household_name: hhName };
            if (cName && cPhone) { payload.new_contact = { member_id: mId, name: cName, relationship: cRel, phone: cPhone, email: cEmail }; }
            saveBtn.disabled = true; saveBtn.textContent = "Saving\u2026";
            fetch('/my/dojo/household/save?csrf_token=' + encodeURIComponent(getCsrfToken()), {
                method: 'POST', credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).then(function(r){ return r.json(); }).then(function(res){
                var msg = document.getElementById("dojoHHMsg");
                if (res.ok) {
                    if (msg) msg.innerHTML = '<span class="text-success"><i class="fa fa-check me-1"></i>Saved!</span>';
                    setTimeout(function(){ closeOverlay(); if (onSave) onSave(); }, 700);
                } else {
                    if (msg) msg.innerHTML = '<span class="text-danger">' + esc(res.error || 'Could not save.') + '</span>';
                    saveBtn.disabled = false; saveBtn.textContent = "Save Changes";
                }
            });
        });
    }

    /* ── Billing tab ─────────────────────────────────────────────────────── */
    function billingTabHtml(data, isParent) {
        if (!isParent) {
            return '<div class="alert alert-info"><i class="fa fa-info-circle me-2"></i>Billing is managed by your household guardian.</div>';
        }
        if (!data) {
            return '<div class="d-flex justify-content-center py-5"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading…</span></div></div>';
        }

        var allSubs = data.subscriptions || [];
        var html = '';

        /* ── Billing failure alerts (check all subs) ───────────────────── */
        allSubs.forEach(function(sub) {
            if (sub.billing_failure_count > 0) {
                var who = sub.member_name ? ' for ' + esc(sub.member_name) : '';
                if (sub.grace_period_end) {
                    html += '<div class="alert alert-danger mb-4"><i class="fa fa-exclamation-triangle me-2"></i>' +
                        '<strong>Membership suspended' + who + '.</strong> The membership will be permanently cancelled after ' +
                        esc(fmtDate(sub.grace_period_end)) + ' if payment is not resolved.</div>';
                } else if (sub.billing_failure_count >= 2) {
                    html += '<div class="alert alert-warning mb-4"><i class="fa fa-exclamation-triangle me-2"></i>' +
                        '<strong>Payment issue' + who + '.</strong> The membership has been paused due to a failed payment.</div>';
                } else {
                    html += '<div class="alert alert-warning mb-4"><i class="fa fa-exclamation-triangle me-2"></i>' +
                        '<strong>Payment issue' + who + '.</strong> A recent payment failed. Please ensure your payment method is up to date.</div>';
                }
            }
        });

        /* ── No subscriptions ──────────────────────────────────────────── */
        if (!allSubs.length) {
            html += '<div class="dojo-billing-card mb-4 p-4">' +
                '<h5 class="fw-bold mb-1" style="color:#202124">No Active Subscription</h5>' +
                '<p style="color:#5f6368;margin-bottom:0">No subscription found for your household. Please contact us to set up your membership.</p>' +
                '</div>';
            return html;
        }

        /* ── Subscription cards (one per student) ──────────────────────── */
        var STATE_LABELS = { active:'Active', paused:'Paused', cancelled:'Cancelled', draft:'Draft', expired:'Expired' };
        var STATE_CHIP_CLS = { active:'dojo-chip--success', paused:'dojo-chip--warning', cancelled:'dojo-chip--neutral', draft:'dojo-chip--info', expired:'dojo-chip--danger' };

        allSubs.forEach(function(sub) {
            var stateLabel = STATE_LABELS[sub.state] || sub.state;
            var stateCls   = STATE_CHIP_CLS[sub.state] || 'dojo-chip--neutral';
            var periodLabel = sub.period === 'monthly' ? '/mo' : sub.period === 'yearly' ? '/yr' : '/wk';
            var heading = sub.member_name ? esc(sub.member_name) + ' — Plan' : 'Current Plan';

            html += '<div class="dojo-billing-card mb-4" data-sub-id="' + sub.id + '">';
            html += '<div class="dojo-billing-card-hd d-flex justify-content-between align-items-center">' +
                '<span>' + heading + '</span>' +
                '<span class="dojo-chip ' + stateCls + '">' + esc(stateLabel) + '</span>' +
                '</div>';
            html += '<div class="dojo-billing-field-row">';
            html += '<span class="dojo-billing-field-lbl">Plan</span>';
            html += '<span class="fw-semibold" style="color:#202124">' + esc(sub.plan_name) + '</span>';
            html += '</div>';
            html += '<div class="dojo-billing-field-row">';
            html += '<span class="dojo-billing-field-lbl">Price</span>';
            html += '<span class="fw-semibold" style="color:#1a73e8">' + esc(fmtMoney(sub.price, sub.currency)) + '<span style="color:#5f6368;font-weight:normal"> ' + esc(periodLabel) + '</span></span>';
            html += '</div>';
            if (sub.next_billing_date && sub.state === 'active') {
                html += '<div class="dojo-billing-field-row">';
                html += '<span class="dojo-billing-field-lbl"><i class="fa fa-calendar me-1"></i>Next billing</span>';
                html += '<span>' + esc(fmtDate(sub.next_billing_date)) + '</span>';
                html += '</div>';
            }
            if (sub.start_date) {
                html += '<div class="dojo-billing-field-row">';
                html += '<span class="dojo-billing-field-lbl"><i class="fa fa-clock-o me-1"></i>Member since</span>';
                html += '<span>' + esc(fmtDate(sub.start_date)) + '</span>';
                html += '</div>';
            }
            if (sub.state === 'paused') {
                html += '<div class="d-flex flex-wrap gap-2 p-3">' +
                    '<button class="btn btn-outline-success btn-sm dojo-billing-resume" data-sub-id="' + sub.id + '">' +
                    '<i class="fa fa-play me-1"></i>Resume</button>' +
                    '</div>';
            }
            if (sub.state === 'active' || sub.state === 'paused') {
                html += '<div class="alert alert-info mx-3 mb-3" style="font-size:.875rem"><i class="fa fa-info-circle me-2"></i>To cancel your subscription, please contact the dojo directly.</div>';
            }
            html += '</div>';
        });

        /* ── Payment method ────────────────────────────────────────────── */
        if (data.payment_method) {
            html += '<div class="dojo-billing-card mb-4">';
            html += '<div class="dojo-billing-card-hd">Payment Method</div>';
            html += '<div class="dojo-billing-field-row">' +
                '<span class="dojo-billing-field-lbl"><i class="fa fa-credit-card me-1"></i>Card</span>' +
                '<span>' + esc(data.payment_method.name) + '</span>' +
                '</div>';
            html += '</div>';
        }

        /* ── Invoice history ───────────────────────────────────────────── */
        var invoices = data.invoices || [];
        html += '<div class="dojo-billing-card">';
        html += '<div class="dojo-billing-card-hd">Invoice History</div>';
        if (!invoices.length) {
            html += '<div class="p-3" style="color:#5f6368;font-size:.875rem">No invoices yet.</div>';
        } else {
            invoices.forEach(function(inv) {
                var payLabel, payChipCls;
                if (inv.payment_state === 'paid' || inv.payment_state === 'in_payment') {
                    payLabel = 'Paid';    payChipCls = 'dojo-chip--success';
                } else if (inv.payment_state === 'partial') {
                    payLabel = 'Partial'; payChipCls = 'dojo-chip--warning';
                } else {
                    payLabel = 'Unpaid';  payChipCls = 'dojo-chip--danger';
                }
                html += '<div class="dojo-billing-field-row">' +
                    '<span style="color:#5f6368;font-size:.8rem">' + esc(inv.date ? fmtDate(inv.date) : '\u2014') + '</span>' +
                    '<span class="fw-semibold" style="color:#202124">' + esc(fmtMoney(inv.amount, inv.currency)) + '</span>' +
                    '<span class="dojo-chip ' + payChipCls + '">' + payLabel + '</span>' +
                    '</div>';
            });
        }
        html += '</div>';

        return html;
    }

    function openBillingPlanOverlay(plans, currentPlanId, subscriptionId, onSave) {
        var plansHtml = (plans || []).map(function(p) {
            var active = p.id === currentPlanId;
            return '<label class="d-flex align-items-start gap-2 p-3 mb-2 rounded border ' +
                (active ? 'border-primary bg-primary bg-opacity-10' : 'border-secondary-subtle') + '">' +
                '<input type="radio" name="dojoBillingPlan" value="' + p.id + '"' + (active ? ' checked' : '') + ' class="form-check-input mt-1"/>' +
                '<span><span class="fw-semibold d-block">' + esc(p.name) + '</span>' +
                '<span class="text-muted small">' + esc(fmtMoney(p.price, p.currency)) + ' / ' + esc(p.period) + '</span>' +
                (p.description ? '<span class="text-muted small d-block fst-italic">' + esc(p.description) + '</span>' : '') +
                '</span></label>';
        }).join('');
        var html = '<h4 class="fw-bold mb-1">Change Plan</h4>';
        html += '<p class="text-muted small mb-3">Select a new plan. Billing updates on the next invoice date.</p>';
        html += '<div class="mb-3">' + (plansHtml || '<p class="text-muted">No plans available.</p>') + '</div>';
        html += '<div id="dojoPlanMsg" class="mb-2 small"></div>';
        html += '<div class="d-flex gap-2"><button class="btn btn-primary btn-sm" id="dojoPlanSaveBtn">Update Plan</button>';
        html += '<button class="btn btn-secondary btn-sm" id="dojoPlanCancelBtn">Cancel</button></div>';
        var el = document.createElement("div");
        el.id = "dojoOverlay"; el.className = "dojo-overlay-backdrop";
        el.innerHTML = '<div class="dojo-overlay-panel" role="dialog" aria-modal="true">' +
            '<button type="button" class="btn-close position-absolute top-0 end-0 m-3" id="dojoOverlayClose" aria-label="Close"></button>' +
            html + '</div>';
        document.body.appendChild(el);
        document.body.classList.add("dojo-overlay-open");
        el.addEventListener("click", function(ev){ if (ev.target === el) closeOverlay(); });
        document.getElementById("dojoOverlayClose").addEventListener("click", closeOverlay);
        document.getElementById("dojoPlanCancelBtn").addEventListener("click", closeOverlay);
        document.getElementById("dojoPlanSaveBtn").addEventListener("click", function() {
            var checked = el.querySelector('input[name="dojoBillingPlan"]:checked');
            if (!checked) return;
            var saveBtn = document.getElementById("dojoPlanSaveBtn");
            saveBtn.disabled = true; saveBtn.textContent = "Updating\u2026";
            var form = new FormData();
            form.set("plan_id", checked.value);
            form.set("csrf_token", getCsrfToken());
            if (subscriptionId) form.set("subscription_id", subscriptionId);
            fetch("/my/dojo/billing/change-plan", { method: "POST", credentials: "same-origin", body: form })
                .then(function(r){ return r.json(); })
                .then(function(res){
                    var msg = document.getElementById("dojoPlanMsg");
                    if (res.ok) {
                        if (msg) msg.innerHTML = '<span class="text-success"><i class="fa fa-check me-1"></i>Plan updated!</span>';
                        setTimeout(function(){ closeOverlay(); if (onSave) onSave(); }, 700);
                    } else {
                        if (msg) msg.innerHTML = '<span class="text-danger">' + esc(res.error || 'Could not update.') + '</span>';
                        saveBtn.disabled = false; saveBtn.textContent = "Update Plan";
                    }
                });
        });
    }

    function openBillingConfirmOverlay(title, message, btnText, btnCls, onConfirm) {
        var html = '<h4 class="fw-bold mb-3">' + esc(title) + '</h4>';
        html += '<p class="text-muted mb-4">' + esc(message) + '</p>';
        html += '<div id="dojoConfirmMsg" class="mb-3 small"></div>';
        html += '<div class="d-flex gap-2"><button class="btn btn-sm ' + esc(btnCls) + '" id="dojoConfirmOkBtn">' + esc(btnText) + '</button>';
        html += '<button class="btn btn-secondary btn-sm" id="dojoConfirmCancelBtn">Go Back</button></div>';
        var el = document.createElement("div");
        el.id = "dojoOverlay"; el.className = "dojo-overlay-backdrop";
        el.innerHTML = '<div class="dojo-overlay-panel" role="dialog" aria-modal="true">' +
            '<button type="button" class="btn-close position-absolute top-0 end-0 m-3" id="dojoOverlayClose" aria-label="Close"></button>' +
            html + '</div>';
        document.body.appendChild(el);
        document.body.classList.add("dojo-overlay-open");
        el.addEventListener("click", function(ev){ if (ev.target === el) closeOverlay(); });
        document.getElementById("dojoOverlayClose").addEventListener("click", closeOverlay);
        document.getElementById("dojoConfirmCancelBtn").addEventListener("click", closeOverlay);
        document.getElementById("dojoConfirmOkBtn").addEventListener("click", function() {
            var okBtn = document.getElementById("dojoConfirmOkBtn");
            okBtn.disabled = true; okBtn.textContent = "Please wait\u2026";
            function onErr(errMsg) {
                var msgEl = document.getElementById("dojoConfirmMsg");
                if (msgEl) msgEl.innerHTML = '<span class="text-danger">' + esc(errMsg) + '</span>';
                okBtn.disabled = false; okBtn.textContent = btnText;
            }
            onConfirm(onErr);
        });
    }


    /* ── Enrollment section (inside session overlay) ─────────────────────── */
    function enrollSection(session, isParent, members, hhMembers) {
        // Filter to household students who are in this session's eligible list
        var eligibleIds = session.eligible_member_ids || [];
        var enrollable = members.filter(function(m) {
            var isStudent = m.is_student;
            if (!isStudent) return false;
            if (eligibleIds.length > 0) return eligibleIds.indexOf(m.id) !== -1;
            return true;
        });
        var full = session.capacity > 0 && session.seats_taken >= session.capacity;
        var cost = session.credits_per_class || 0;  // 0 = unlimited plan

        // Build credit info map from household data
        var creditMap = {};
        (hhMembers || []).forEach(function(hm) {
            var cpp = (hm.plan && hm.plan.credits_per_period) || 0;
            creditMap[hm.id] = {
                balance: hm.credit_balance || 0,
                unlimited: cpp === 0 && !!hm.plan,
            };
        });

        var html = '<div class="border-top pt-3 mt-3" id="dojoEnrollSection">';
        html += '<h6 class="fw-semibold mb-2">Reserve &amp; Enroll</h6>';

        // Credit cost chip
        if (cost > 0) {
            html += '<div class="mb-3"><span class="badge rounded-pill" style="background:#0dcaf0;color:#000"><i class="fa fa-circle-o me-1"></i>' + cost + ' credit' + (cost !== 1 ? 's' : '') + ' per session</span></div>';
        } else {
            html += '<div class="mb-3"><span class="dojo-chip dojo-chip--success"><i class="fa fa-unlock me-1"></i>Unlimited plan — no credits used</span></div>';
        }

        if (full) {
            html += '<span style="color:#5f6368;font-size:.85rem">Session is full.</span>';
        } else if (!enrollable.length) {
            var hasStudents = members.some(function(m){ return m.is_student; });
            if (hasStudents) {
                html += '<span style="color:#5f6368;font-size:.85rem">No household students are subscribed to this program. Ask an instructor for help.</span>';
            } else {
                html += '<span style="color:#5f6368;font-size:.85rem">No students in your household to enroll.</span>';
            }
        } else if (enrollable.length > 1) {
            // Multi-member: show per-member credit previews + select
            html += '<div class="mb-3">';
            enrollable.forEach(function(m) {
                var cr = creditMap[m.id];
                var bal = cr ? cr.balance : null;
                var unl = cr ? cr.unlimited : false;
                html += '<div class="d-flex align-items-center gap-2 mb-1 small">';
                html += '<span class="fw-semibold" style="min-width:120px">' + esc(m.name) + '</span>';
                if (unl) {
                    html += '<span class="dojo-chip dojo-chip--success"><i class="fa fa-unlock me-1"></i>Unlimited</span>';
                } else if (bal !== null && cost > 0) {
                    var after = bal - cost;
                    var balCls = bal <= 0 ? 'dojo-chip--danger' : bal <= 2 ? 'dojo-chip--warning' : 'dojo-chip--success';
                    var aftCls = after < 0 ? 'dojo-chip--danger' : after <= 2 ? 'dojo-chip--warning' : 'dojo-chip--success';
                    html += '<span class="dojo-chip ' + balCls + '">' + bal + '</span>';
                    html += '<span style="color:#5f6368">&#8594;</span>';
                    html += '<span class="dojo-chip ' + aftCls + '">' + after + '</span>';
                    if (bal < cost) {
                        html += '<span style="color:#d93025;font-size:.8rem"><i class="fa fa-exclamation-triangle me-1"></i>Insufficient</span>';
                    }
                }
                html += '</div>';
            });
            html += '</div>';
            var opts = enrollable.map(function(m){ return '<option value="' + m.id + '">' + esc(m.name) + '</option>'; }).join('');
            html += '<div class="d-flex gap-2 align-items-center flex-wrap">';
            html += '<select id="dojoEnrollMemberSel" class="form-select form-select-sm" style="max-width:200px">' + opts + '</select>';
            // Set initial button state based on first enrollable member
            var firstCr = creditMap[enrollable[0].id];
            var firstNoCredits = firstCr && !firstCr.unlimited && cost > 0 && firstCr.balance < cost;
            if (firstNoCredits) {
                html += '<button class="btn btn-sm btn-danger" disabled id="dojoEnrollBtn" data-session-id="' + session.id + '" data-cost="' + cost + '"><i class="fa fa-times me-1"></i>No Credits Remaining</button>';
            } else {
                html += '<button class="btn btn-primary btn-sm" id="dojoEnrollBtn" data-session-id="' + session.id + '" data-cost="' + cost + '">Reserve &amp; Enroll</button>';
            }
            html += '</div>';
        } else {
            // Single member: inline credit preview + button
            var m0 = enrollable[0];
            var mid = m0.id;
            var cr0 = creditMap[mid];
            var bal0 = cr0 ? cr0.balance : null;
            var unl0 = cr0 ? cr0.unlimited : false;
            var noCredits = !unl0 && cost > 0 && bal0 !== null && bal0 < cost;

            if (!unl0 && bal0 !== null && cost > 0) {
                var after0 = bal0 - cost;
                var b0Cls = bal0 <= 0 ? 'dojo-chip--danger' : bal0 <= 2 ? 'dojo-chip--warning' : 'dojo-chip--success';
                var a0Cls = after0 < 0 ? 'dojo-chip--danger' : after0 <= 2 ? 'dojo-chip--warning' : 'dojo-chip--success';
                html += '<div class="d-flex align-items-center gap-2 mb-3">';
                html += '<span class="fw-semibold" style="font-size:.85rem">' + esc(m0.name) + '</span>';
                html += '<span class="dojo-chip ' + b0Cls + '">' + bal0 + '</span>';
                html += '<span style="color:#5f6368">&#8594;</span>';
                html += '<span class="dojo-chip ' + a0Cls + '">' + after0 + '</span>';
                html += '<span style="color:#5f6368;font-size:.8rem">credits after enrollment</span>';
                html += '</div>';
            }

            if (noCredits) {
                html += '<button class="btn btn-sm btn-danger" disabled id="dojoEnrollBtn" data-session-id="' + session.id + '" data-member-id="' + mid + '"><i class="fa fa-times me-1"></i>No Credits Remaining</button>';
            } else {
                html += '<button class="btn btn-primary btn-sm" id="dojoEnrollBtn" data-session-id="' + session.id + '" data-member-id="' + mid + '">' +
                    (unl0 ? '<i class="fa fa-unlock me-1"></i>' : '<i class="fa fa-calendar-check-o me-1"></i>') +
                    'Reserve &amp; Enroll ' + esc(m0.name) + '</button>';
            }
        }
        html += '<div id="dojoEnrollMsg" class="mt-2 small"></div></div>';
        return html;
    }

    /* ── Overlay ─────────────────────────────────────────────────────────── */
    function overlayBody(type, item) {
        if (type === "session") {
            var lvl = b(LEVEL, item.level);
            return '<div class="d-flex align-items-center gap-2 mb-3 mt-1">' +
                '<span class="' + esc(lvl.cls) + '">' + esc(lvl.label) + '</span>' +
                (item.duration_minutes ? '<small style="color:#5f6368;font-weight:600">' + esc(item.duration_minutes) + '&nbsp;min</small>' : '') +
                '</div>' +
                '<h4 class="fw-bold mb-3">' + esc(item.name) + '</h4>' +
                '<dl class="row g-2 mb-0">' +
                '<dt class="col-sm-5 text-muted small">Date &amp; Time</dt><dd class="col-sm-7 small">' + esc(fmtDt(item.start_datetime)) + '</dd>' +
                '<dt class="col-sm-5 text-muted small">Instructor</dt><dd class="col-sm-7 small">'   + esc(item.instructor || "\u2014")       + '</dd>' +
                '<dt class="col-sm-5 text-muted small">Seats</dt><dd class="col-sm-7 small">'        + esc(item.seats_taken) + '/' + esc(item.capacity) + ' taken</dd>' +
                '</dl>' +
                (item.description ? '<div class="mt-3 text-muted small border-top pt-3">' + esc(item.description) + '</div>' : '');
        }
        if (type === "enrollment") {
            var st = b(STATUS, item.status);
            var at = b(ATT_STATE, item.attendance_state);
            return '<div class="d-flex gap-2 mb-3 mt-1"><span class="badge fs-6 ' + esc(st.cls) + '">' + esc(st.label) + '</span><span class="badge fs-6 ' + esc(at.cls) + '">' + esc(at.label) + '</span></div>' +
                '<h4 class="fw-bold mb-3">' + esc(item.session_name) + '</h4>' +
                '<dl class="row g-2 mb-0">' +
                '<dt class="col-sm-5 text-muted small">Member</dt><dd class="col-sm-7 small">'       + esc(item.member_name || "\u2014")          + '</dd>' +
                '<dt class="col-sm-5 text-muted small">Date &amp; Time</dt><dd class="col-sm-7 small">' + esc(fmtDt(item.start_datetime)) + '</dd>' +
                '<dt class="col-sm-5 text-muted small">Instructor</dt><dd class="col-sm-7 small">'   + esc(item.instructor || "\u2014")            + '</dd>' +
                '</dl>';
        }
        var ls = b(LOG_STATUS, item.status);
        return '<div class="mb-3 mt-1"><span class="badge fs-6 ' + esc(ls.cls) + '">' + esc(ls.label) + '</span></div>' +
            '<h4 class="fw-bold mb-3">' + esc(item.session_name || "Session") + '</h4>' +
            '<dl class="row g-2 mb-0">' +
            '<dt class="col-sm-5 text-muted small">Member</dt><dd class="col-sm-7 small">'  + esc(item.member_name || "\u2014")        + '</dd>' +
            '<dt class="col-sm-5 text-muted small">Check-in</dt><dd class="col-sm-7 small">' + esc(fmtDt(item.checkin_datetime)) + '</dd>' +
            (item.note ? '<dt class="col-sm-5 text-muted small">Note</dt><dd class="col-sm-7 small">' + esc(item.note) + '</dd>' : '') +
            '</dl>';
    }

    function openOverlay(type, item, isParent, members, state, onUpdate) {
        var old = document.getElementById("dojoOverlay");
        if (old) old.remove();
        var body = overlayBody(type, item);
        // Enrollment section is only available for parents/guardians
        var hhMembers = (state.household && state.household.members) || [];
        if (type === "session" && isParent) body += enrollSection(item, isParent, members, hhMembers);
        var el = document.createElement("div");
        el.id = "dojoOverlay"; el.className = "dojo-overlay-backdrop";
        el.innerHTML = '<div class="dojo-overlay-panel" role="dialog" aria-modal="true">' +
            '<button type="button" class="btn-close position-absolute top-0 end-0 m-3" id="dojoOverlayClose" aria-label="Close"></button>' +
            body + '</div>';
        document.body.appendChild(el);
        document.body.classList.add("dojo-overlay-open");
        el.addEventListener("click", function(ev){ if (ev.target === el) closeOverlay(); });
        document.getElementById("dojoOverlayClose").addEventListener("click", closeOverlay);

        var enrollBtn = document.getElementById("dojoEnrollBtn");
        if (enrollBtn) {
            // Multi-member dropdown: update button state when selection changes
            var selEl = document.getElementById("dojoEnrollMemberSel");
            if (selEl) {
                var _hhCreditMap = {};
                (hhMembers || []).forEach(function(hm) {
                    var cpp = (hm.plan && hm.plan.credits_per_period) || 0;
                    _hhCreditMap[hm.id] = {
                        balance: hm.credit_balance || 0,
                        unlimited: cpp === 0 && !!hm.plan,
                    };
                });
                var _enrollCost = parseInt(enrollBtn.dataset.cost, 10) || 0;
                selEl.addEventListener("change", function() {
                    var selectedId = parseInt(selEl.value, 10);
                    var cr = _hhCreditMap[selectedId];
                    var noCredits = cr && !cr.unlimited && _enrollCost > 0 && cr.balance < _enrollCost;
                    if (noCredits) {
                        enrollBtn.disabled = true;
                        enrollBtn.className = 'btn btn-sm btn-danger';
                        enrollBtn.innerHTML = '<i class="fa fa-times me-1"></i>No Credits Remaining';
                    } else {
                        enrollBtn.disabled = false;
                        enrollBtn.className = 'btn btn-primary btn-sm';
                        enrollBtn.innerHTML = 'Reserve &amp; Enroll';
                    }
                });
            }
            var origBtnText = enrollBtn.textContent;
            enrollBtn.addEventListener("click", function() {
                var sid = parseInt(enrollBtn.dataset.sessionId, 10);
                var sel = document.getElementById("dojoEnrollMemberSel");
                var mid = sel ? parseInt(sel.value, 10) : parseInt(enrollBtn.dataset.memberId, 10);
                if (!sid || !mid) return;
                enrollBtn.disabled = true; enrollBtn.textContent = "Enrolling\u2026";
                var form = new FormData();
                form.set('session_id', sid); form.set('member_id', mid); form.set('csrf_token', getCsrfToken());
                fetch('/my/dojo/enroll', { method:'POST', credentials:'same-origin', body:form })
                    .then(function(r){ return r.json(); })
                    .then(function(res){
                        if (res.ok) {
                            // Refresh all relevant state, then close overlay and re-render
                            Promise.all([
                                fetchJson("/my/dojo/json/enrollments"),
                                fetchJson("/my/dojo/json/schedule"),
                                fetchJson("/my/dojo/json/household"),
                            ]).then(function(results) {
                                state.enrollments = (results[0] && results[0].enrollments) || state.enrollments;
                                state.sessions    = (results[1] && results[1].sessions)    || state.sessions;
                                if (results[2] && results[2].members) state.household = results[2];
                                closeOverlay();
                                if (onUpdate) onUpdate();
                            });
                        } else {
                            var msg = document.getElementById("dojoEnrollMsg");
                            if (msg) msg.innerHTML = '<span class="text-danger"><i class="fa fa-times me-1"></i>' + esc(res.error || 'Could not enroll.') + '</span>';
                            enrollBtn.disabled = false; enrollBtn.textContent = origBtnText;
                        }
                    }).catch(function(){
                        var msg = document.getElementById("dojoEnrollMsg");
                        if (msg) msg.innerHTML = '<span class="text-danger">An error occurred.</span>';
                        enrollBtn.disabled = false; enrollBtn.textContent = origBtnText;
                    });
            });
        }
    }

    function closeOverlay() {
        var el = document.getElementById("dojoOverlay");
        if (el) el.remove();
        document.body.classList.remove("dojo-overlay-open");
    }
    /* ── Student switcher (dropdown) ────────────────────────────────────── */
    function studentSwitcherHtml(students, selectedId) {
        if (!students || !students.length) return '';
        var html = '<div class="dojo-student-switcher mb-3">';
        html += '<div class="py-2 px-3 d-flex align-items-center gap-2 flex-wrap">';
        html += '<label style="color:#5f6368;font-size:.8rem;font-weight:600;margin-bottom:0;flex-shrink:0"><i class="fa fa-user-circle me-1"></i>Viewing student:</label>';
        html += '<select class="form-select form-select-sm dojo-student-select" id="dojoStudentSelect" style="max-width:220px">';
        html += '<option value=""' + (!selectedId ? ' selected' : '') + '>All Students</option>';
        students.forEach(function(s) {
            html += '<option value="' + s.id + '"' + (s.id === selectedId ? ' selected' : '') + '>' + esc(s.name) + '</option>';
        });
        html += '</select>';
        html += '</div></div>';
        return html;
    }

    function studentBeltBannerHtml(belt) {
        if (!belt) return '';
        var rank = belt.current_rank;
        if (!rank) return '';
        var color = rank.color || '#cccccc';
        var pct = belt.rank_pct || 0;
        var html = '<div class="dojo-student-context-banner mb-3" style="border-left:3px solid ' + esc(color) + '">';
        html += '<div class="py-2 px-3 d-flex align-items-center gap-3">';;
        html += '<div style="width:32px;height:32px;border-radius:50%;background:' + esc(color) + ';flex-shrink:0;"></div>';
        html += '<div class="flex-grow-1">';
        html += '<div class="fw-semibold" style="font-size:.85rem;color:#202124">' + esc(rank.name) + '</div>';
        html += '<div class="dojo-progress mt-1" style="max-width:180px"><div class="dojo-progress-bar" role="progressbar" style="width:' + pct + '%;background:' + esc(color) + '"></div></div>';
        html += '</div>';
        if (belt.next_rank) html += '<small style="color:#5f6368">Next: ' + esc(belt.next_rank.name) + '</small>';
        html += '</div></div>';
        return html;
    }

    /* ── Belt rail ───────────────────────────────────────────────────── */
    function _isDark(hexColor) {
        try {
            var c = (hexColor || '').replace('#', '');
            if (c.length === 3) c = c[0]+c[0]+c[1]+c[1]+c[2]+c[2];
            var r = parseInt(c.substr(0,2),16), g = parseInt(c.substr(2,2),16), b = parseInt(c.substr(4,2),16);
            return (r*299 + g*587 + b*114) / 1000 < 128;
        } catch(e) { return false; }
    }

    function beltRailHtml(beltPath, currentRankId, nextRankId) {
        if (!beltPath || !beltPath.length) return '<p class="text-muted small fst-italic">No belt path defined for this program.</p>';
        var curIdx = beltPath.findIndex(function(r){ return r.id === currentRankId; });
        var html = '<div class="dojo-belt-rail d-flex align-items-center flex-wrap">';
        beltPath.forEach(function(rank, i) {
            var isCurrent = rank.id === currentRankId;
            var isNext    = rank.id === nextRankId;
            var isAchieved = curIdx >= 0 && i < curIdx;
            var nodeColor = rank.color || '#cccccc';
            var txtColor  = _isDark(nodeColor) ? '#fff' : '#333';
            var bgStyle   = (isCurrent || isAchieved) ? 'background:' + esc(nodeColor) + ';' : 'background:#f0f0f0;';
            var borderSt  = isCurrent  ? 'border:3px solid ' + esc(nodeColor) + ';box-shadow:0 0 0 3px rgba(0,0,0,.12);'
                          : isNext     ? 'border:2px dashed ' + esc(nodeColor) + ';'
                          : isAchieved ? 'border:2px solid ' + esc(nodeColor) + ';'
                          :              'border:2px solid #dee2e6;';
            html += '<div class="text-center" style="min-width:52px">';
            html += '<div class="dojo-belt-node mx-auto d-flex align-items-center justify-content-center" title="' + esc(rank.name) + '"';
            html += ' style="width:36px;height:36px;border-radius:50%;' + bgStyle + borderSt + '">';
            if (isCurrent)   html += '<i class="fa fa-star" style="color:' + txtColor + ';font-size:13px"></i>';
            else if (isAchieved) html += '<i class="fa fa-check" style="color:' + txtColor + ';font-size:11px"></i>';
            html += '</div>';
            html += '<div class="dojo-belt-label" style="font-size:.6rem;line-height:1.1;margin-top:2px;color:#666;word-break:break-word">' + esc(rank.name) + '</div>';
            html += '</div>';
            if (i < beltPath.length - 1) {
                html += '<div style="flex:1;min-width:6px;height:2px;background:#dee2e6;margin-bottom:18px"></div>';
            }
        });
        html += '</div>';
        return html;
    }

    /* ── Programs tab: all students overview (parent, no student selected) ── */
    function allStudentsProgramsHtml(studentPrograms) {
        if (!studentPrograms || !studentPrograms.length) {
            return '<div class="alert alert-info"><i class="fa fa-info-circle me-2"></i>No student programs found. Make sure your students are enrolled in classes.</div>';
        }
        var html = '';
        studentPrograms.forEach(function(student) {
            html += '<div class="mb-5">';
            html += '<div class="d-flex align-items-center gap-2 mb-3">';
                html += '<div class="rounded-circle flex-shrink-0" style="width:34px;height:34px;border-radius:50%;background:#1a73e8;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:.85rem">' + esc((student.name || '?')[0].toUpperCase()) + '</div>';
                html += '<h5 class="fw-bold mb-0" style="color:#202124">' + esc(student.name) + '</h5>';
            if (student.programs && student.programs.length) {
                html += '<span class="dojo-chip dojo-chip--neutral ms-1">' + student.programs.length + ' program' + (student.programs.length !== 1 ? 's' : '') + '</span>';
            }
            html += '</div>';
            if (!student.programs || !student.programs.length) {
                html += '<div class="alert alert-light border py-2 small"><i class="fa fa-info-circle me-1"></i>No programs found for this student.</div>';
            } else {
                html += programsTabHtml(student.programs, student.belt_history || [], student.id, true);
            }
            html += '</div>';
        });
        return html;
    }

    /* ── Programs tab ─────────────────────────────────────────────────── */
    function programsTabHtml(programs, beltHistory, selectedMemberId, isParent) {
        if (!programs || !programs.length) {
            return '<div class="alert alert-info"><i class="fa fa-info-circle me-2"></i>No programs found. Contact your instructor or subscribe to a program to get started.</div>';
        }

        var activePrograms   = programs.filter(function(p){ return p.is_active !== false; });
        var previousPrograms = programs.filter(function(p){ return p.is_active === false; });

        function programCardHtml(prog, isMuted) {
            var progColor = isMuted ? '#9aa0a6' : (prog.color || '#6C757D');
            var html = '';
            html += '<div class="dojo-program-card mb-4" style="border-left:4px solid ' + esc(progColor) + (isMuted ? ';opacity:.75' : '') + '">';
            html += '<div class="p-4">';
            html += '<div class="d-flex align-items-start justify-content-between gap-2 mb-3">';
            html += '<div><h5 class="fw-bold mb-0">' + esc(prog.name) + '</h5>';
            if (prog.code) html += '<span class="dojo-chip dojo-chip--neutral mt-1">' + esc(prog.code) + '</span>';
            if (isMuted) html += '<span class="dojo-chip dojo-chip--neutral ms-1" style="color:#9aa0a6">Previous</span>';
            html += '</div>';
            if (!isMuted && prog.current_rank_id !== null) {
                if (prog.test_invite_pending) {
                    html += '<span class="dojo-chip dojo-chip--success align-self-start"><i class="fa fa-check me-1"></i>Belt Test Requested</span>';
                } else {
                    html += '<button class="btn btn-sm btn-outline-warning dojo-test-request-btn flex-shrink-0" data-member-id="' + esc(selectedMemberId || '') + '"><i class="fa fa-trophy me-1"></i>Request Belt Test</button>';
                }
            }
            html += '</div>';
            if (prog.templates && prog.templates.length) {
                html += '<div class="d-flex flex-wrap gap-1 mb-3">';
                prog.templates.forEach(function(t) {
                    var lvl = b(LEVEL, t.level);
                    html += '<span class="' + esc(lvl.cls) + '" title="' + esc(lvl.label) + '"><i class="fa fa-calendar me-1"></i>' + esc(t.name) + '</span>';
                });
                html += '</div>';
            }
            if (prog.belt_path && prog.belt_path.length) {
                html += '<div class="mb-3">';
                html += '<div class="d-flex align-items-center justify-content-between mb-2">';
                html += '<p class="dojo-field-lbl mb-0">Belt Progression</p>';
                if (prog.current_rank_name) {
                    var rankColor = prog.current_rank_color || '#cccccc';
                    html += '<div class="d-flex align-items-center gap-2">';
                    html += '<div style="width:14px;height:14px;border-radius:50%;background:' + esc(rankColor) + ';border:2px solid rgba(0,0,0,.15);flex-shrink:0"></div>';
                    html += '<span style="font-size:.85rem;font-weight:600;color:#202124">' + esc(prog.current_rank_name) + '</span>';
                    if (prog.rank_position && prog.rank_total) {
                        html += '<span style="color:#5f6368;font-size:.8rem">(' + prog.rank_position + '/' + prog.rank_total + ')</span>';
                    }
                    html += '</div>';
                } else {
                    html += '<span style="color:#5f6368;font-size:.85rem;font-style:italic">No rank yet</span>';
                }
                html += '</div>';
                html += beltRailHtml(prog.belt_path, prog.current_rank_id, prog.next_rank_id);
                if (prog.next_rank_name && prog.rank_pct > 0) {
                    html += '<div class="d-flex align-items-center gap-2 mt-2">';
                    html += '<div class="dojo-progress flex-grow-1" style="max-width:180px"><div class="dojo-progress-bar" role="progressbar" style="width:' + prog.rank_pct + '%;background:' + esc(progColor) + '"></div></div>';
                    html += '<small style="color:#5f6368">Next: <strong>' + esc(prog.next_rank_name) + '</strong></small>';
                    html += '</div>';
                } else if (!prog.current_rank_name) {
                    html += '<div class="mt-2"><small class="text-muted fst-italic">Complete sessions to advance through the belt path.</small></div>';
                } else if (!prog.next_rank_name && prog.current_rank_name) {
                    html += '<div class="mt-2"><small class="text-success fw-semibold"><i class="fa fa-trophy me-1"></i>Highest rank achieved!</small></div>';
                }
                html += '</div>';
            }
            if (prog.rank_history && prog.rank_history.length) {
                html += '<div class="border-top pt-3 mt-2 mb-3">';
                html += '<p class="dojo-field-lbl mb-2"><i class="fa fa-history me-1"></i>Rank History</p>';
                html += '<div class="vstack gap-2">';
                prog.rank_history.forEach(function(h) {
                    var rc = h.rank_color || '#cccccc';
                    html += '<div class="dojo-rank-row">';
                    html += '<div style="width:20px;height:20px;border-radius:50%;background:' + esc(rc) + ';border:2px solid rgba(0,0,0,.12);flex-shrink:0"></div>';
                    html += '<div class="flex-grow-1"><div style="font-size:.85rem;font-weight:600;color:#202124">' + esc(h.rank_name) + '</div>';
                    if (h.awarded_by) html += '<div style="color:#5f6368;font-size:.75rem">Awarded by ' + esc(h.awarded_by) + '</div>';
                    html += '</div>';
                    if (h.date_awarded) html += '<small style="color:#5f6368;flex-shrink:0">' + esc(fmtDate(h.date_awarded)) + '</small>';
                    html += '</div>';
                });
                html += '</div></div>';
            }
            if (!isMuted) {
                html += '<div class="border-top pt-3 mt-2">';
                html += '<p class="dojo-field-lbl mb-2"><i class="fa fa-envelope me-1"></i>Message Instructor</p>';
                html += '<div class="d-flex gap-2">';
                html += '<textarea class="form-control form-control-sm dojo-msg-input" id="dojoMsgInput_' + prog.id + '" rows="2" placeholder="Write a message to your instructor\u2026" style="resize:none"></textarea>';
                html += '<button class="btn btn-sm btn-outline-primary dojo-msg-send-btn" data-program-id="' + prog.id + '" data-member-id="' + esc(selectedMemberId || '') + '" style="height:fit-content;align-self:flex-end">Send</button>';
                html += '</div><div class="dojo-msg-feedback small mt-1" id="dojoMsgFeedback_' + prog.id + '"></div>';
                html += '</div>';
            }
            html += '</div></div>';
            return html;
        }

        var html = '';

        if (activePrograms.length) {
            activePrograms.forEach(function(prog) { html += programCardHtml(prog, false); });
        } else {
            html += '<div class="alert alert-info mb-3"><i class="fa fa-info-circle me-2"></i>No active programs. See previous programs below.</div>';
        }

        if (previousPrograms.length) {
            html += '<details class="mt-2">';
            html += '<summary class="dojo-field-lbl mb-3" style="cursor:pointer;list-style:none;display:flex;align-items:center;gap:.4rem">'
                  + '<i class="fa fa-history me-1"></i>Previous Programs (' + previousPrograms.length + ')'
                  + '</summary>';
            previousPrograms.forEach(function(prog) { html += programCardHtml(prog, true); });
            html += '</details>';
        }

        return html;
    }

    /* ── Auto-Enroll Preferences section ────────────────────────────────── */
    var DAYS = [
        { key: 'mon', label: 'Mon' }, { key: 'tue', label: 'Tue' },
        { key: 'wed', label: 'Wed' }, { key: 'thu', label: 'Thu' },
        { key: 'fri', label: 'Fri' }, { key: 'sat', label: 'Sat' },
        { key: 'sun', label: 'Sun' },
    ];
    function autoEnrollSectionHtml(prefs, selectedStudentId) {
        // Filter to selected student if one is chosen
        var filtered = prefs;
        if (selectedStudentId) {
            filtered = prefs.filter(function(p){ return p.member_id === selectedStudentId; });
        }
        var html = '<div class="mb-4">';
        html += '<p class="text-muted small mb-3">Toggle a class on to be automatically added to its sessions. Choose which days you want and whether to enrol permanently or just this week.</p>';
        if (!filtered.length) {
            html += '<div class="alert alert-info"><i class="fa fa-info-circle me-2"></i>No recurring classes are available yet.</div>';
            html += '</div>';
            return html;
        }
        filtered.forEach(function(p) {
            var key = p.member_id + '_' + p.template_id;
            var isEnrolled = p.enrolled || p.active;
            html += '<div class="dojo-auto-enroll-card mb-3" '
                  + 'data-member-id="' + p.member_id + '" '
                  + 'data-template-id="' + p.template_id + '">';
            if (isEnrolled) {
                html += '<div style="height:3px;background:#188038;border-radius:4px 4px 0 0"></div>';
            } else {
                html += '<div style="height:3px;background:#e0e0e0;border-radius:4px 4px 0 0"></div>';
            }
            html += '<div class="p-3">';
            // Header row: name + on/off toggle
            html += '<div class="d-flex justify-content-between align-items-center mb-2">';
            html += '<div>';
            html += '<span class="fw-semibold">' + esc(p.template_name) + '</span>';
            if (p.program_name) html += ' <span class="dojo-chip dojo-chip--neutral ms-1">' + esc(p.program_name) + '</span>';
            if (!p.active && p.has_pref) html += ' <span class="dojo-chip dojo-chip--danger ms-1">Opted out</span>';
            if (p.member_name && !selectedStudentId) html += '<div class="text-muted small">' + esc(p.member_name) + '</div>';
            html += '</div>';
            html += '<div class="form-check form-switch mb-0">';
            html += '<input class="form-check-input dojo-ae-active" type="checkbox" role="switch" '
                  + 'id="ae-active-' + key + '" '
                  + (p.active ? 'checked' : '') + ' data-key="' + key + '">';
            html += '<label class="form-check-label" for="ae-active-' + key + '">' + (p.active ? 'On' : 'Off') + '</label>';
            html += '</div></div>';
            // Detailed controls (hidden when off)
            html += '<div class="dojo-ae-details" id="ae-details-' + key + '" style="' + (p.active ? '' : 'display:none') + '">';
            html += '<hr class="my-2">';
            // Mode picker
            html += '<div class="d-flex gap-2 mb-3 align-items-center">';
            html += '<span class="text-muted small me-1">Mode:</span>';
            html += '<button class="btn btn-sm dojo-ae-mode-btn ' + (p.mode !== 'multiday' ? 'btn-primary' : 'btn-outline-secondary') + '" '
                  + 'data-key="' + key + '" data-mode="permanent"><i class="fa fa-infinity me-1"></i>Never Remove</button>';
            html += '<button class="btn btn-sm dojo-ae-mode-btn ' + (p.mode === 'multiday' ? 'btn-primary' : 'btn-outline-secondary') + '" '
                  + 'data-key="' + key + '" data-mode="multiday"><i class="fa fa-calendar-o me-1"></i>Multiday Range</button>';
            html += '</div>';
            // Date range inputs (visible only for multiday mode)
            var isMultiday = p.mode === 'multiday';
            html += '<div class="dojo-ae-date-range d-flex flex-wrap gap-2 align-items-center mb-3" id="ae-daterange-' + key + '" style="' + (isMultiday ? '' : 'display:none') + '">';
            html += '<span class="text-muted small">From:</span>';
            html += '<input type="date" class="form-control form-control-sm dojo-ae-date-from" id="ae-datefrom-' + key + '" style="max-width:150px" value="' + esc(p.date_from || '') + '">';
            html += '<span class="text-muted small">To:</span>';
            html += '<input type="date" class="form-control form-control-sm dojo-ae-date-to" id="ae-dateto-' + key + '" style="max-width:150px" value="' + esc(p.date_to || '') + '">';
            html += '</div>';
            // Day checkboxes
            html += '<div class="mb-1"><span class="text-muted small">Days:</span></div>';
            html += '<div class="d-flex flex-wrap gap-2 mb-3">';
            DAYS.forEach(function(d) {
                var tmplActive = p['tmpl_rec_' + d.key];
                var prefChecked = p['pref_' + d.key];
                var allEmpty = !DAYS.some(function(x){ return p['pref_' + x.key]; });
                var isChecked = allEmpty ? tmplActive : prefChecked;
                html += '<label class="btn btn-sm ' + (isChecked ? 'btn-primary' : 'btn-outline-secondary') + ' dojo-ae-day-btn'
                      + (tmplActive ? '' : ' disabled') + '" '
                      + 'title="' + (tmplActive ? d.label : 'Class doesn\'t run on ' + d.label) + '">';
                html += '<input type="checkbox" class="d-none dojo-ae-day-chk" '
                      + 'data-key="' + key + '" data-day="' + d.key + '" '
                      + (isChecked ? 'checked' : '') + ' '
                      + (tmplActive ? '' : 'disabled') + '>';
                html += d.label + '</label>';
            });
            html += '</div>';
            html += '<p class="text-muted small mb-2">Leave all days un-ticked to enrol on every day the class runs.</p>';
            html += '</div>'; // .dojo-ae-details
            // Save button always visible
            html += '<div class="mt-2">';
            html += '<button class="btn btn-sm btn-success dojo-ae-save-btn" data-key="' + key + '">';
            html += '<i class="fa fa-check me-1"></i>Save</button>';
            html += '<span class="dojo-ae-saved-msg ms-2 text-success small" id="ae-saved-' + key + '" style="display:none"><i class="fa fa-check-circle me-1"></i>Saved!</span>';
            html += '</div>';
            html += '</div></div>'; // .dojo-auto-enroll-card
        });
        html += '</div>';
        return html;
    }

    /* ── Classes tab (merged schedule + enrollments) ────────────────────── */
    /* ── Per-member credit strip (above available sessions) ───────────── */
    function memberCreditStripHtml(enrollableMembers, hhData) {
        var hhMems = (hhData && hhData.members) || [];
        var creditMap = {};
        hhMems.forEach(function(hm) {
            var cpp = (hm.plan && hm.plan.credits_per_period) || 0;
            creditMap[hm.id] = {
                name: hm.name,
                balance: hm.credit_balance || 0,
                pending: hm.credit_pending || 0,
                creditsPerPeriod: cpp,
                unlimited: cpp === 0 && !!hm.plan,
            };
        });
        var relevant = enrollableMembers.filter(function(m) { return !!creditMap[m.id]; });
        if (!relevant.length) return '';
        var html = '<div class="d-flex flex-wrap gap-2 mb-3">';
        relevant.forEach(function(m) {
            var cr = creditMap[m.id];
            if (!cr) return;
            html += '<div class="dojo-credit-item">';
            html += '<span class="fw-semibold" style="color:#202124">' + esc(cr.name) + '</span>';
            if (cr.unlimited) {
                html += '<span class="dojo-chip dojo-chip--success"><i class="fa fa-unlock me-1"></i>Unlimited</span>';
            } else {
                var chipCls = cr.balance <= 0 ? 'dojo-chip--danger' : cr.balance <= 2 ? 'dojo-chip--warning' : 'dojo-chip--success';
                html += '<span class="dojo-chip ' + chipCls + '">' + cr.balance + ' credit' + (cr.balance !== 1 ? 's' : '') + '</span>';
                if (cr.pending < 0) {
                    html += '<span style="color:#5f6368;font-size:.75rem"><i class="fa fa-clock-o me-1"></i>' + Math.abs(cr.pending) + ' held</span>';
                }
            }
            html += '</div>';
        });
        html += '</div>';
        return html;
    }

    function classesTabHtml(enrollments, sessions, isParent, members, autoEnrollPrefs, selectedStudentId, hhData) {
        var now = new Date();
        function dt(iso) { return iso ? new Date(iso.indexOf('T') !== -1 ? iso + 'Z' : iso) : null; }
        var active = (enrollments || []).filter(function(e){ return e.status !== 'cancelled'; });
        var upcoming = active.filter(function(e){ var d = dt(e.start_datetime); return d && d > now; });
        var past     = active.filter(function(e){ var d = dt(e.start_datetime); return d && d <= now; });
        var html = '';
        html += '<div class="dojo-classes-section mb-4">';
        html += '<h6 class="dojo-classes-section-header fw-semibold mb-3"><i class="fa fa-calendar-check-o me-2 text-success"></i>Upcoming Enrolled Sessions</h6>';
        if (upcoming.length) {
            html += '<div class="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">';
            upcoming.forEach(function(e) {
                var clr = STATUS_CLR[e.status] || '#6c757d';
                var lvl = b(LEVEL, e.level);
                html += '<div class="col"><div class="dojo-md3-card dojo-md3-card--clickable h-100" style="border-left:3px solid ' + esc(clr) + '" data-type="enrollment" data-id="' + e.id + '">';
                html += '<div class="p-3">';
                html += '<div class="d-flex justify-content-between align-items-start mb-2">';
                html += '<span class="' + esc(lvl.cls) + '">' + esc(lvl.label) + '</span>';
                html += '<span class="dojo-chip dojo-chip--success">Registered</span>';
                html += '</div>';
                html += '<h6 class="fw-bold mb-2 lh-sm" style="color:#202124">' + esc(e.session_name) + '</h6>';
                if (e.program_name) html += '<div style="color:#5f6368;font-size:.8rem;margin-bottom:.25rem"><i class="fa fa-tag me-1"></i>' + esc(e.program_name) + '</div>';
                html += '<div class="vstack gap-1 mb-3" style="color:#5f6368;font-size:.8rem">';
                html += '<div><i class="fa fa-calendar-o me-1"></i>' + esc(fmtDt(e.start_datetime)) + '</div>';
                if (e.instructor)   html += '<div><i class="fa fa-user me-1"></i>' + esc(e.instructor) + '</div>';
                if (e.member_name)  html += '<div><i class="fa fa-graduation-cap me-1"></i>' + esc(e.member_name) + '</div>';
                html += '</div>';
                html += '<button class="btn btn-sm btn-outline-danger dojo-cancel-enroll-btn" data-enrollment-id="' + e.id + '">Cancel</button>';
                html += '</div></div></div>';
            });
            html += '</div>';
        } else {
            html += '<div class="alert alert-light border py-2 small">No upcoming enrolled sessions.</div>';
        }
        html += '</div>';
        if (isParent && sessions && sessions.length) {
            var enrolledSids = {};
            active.forEach(function(e){ if (e.session_id) enrolledSids[e.session_id] = true; });
            var available = sessions.filter(function(s){ return !enrolledSids[s.id]; });
            if (available.length) {
                html += '<div class="dojo-classes-section mb-4">';
                html += '<h6 class="dojo-classes-section-header fw-semibold mb-3"><i class="fa fa-calendar-plus-o me-2 text-primary"></i>Available Sessions</h6>';
                var enrollableMembers = members.filter(function(m){ return m.is_student; });
                html += memberCreditStripHtml(enrollableMembers, hhData);
                html += '<div class="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">';
                available.forEach(function(s){ html += sessionCard(s); });
                html += '</div></div>';
            }
        }
        if (past.length) {
            html += '<div class="dojo-classes-section">';
            html += '<h6 class="dojo-classes-section-header fw-semibold mb-3"><i class="fa fa-history me-2" style="color:#5f6368"></i>Past Sessions <span class="dojo-chip dojo-chip--neutral ms-1">' + past.length + '</span></h6>';
            html += '<div class="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">';
            past.forEach(function(e) {
                var at  = b(ATT_STATE, e.attendance_state);
                var clr = LOG_CLR[e.attendance_state] || '#5f6368';
                html += '<div class="col"><div class="dojo-md3-card h-100" style="border-left:3px solid ' + esc(clr) + ';opacity:.8" data-type="enrollment" data-id="' + e.id + '">';
                html += '<div class="p-3">';
                html += '<div class="d-flex justify-content-between align-items-start mb-2">';
                html += '<span class="' + esc(at.cls) + '">' + esc(at.label) + '</span>';
                html += '</div>';
                html += '<h6 class="fw-bold mb-2 lh-sm" style="color:#202124">' + esc(e.session_name) + '</h6>';
                if (e.program_name) html += '<div style="color:#5f6368;font-size:.8rem;margin-bottom:.25rem"><i class="fa fa-tag me-1"></i>' + esc(e.program_name) + '</div>';
                html += '<div class="vstack gap-1" style="color:#5f6368;font-size:.8rem">';
                html += '<div><i class="fa fa-calendar-o me-1"></i>' + esc(fmtDt(e.start_datetime)) + '</div>';
                if (e.instructor) html += '<div><i class="fa fa-user me-1"></i>' + esc(e.instructor) + '</div>';
                html += '</div></div></div></div>';
            });
            html += '</div></div>';
        }
        return html;
    }
    /* ── Render ──────────────────────────────────────────────────────────── */
    function render(root, state, isParent, members, students, isStudentOnly) {
        students     = students     || [];
        isStudentOnly = !!isStudentOnly;
        var TABS = [
            { key:"programs",    icon:"fa-graduation-cap", label:"Programs"     },
            { key:"classes",     icon:"fa-calendar",       label:"Classes"      },
            { key:"auto_enroll", svg:'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-.15em" class="me-1"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 .49-3"/></svg>', label:"Auto-Enroll"  },
            { key:"attendance",  icon:"fa-check-circle",   label:"Attendance"   },
            { key:"household",   icon:"fa-home",           label:"My Household" },
        ];
        if (isParent) TABS.push({ key:"billing", icon:"fa-credit-card", label:"Billing" });
        var navHtml = TABS.map(function(t){
            var active = state.activeTab === t.key ? " active" : "";
            var aeEnrolled = t.key==="auto_enroll" ? (state.autoEnrollPrefs||[]).filter(function(p){ return p.active; }).length : 0;
            var cnt = t.key==="programs"?state.programs.length : t.key==="classes"?(state.enrollments||[]).filter(function(e){return e.status!=='cancelled';}).length : t.key==="attendance"?state.logs.length : t.key==="billing"?(state.billing?(state.billing.invoices||[]).length:0) : aeEnrolled;
            var badge = cnt ? '<span class="dojo-chip dojo-chip--neutral ms-1">' + cnt + '</span>' : "";
            var iconHtml = t.svg ? t.svg : '<i class="fa ' + t.icon + ' me-1"></i>';
            return '<button type="button" role="tab" class="dojo-tab-btn' + active +
                   '" data-tab="' + t.key + '">' + iconHtml + t.label + badge + '</button>';
        }).join("");

        var body;
        if (state.loading) {
            body = '<div class="d-flex justify-content-center py-5"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading\u2026</span></div></div>';
        } else if (state.activeTab === "programs") {
            if (isParent && !state.selectedStudentId) {
                body = allStudentsProgramsHtml(state.studentPrograms);
            } else {
                var _memberId = state.selectedStudentId || parseInt(root.dataset.memberId, 10);
                // For 'both'-role members the server returns programs inside studentPrograms,
                // not in the top-level programs array.  Fall back to the student record when
                // state.programs is empty but a student is pre-selected.
                var _progs = state.programs;
                var _hist  = state.beltHistory;
                if (!_progs.length && state.selectedStudentId && state.studentPrograms.length) {
                    var _stuData = state.studentPrograms.find(function(s){ return s.id === state.selectedStudentId; });
                    if (_stuData) { _progs = _stuData.programs || []; _hist = _stuData.belt_history || []; }
                }
                body = programsTabHtml(_progs, _hist, _memberId, isParent);
            }
        } else if (state.activeTab === "classes") {
            body = classesTabHtml(state.enrollments, state.sessions, isParent, members, state.autoEnrollPrefs, state.selectedStudentId, state.household);
        } else if (state.activeTab === "auto_enroll") {
            if (isParent && !state.selectedStudentId && students.length > 0) {
                body = '<div class="alert alert-info mt-2"><i class="fa fa-info-circle me-2"></i>'
                     + 'Select a student using the switcher above to manage their auto-enroll preferences.</div>';
            } else {
                body = autoEnrollSectionHtml(state.autoEnrollPrefs, state.selectedStudentId || null);
            }
        } else if (state.activeTab === "attendance") {
            body = state.logs.length
                ? '<div class="row row-cols-1 row-cols-md-2 row-cols-xl-3 g-3">' + state.logs.map(attendanceCard).join("") + '</div>'
                : '<div class="alert alert-info">No attendance records yet.</div>';
        } else if (state.activeTab === "billing") {
            body = billingTabHtml(state.billing, isParent);
        } else {
            body = householdTabHtml(state.household, isParent);
        }

        // Prepend student switcher for parents
        var extraHtml = '';
        if (isParent && students.length > 1) {
            extraHtml += studentSwitcherHtml(students, state.selectedStudentId);
        }
        root.innerHTML = extraHtml +
                         '<nav class="dojo-tab-nav mb-3" role="tablist">' + navHtml + '</nav>' +
                         '<div id="dojoTabContent" class="mt-3">' + body + '</div>';

        /* ── refreshForStudent: re-fetch all data scoped to one student ── */
        function refreshForStudent(studentId) {
            state.selectedStudentId   = studentId || null;
            state.selectedStudentBelt = null;
            state.loading = true;
            render(root, state, isParent, members, students, isStudentOnly);
            var qs = studentId ? '?member_id=' + studentId : '';
            Promise.all([
                fetchJson('/my/dojo/json/schedule'     + qs),
                fetchJson('/my/dojo/json/enrollments'  + qs),
                fetchJson('/my/dojo/json/attendance'   + qs),
                fetchJson('/my/dojo/json/programs'     + qs),
                studentId ? fetchJson('/my/dojo/json/belt?member_id='         + studentId) : Promise.resolve(null),
                studentId ? fetchJson('/my/dojo/json/belt-history?member_id=' + studentId) : Promise.resolve(null),
                fetchJson('/my/dojo/json/auto-enroll' + qs),
            ]).then(function(r) {
                state.sessions            = r[0].sessions    || [];
                state.enrollments         = r[1].enrollments || [];
                state.logs                = r[2].logs        || [];
                state.programs            = r[3].programs    || [];
                state.selectedStudentBelt = r[4];
                state.beltHistory         = r[5] ? (r[5].history || []) : [];
                state.autoEnrollPrefs     = r[6] ? (r[6].preferences || []) : [];
                state.loading = false;
                render(root, state, isParent, members, students, isStudentOnly);
            });
        }

        /* ── Student switcher clicks ── */
        var studentSel = document.getElementById('dojoStudentSelect');
        if (studentSel) {
            studentSel.addEventListener('change', function() {
                var val = parseInt(this.value, 10);
                refreshForStudent(isNaN(val) ? null : val);
            });
        }

        root.querySelectorAll('.dojo-cancel-enroll-btn').forEach(function(btn) {
            btn.addEventListener('click', function(ev) {
                ev.stopPropagation();
                var eid = parseInt(btn.dataset.enrollmentId, 10);
                if (!eid || !confirm('Cancel this enrollment?')) return;
                btn.disabled = true; btn.textContent = 'Cancelling\u2026';
                var form = new FormData(); form.set('enrollment_id', eid); form.set('csrf_token', getCsrfToken());
                fetch('/my/dojo/unenroll', { method: 'POST', credentials: 'same-origin', body: form })
                    .then(function(r){ return r.json(); })
                    .then(function(res){
                        if (res.ok) {
                            // Refresh enrollments, sessions and household credits then re-render
                            Promise.all([
                                fetchJson('/my/dojo/json/enrollments'),
                                fetchJson('/my/dojo/json/schedule'),
                                fetchJson('/my/dojo/json/household'),
                            ]).then(function(results) {
                                state.enrollments = (results[0] && results[0].enrollments) || state.enrollments;
                                state.sessions    = (results[1] && results[1].sessions)    || state.sessions;
                                if (results[2] && results[2].members) state.household = results[2];
                                render(root, state, isParent, members, students, isStudentOnly);
                            });
                        } else { btn.disabled = false; btn.textContent = 'Cancel'; alert(res.error || 'Could not cancel.'); }
                    }).catch(function(){ btn.disabled = false; btn.textContent = 'Cancel'; });
            });
        });

        /* ── Auto-Enroll: helper to read current card state ── */
        function readCardState(key) {
            var card = root.querySelector('.dojo-auto-enroll-card[data-member-id]');
            // Find card by key (member_id_template_id)
            var cards = root.querySelectorAll('.dojo-auto-enroll-card');
            var found = null;
            cards.forEach(function(c){ if (c.dataset.memberId + '_' + c.dataset.templateId === key) found = c; });
            if (!found) return null;
            var days = {};
            DAYS.forEach(function(d) {
                var chk = found.querySelector('.dojo-ae-day-chk[data-day="' + d.key + '"]');
                days['pref_' + d.key] = chk ? chk.checked : false;
            });
            var modeActive = found.querySelector('.dojo-ae-mode-btn.btn-primary');
            var cardKey = found.dataset.memberId + '_' + found.dataset.templateId;
            var dateFromEl = document.getElementById('ae-datefrom-' + cardKey);
            var dateToEl   = document.getElementById('ae-dateto-'   + cardKey);
            return {
                member_id:   parseInt(found.dataset.memberId, 10),
                template_id: parseInt(found.dataset.templateId, 10),
                active:      found.querySelector('.dojo-ae-active').checked,
                mode:        modeActive ? modeActive.dataset.mode : 'permanent',
                date_from:   dateFromEl ? dateFromEl.value : '',
                date_to:     dateToEl   ? dateToEl.value   : '',
                pref_mon: days.pref_mon, pref_tue: days.pref_tue,
                pref_wed: days.pref_wed, pref_thu: days.pref_thu,
                pref_fri: days.pref_fri, pref_sat: days.pref_sat,
                pref_sun: days.pref_sun,
            };
        }

        /* ── Auto-Enroll: active toggle ── */
        root.querySelectorAll('.dojo-ae-active').forEach(function(chk) {
            chk.addEventListener('change', function() {
                var key = chk.dataset.key;
                var details = document.getElementById('ae-details-' + key);
                if (details) details.style.display = chk.checked ? '' : 'none';
                var lbl = chk.nextElementSibling;
                if (lbl) lbl.textContent = chk.checked ? 'On' : 'Off';
            });
        });

        /* ── Auto-Enroll: mode buttons ── */
        root.querySelectorAll('.dojo-ae-mode-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var key = btn.dataset.key;
                root.querySelectorAll('.dojo-ae-mode-btn[data-key="' + key + '"]').forEach(function(b) {
                    b.classList.remove('btn-primary');
                    b.classList.add('btn-outline-secondary');
                });
                btn.classList.remove('btn-outline-secondary');
                btn.classList.add('btn-primary');
                // Show/hide date range row based on selected mode
                var dateRange = document.getElementById('ae-daterange-' + key);
                if (dateRange) {
                    dateRange.style.display = btn.dataset.mode === 'multiday' ? '' : 'none';
                }
            });
        });

        /* ── Auto-Enroll: day checkboxes ── */
        root.querySelectorAll('.dojo-ae-day-chk').forEach(function(chk) {
            chk.addEventListener('change', function() {
                var lbl = chk.closest('label');
                if (lbl) {
                    if (chk.checked) { lbl.classList.remove('btn-outline-secondary'); lbl.classList.add('btn-primary'); }
                    else             { lbl.classList.remove('btn-primary'); lbl.classList.add('btn-outline-secondary'); }
                }
            });
        });

        /* ── Auto-Enroll: save button ── */
        root.querySelectorAll('.dojo-ae-save-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var key = btn.dataset.key;
                var payload = readCardState(key);
                if (!payload) return;
                btn.disabled = true;
                fetch('/my/dojo/auto-enroll?csrf_token=' + encodeURIComponent(getCsrfToken()), {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                }).then(function(r){ return r.json(); })
                  .then(function(res) {
                    btn.disabled = false;
                    if (res.success) {
                        // Update state.autoEnrollPrefs to reflect saved values
                        var existing = state.autoEnrollPrefs.find(function(p){
                            return p.member_id === payload.member_id && p.template_id === payload.template_id;
                        });
                        if (existing) {
                            Object.assign(existing, payload, { has_pref: true });
                        } else {
                            state.autoEnrollPrefs.push(Object.assign({}, payload, { has_pref: true }));
                        }
                        var msg = document.getElementById('ae-saved-' + key);
                        if (msg) { msg.style.display = 'inline'; setTimeout(function(){ msg.style.display = 'none'; }, 2500); }
                    } else {
                        alert(res.error || 'Could not save preference.');
                    }
                  }).catch(function(){ btn.disabled = false; alert('Network error saving preference.'); });
            });
        });

        root.querySelectorAll('.dojo-test-request-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                if (!confirm('Request a belt test? Your instructor will be notified.')) return;
                btn.disabled = true; btn.textContent = 'Requesting\u2026';
                var mid = btn.dataset.memberId;
                var form = new FormData(); if (mid) form.set('member_id', mid); form.set('csrf_token', getCsrfToken());
                fetch('/my/dojo/belt-test-request', { method: 'POST', credentials: 'same-origin', body: form })
                    .then(function(r){ return r.json(); })
                    .then(function(res){
                        if (res.ok) {
                            state.programs.forEach(function(p){ p.test_invite_pending = true; });
                            render(root, state, isParent, members, students, isStudentOnly);
                        } else { btn.disabled = false; btn.textContent = 'Request Belt Test'; alert(res.error || 'Could not submit.'); }
                    });
            });
        });

        root.querySelectorAll('.dojo-msg-send-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var pid = btn.dataset.programId;
                var mid = btn.dataset.memberId;
                var input    = document.getElementById('dojoMsgInput_' + pid);
                var feedback = document.getElementById('dojoMsgFeedback_' + pid);
                var msg = input ? input.value.trim() : '';
                if (!msg) { if (feedback) feedback.innerHTML = '<span class="text-danger">Please enter a message.</span>'; return; }
                btn.disabled = true; btn.textContent = 'Sending\u2026';
                if (feedback) feedback.innerHTML = '';
                fetch('/my/dojo/message?csrf_token=' + encodeURIComponent(getCsrfToken()), {
                    method: 'POST', credentials: 'same-origin',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: msg, member_id: mid ? parseInt(mid, 10) : null }),
                }).then(function(r){ return r.json(); }).then(function(res){
                    if (res.ok) {
                        if (feedback) feedback.innerHTML = '<span class="text-success"><i class="fa fa-check me-1"></i>Message sent!</span>';
                        if (input) input.value = '';
                    } else {
                        if (feedback) feedback.innerHTML = '<span class="text-danger">' + esc(res.error || 'Could not send.') + '</span>';
                    }
                    btn.disabled = false; btn.textContent = 'Send';
                });
            });
        });

        /* ── Delegated: tab buttons (survive re-renders) ── */
        root.addEventListener("click", function(ev) {
            var btn = ev.target.closest(".dojo-tab-btn");
            if (btn && root.contains(btn)) {
                state.activeTab = btn.dataset.tab;
                render(root, state, isParent, members, students, isStudentOnly);
                var brand = document.querySelector(".o_portal_navbar .navbar-brand");
                if (brand) brand.textContent = TAB_TITLES[btn.dataset.tab] || "Dojo Portal";
                return;
            }

            /* ── Delegated: clickable cards (survive re-renders) ── */
            var card = ev.target.closest(".dojo-md3-card--clickable");
            if (card && root.contains(card)) {
                // Ignore clicks on interactive children (buttons, links)
                if (ev.target.closest("button,a")) return;
                var type = card.dataset.type;
                var id = parseInt(card.dataset.id, 10);
                var item = null;
                if (type === "session")    item = state.sessions.find(function(s){ return s.id === id; });
                if (type === "enrollment") item = state.enrollments.find(function(e){ return e.id === id; });
                if (type === "attendance") item = state.logs.find(function(l){ return l.id === id; });
                if (item) openOverlay(type, item, isParent, members, state, function() {
                    render(root, state, isParent, members, students, isStudentOnly);
                });
            }
        });

        var editBtn = document.getElementById("dojoEditHouseholdBtn");
        if (editBtn) {
            editBtn.addEventListener("click", function(){
                openHouseholdEditOverlay(state.household, members, function(){
                    fetchJson("/my/dojo/json/household").then(function(d){
                        state.household = d;
                        render(root, state, isParent, members, students, isStudentOnly);
                    });
                });
            });
        }

        // ── Billing action buttons (parents only) ─────────────────────────
        function refreshBilling() {
            fetchJson("/my/dojo/json/billing").then(function(d){
                state.billing = d;
                render(root, state, isParent, members, students, isStudentOnly);
            });
        }
        document.querySelectorAll(".dojo-billing-resume").forEach(function(btn) {
            btn.addEventListener("click", function(){
                var subId = btn.getAttribute("data-sub-id");
                var csrfForm = new FormData();
                csrfForm.set('csrf_token', getCsrfToken());
                if (subId) csrfForm.set('subscription_id', subId);
                fetch("/my/dojo/billing/resume", { method:"POST", credentials:"same-origin", body: csrfForm })
                    .then(function(r){ return r.json(); })
                    .then(function(res){ if (res.ok) refreshBilling(); });
            });
        });
        // ── Google Wallet push provisioning ──────────────────────────────
        var walletBtn = document.getElementById("dojoAddToWallet");
        if (walletBtn) {
            walletBtn.addEventListener("click", function() {
                walletBtn.disabled = true;
                walletBtn.textContent = "Loading…";
                fetch("/my/dojo/billing/wallet-provision", {credentials: "same-origin"})
                    .then(function(r) { return r.json(); })
                    .then(function(d) {
                        if (d.error) {
                            alert("Error: " + d.error);
                            walletBtn.disabled = false;
                            walletBtn.innerHTML = '<img src="https://pay.google.com/about/static/images/social/gp_logo.svg" height="18" style="vertical-align:middle;margin-right:6px" alt="">Add to Google Wallet';
                            return;
                        }
                        function doProvision() {
                            Stripe(d.publishable_key).pushProvisioning.push({
                                card: d.stripe_card_id,
                                ephemeralKeySecret: d.ephemeral_key_secret,
                            }).then(function(result) {
                                if (result.error) { alert(result.error.message); }
                                walletBtn.disabled = false;
                                walletBtn.innerHTML = '<img src="https://pay.google.com/about/static/images/social/gp_logo.svg" height="18" style="vertical-align:middle;margin-right:6px" alt="">Add to Google Wallet';
                            });
                        }
                        if (!window.Stripe) {
                            var script = document.createElement("script");
                            script.src = "https://js.stripe.com/v3/";
                            script.onload = doProvision;
                            document.head.appendChild(script);
                        } else {
                            doProvision();
                        }
                    })
                    .catch(function() {
                        alert("Network error");
                        walletBtn.disabled = false;
                        walletBtn.innerHTML = '<img src="https://pay.google.com/about/static/images/social/gp_logo.svg" height="18" style="vertical-align:middle;margin-right:6px" alt="">Add to Google Wallet';
                    });
            });
        }
    }

    /* ── Boot ────────────────────────────────────────────────────────────── */
    function boot() {
        var root = document.getElementById("dojo_activities_mount");
        if (!root) return;

        var isParent      = root.dataset.isParent === 'true';
        var isStudentOnly = root.dataset.isStudentOnly === 'true';
        var members  = [];
        try { members = JSON.parse(root.dataset.members || '[]'); } catch(e){}
        var students = [];
        try { students = JSON.parse(root.dataset.students || '[]'); } catch(e){}

        // For a 'both' role member (student+parent) who is the only student in the
        // household, pre-select themselves so student-scoped tabs (auto-enroll,
        // programs, etc.) render immediately without needing the switcher.
        var autoSelectedStudent = (isParent && students.length === 1) ? students[0].id : null;

        var state = {
            activeTab:          root.dataset.tab || "programs",
            sessions:           [], enrollments: [], logs: [],
            programs:           [], beltHistory: [],
            studentPrograms:    [],
            household:          null,
            billing:            null,
            autoEnrollPrefs:    [],
            selectedStudentId:  autoSelectedStudent,
            selectedStudentBelt: null,
            loading:            true,
        };
        render(root, state, isParent, members, students, isStudentOnly);

        var brand = document.querySelector(".o_portal_navbar .navbar-brand");
        if (brand) brand.textContent = TAB_TITLES[state.activeTab] || "Dojo Portal";

        Promise.all([
            fetchJson("/my/dojo/json/schedule"),
            fetchJson("/my/dojo/json/enrollments"),
            fetchJson("/my/dojo/json/attendance"),
            fetchJson("/my/dojo/json/household"),
            fetchJson("/my/dojo/json/programs"),
            fetchJson("/my/dojo/json/belt-history"),
            isParent ? fetchJson("/my/dojo/json/billing") : Promise.resolve(null),
            fetchJson("/my/dojo/json/auto-enroll"),
        ]).then(function(results){
            state.sessions        = results[0].sessions    || [];
            state.enrollments     = results[1].enrollments || [];
            state.logs            = results[2].logs        || [];
            state.household       = results[3];
            state.programs        = results[4].programs    || [];
            state.studentPrograms = results[4].students    || [];
            state.beltHistory     = results[5].history     || [];
            state.billing         = results[6];
            state.autoEnrollPrefs = results[7] ? (results[7].preferences || []) : [];
            state.loading         = false;
            render(root, state, isParent, members, students, isStudentOnly);
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }

})();
