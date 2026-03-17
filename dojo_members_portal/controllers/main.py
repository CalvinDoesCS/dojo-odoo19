from odoo import fields, http, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.exceptions import AccessError, MissingError, ValidationError, UserError
import json
from datetime import datetime, timedelta


class DojoMemberPortal(CustomerPortal):
    """Portal controller for Dojo member-facing pages under /my."""

    # ── Portal home: inject dojo doc counts ──────────────────────────────
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        env = request.env

        if 'dojo_schedule_count' in counters:
            # Use sudo() – open sessions are public info, and portal users
            # without the dojo-specific group would get an AccessError otherwise.
            values['dojo_schedule_count'] = env['dojo.class.session'].sudo().search_count([
                ('state', '=', 'open'),
                ('start_datetime', '>=', fields.Datetime.now()),
            ])

        if 'dojo_attendance_count' in counters:
            household_member_ids = self._get_household_member_ids()
            try:
                values['dojo_attendance_count'] = env['dojo.attendance.log'].search_count([
                    ('member_id', 'in', household_member_ids),
                ]) if household_member_ids else 0
            except Exception:
                values['dojo_attendance_count'] = 0

        if 'dojo_invoice_count' in counters:
            invoice_ids = self._get_household_invoice_ids()
            values['dojo_invoice_count'] = len(invoice_ids)

        return values

    # ── Helpers ───────────────────────────────────────────────────────────
    def _get_current_member(self):
        """Return the dojo.member record for the current portal user, or None."""
        partner = request.env.user.partner_id
        member = request.env['dojo.member'].sudo().search(
            [('partner_id', '=', partner.id)], limit=1
        )
        return member or None

    def _get_household_member_ids(self):
        """Return member IDs scoped to the current user's access level.

        Students (role == 'student') are strictly limited to their own record.
        Parents and 'both' roles see the entire household.
        """
        member = self._get_current_member()
        if not member:
            return []
        # Students may only ever see their own data — never siblings or parents
        if member.role == 'student':
            return [member.id]
        if member.household_id:
            return member.household_id.member_ids.ids
        return [member.id]

    def _get_student_members(self):
        """Return dojo.member records that are students in the current household.

        Only meaningful for parents; returns an empty RecordSet for students.
        """
        member = self._get_current_member()
        if not member or member.role == 'student':
            return request.env['dojo.member'].sudo().browse([])
        all_members = request.env['dojo.member'].sudo().browse(
            self._get_household_member_ids()
        )
        return all_members.filtered(lambda m: m.role in ('student', 'both'))

    def _resolve_view_member_ids(self, member_id=None):
        """Return the list of member IDs to use for a JSON data request.

        If ``member_id`` is provided and the caller is a parent, validate that
        the requested member belongs to their household and return [member_id].
        Students always get only their own ID regardless of params.
        """
        member = self._get_current_member()
        if not member:
            return []
        if member.role == 'student':
            return [member.id]
        if member_id:
            try:
                mid = int(member_id)
            except (TypeError, ValueError):
                mid = None
            if mid:
                hm_ids = self._get_household_member_ids()
                if mid in hm_ids:
                    return [mid]
        return self._get_household_member_ids()

    def _get_household_invoice_ids(self):
        """Return all account.move IDs for invoices tied to household subscriptions."""
        member_ids = self._get_household_member_ids()
        if not member_ids:
            return []
        subscriptions = request.env['dojo.member.subscription'].sudo().search([
            ('member_id', 'in', member_ids),
        ])
        # Collect individual (M2o) invoices AND consolidated household (M2m) invoices.
        # The | operator deduplicates so a consolidated invoice shared across subs
        # appears only once in the result.
        all_invoices = subscriptions.mapped('invoice_ids') | subscriptions.mapped('household_invoice_ids')
        return all_invoices.ids

    def _get_belt_context(self, member):
        """Return current_rank, next_rank, and rank_pct (0-100) for the dashboard."""
        if not member:
            return {'current_rank': None, 'next_rank': None, 'rank_pct': 0}
        current_rank = getattr(member, 'current_rank_id', None) or None
        if not current_rank:
            return {'current_rank': None, 'next_rank': None, 'rank_pct': 0}
        all_ranks = request.env['dojo.belt.rank'].sudo().search(
            [('company_id', '=', member.company_id.id)], order='sequence asc'
        )
        rank_ids = all_ranks.ids
        try:
            idx = rank_ids.index(current_rank.id)
        except ValueError:
            idx = 0
        total = len(rank_ids)
        next_rank = all_ranks[idx + 1] if idx + 1 < total else None
        rank_pct = int(((idx + 1) / total) * 100) if total else 0
        return {'current_rank': current_rank, 'next_rank': next_rank, 'rank_pct': rank_pct}

    # ── /my/dojo  (unified portal page) ─────────────────────────────────
    @http.route('/my/dojo', type='http', auth='user', website=True)
    def portal_dojo_home(self, tab='programs', saved=None, upgraded=None, invoice_warning=None, **kwargs):
        member = self._get_current_member()
        if not member:
            return request.render('dojo_members_portal.portal_no_member', {})
        env = request.env
        is_parent = member.role in ('parent', 'both')
        is_student_only = member.role == 'student'
        household_member_ids = self._get_household_member_ids()

        attendance_count = env['dojo.attendance.log'].sudo().search_count([
            ('member_id', 'in', household_member_ids),
        ])
        upcoming_count = env['dojo.class.enrollment'].sudo().search_count([
            ('member_id', 'in', household_member_ids),
            ('status', '=', 'registered'),
            ('session_id.start_datetime', '>=', fields.Datetime.now()),
            ('session_id.state', 'in', ['open', 'draft']),
        ])
        household_members = env['dojo.member'].sudo().browse(household_member_ids)
        members_json = json.dumps([{'id': m.id, 'name': m.name, 'role': m.role or ''} for m in household_members])

        # Student members for the household switcher (parents only)
        student_members = self._get_student_members() if is_parent else env['dojo.member'].sudo().browse([])
        students_json = json.dumps([{'id': m.id, 'name': m.name} for m in student_members])

        belt = self._get_belt_context(member)

        # Credit balance for the portal hero chip
        active_sub = member.sudo().active_subscription_id
        is_credit_plan = bool(getattr(getattr(active_sub, 'plan_id', None), 'credits_per_period', 0))
        credit_balance = getattr(active_sub, 'credit_balance', 0) if active_sub else 0

        return request.render('dojo_members_portal.portal_dojo_home', {
            'member': member,
            'is_parent': is_parent,
            'is_student_only': is_student_only,
            'initial_tab': tab,
            'page_name': 'dojo_home',
            'attendance_count': attendance_count,
            'upcoming_count': upcoming_count,
            'household_saved': saved == '1',
            'plan_upgraded': upgraded == '1',
            'invoice_warning': invoice_warning == '1',
            'members_json': members_json,
            'students_json': students_json,
            'is_credit_plan': is_credit_plan,
            'credit_balance': credit_balance,
            # Belt context: hide rank card for parents who have no rank of their own
            'show_belt_card': is_student_only or bool(belt.get('current_rank')),
            **belt,
        })

    # ── /my/dojo/schedule – redirect to unified page ───────────────────
    @http.route('/my/dojo/schedule', type='http', auth='user')
    def portal_my_schedule(self, **kwargs):
        return request.redirect('/my/dojo?tab=classes')

    # ── /my/dojo/enrollments – redirect to unified page ─────────────────
    @http.route('/my/dojo/enrollments', type='http', auth='user')
    def portal_my_enrollments(self, **kwargs):
        return request.redirect('/my/dojo?tab=classes')

    # ── /my/dojo/attendance – redirect to unified page ──────────────────
    @http.route('/my/dojo/attendance', type='http', auth='user')
    def portal_my_attendance(self, **kwargs):
        return request.redirect('/my/dojo?tab=attendance')

    # ── JSON data endpoints for the OWL activities component ──────────────
    @http.route('/my/dojo/json/belt', type='http', auth='user')
    def portal_json_belt(self, member_id=None, **kwargs):
        """Return belt rank context for a member. Parents can request any household member."""
        current = self._get_current_member()
        if not current:
            return request.make_response(
                json.dumps({'error': 'not found'}),
                headers=[('Content-Type', 'application/json')],
            )
        # Resolve target member
        target = current
        if member_id and current.role != 'student':
            try:
                mid = int(member_id)
                hm_ids = self._get_household_member_ids()
                if mid in hm_ids:
                    target = request.env['dojo.member'].sudo().browse(mid)
            except (TypeError, ValueError):
                pass
        belt = self._get_belt_context(target)
        return request.make_response(
            json.dumps({
                'member_id': target.id,
                'member_name': target.name or '',
                'current_rank': (
                    {
                        'id': belt['current_rank'].id,
                        'name': belt['current_rank'].name,
                        'color': getattr(belt['current_rank'], 'color', None) or '#cccccc',
                    } if belt.get('current_rank') else None
                ),
                'next_rank': (
                    {'id': belt['next_rank'].id, 'name': belt['next_rank'].name}
                    if belt.get('next_rank') else None
                ),
                'rank_pct': belt.get('rank_pct', 0),
            }),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/json/schedule', type='http', auth='user')
    def portal_json_schedule(self, member_id=None, **kwargs):
        member = self._get_current_member()
        is_parent = member.role in ('parent', 'both') if member else True
        household_member_ids = self._resolve_view_member_ids(member_id)
        household_members = request.env['dojo.member'].sudo().browse(household_member_ids)

        # Scope sessions to programs covered by each member's active subscription.
        # Build: program_id -> [member_ids subscribed to it]
        program_member_map = {}  # {program_id: [member_id, ...]}
        for m in household_members.filtered(lambda x: x.role in ('student', 'both')):
            sub = m.active_subscription_id
            if not sub:
                continue
            plan = sub.plan_id
            if getattr(plan, 'plan_type', '') == 'program' and plan.program_id:
                prog_id = plan.program_id.id
                program_member_map.setdefault(prog_id, []).append(m.id)

        if not program_member_map:
            return request.make_response(
                json.dumps({'sessions': [], 'can_enroll': is_parent}),
                headers=[('Content-Type', 'application/json')],
            )

        domain = [
            ('state', '=', 'open'),
            ('start_datetime', '>=', fields.Datetime.now()),
            ('template_id.program_id', 'in', list(program_member_map.keys())),
        ]
        sessions = request.env['dojo.class.session'].sudo().search(
            domain, order='start_datetime asc', limit=100
        )
        data = []
        for s in sessions:
            prog = s.template_id.program_id if s.template_id else False
            prog_id = prog.id if prog else None
            # Eligible = members subscribed to this session's program
            eligible_member_ids = program_member_map.get(prog_id, [])
            # Credit cost per class from the program model (default 1)
            credits_per_class = getattr(prog, 'credits_per_class', 1) if prog else 1
            data.append({
                'id': s.id,
                'name': s.template_id.name or '',
                'template_id': s.template_id.id,
                'program_name': prog.name if prog else '',
                'start_datetime': fields.Datetime.to_string(s.start_datetime) if s.start_datetime else None,
                'end_datetime': fields.Datetime.to_string(s.end_datetime) if s.end_datetime else None,
                'instructor': s.instructor_profile_id.name if s.instructor_profile_id else None,
                'level': s.template_id.level or 'all',
                'duration_minutes': s.template_id.duration_minutes or 0,
                'seats_taken': s.seats_taken or 0,
                'capacity': s.capacity or 0,
                'state': s.state,
                'description': s.template_id.description or '',
                'eligible_member_ids': eligible_member_ids,
                'credits_per_class': credits_per_class,
            })
        return request.make_response(
            json.dumps({'sessions': data, 'can_enroll': is_parent}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/json/enrollments', type='http', auth='user')
    def portal_json_enrollments(self, member_id=None, **kwargs):
        member_ids = self._resolve_view_member_ids(member_id)
        enrollments = request.env['dojo.class.enrollment'].sudo().search(
            [('member_id', 'in', member_ids)],
            limit=200,
        )
        # Sort by session start_datetime descending in Python to avoid cross-model order
        enrollments = sorted(
            enrollments,
            key=lambda e: e.session_id.start_datetime or fields.Datetime.now(),
            reverse=True,
        )[:100]
        data = []
        for e in enrollments:
            tmpl = e.session_id.template_id
            data.append({
                'id': e.id,
                'session_id': e.session_id.id,
                'member_id': e.member_id.id,
                'member_name': e.member_id.name or '',
                'session_name': tmpl.name or '',
                'template_id': tmpl.id,
                'program_name': tmpl.program_id.name if tmpl.program_id else '',
                'level': tmpl.level or 'all',
                'start_datetime': fields.Datetime.to_string(e.session_id.start_datetime)
                    if e.session_id.start_datetime else None,
                'end_datetime': fields.Datetime.to_string(e.session_id.end_datetime)
                    if e.session_id.end_datetime else None,
                'instructor': e.session_id.instructor_profile_id.name
                    if e.session_id.instructor_profile_id else None,
                'status': e.status or '',
                'attendance_state': e.attendance_state or '',
            })
        return request.make_response(
            json.dumps({'enrollments': data}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── Auto-Enroll Preferences ────────────────────────────────────────────

    @http.route('/my/dojo/json/auto-enroll', type='http', auth='user')
    def portal_json_auto_enroll(self, member_id=None, **kwargs):
        """Return auto-enroll status for ALL active recurring class templates.

        Each entry represents one (member, template) pair.  If the member has an
        explicit preference record it is returned; otherwise a virtual default entry
        (active=True, permanent, no specific days) is synthesised so the UI always
        shows every available recurring class.
        """
        member_ids = self._resolve_view_member_ids(member_id)
        household_members = request.env['dojo.member'].sudo().browse(member_ids)
        # Parents are guardians, not class participants — only query students.
        household_members = household_members.filtered(
            lambda m: m.role in ('student', 'both')
        )
        if not household_members:
            return request.make_response(
                json.dumps({'preferences': []}),
                headers=[('Content-Type', 'application/json')],
            )

        # Only recurring templates the students are actually enrolled in
        enrolled_tmpl_ids = set()
        for _m in household_members:
            enrolled_tmpl_ids.update(_m.enrolled_template_ids.ids)
            _en = request.env['dojo.class.enrollment'].sudo().search([
                ('member_id', '=', _m.id),
                ('status', '!=', 'cancelled'),
            ])
            enrolled_tmpl_ids.update(_en.mapped('session_id.template_id').ids)
        all_templates = request.env['dojo.class.template'].sudo().browse(
            list(enrolled_tmpl_ids)
        ).filtered(lambda t: t.recurrence_active)

        # Existing explicit preferences (include inactive/opted-out via active_test=False)
        prefs = request.env['dojo.course.auto.enroll'].with_context(
            active_test=False,
        ).sudo().search([('member_id', 'in', member_ids)])
        pref_by_key = {(p.member_id.id, p.template_id.id): p for p in prefs}

        # Which templates is each member already on the roster for?
        enrolled_by_member = {m.id: set(m.enrolled_template_ids.ids) for m in household_members}

        def _row(m, tmpl, pref=None):
            enrolled = tmpl.id in enrolled_by_member.get(m.id, set())
            if pref:
                return {
                    'id': pref.id,
                    'member_id': m.id,
                    'member_name': m.name or '',
                    'template_id': tmpl.id,
                    'template_name': tmpl.name or '',
                    'program_name': tmpl.program_id.name if tmpl.program_id else '',
                    'enrolled': enrolled,
                    'active': pref.active,
                    'mode': pref.mode,
                    'date_from': fields.Date.to_string(pref.date_from) if pref.date_from else None,
                    'date_to': fields.Date.to_string(pref.date_to) if pref.date_to else None,
                    'tmpl_rec_mon': tmpl.rec_mon, 'tmpl_rec_tue': tmpl.rec_tue,
                    'tmpl_rec_wed': tmpl.rec_wed, 'tmpl_rec_thu': tmpl.rec_thu,
                    'tmpl_rec_fri': tmpl.rec_fri, 'tmpl_rec_sat': tmpl.rec_sat,
                    'tmpl_rec_sun': tmpl.rec_sun,
                    'pref_mon': pref.pref_mon, 'pref_tue': pref.pref_tue,
                    'pref_wed': pref.pref_wed, 'pref_thu': pref.pref_thu,
                    'pref_fri': pref.pref_fri, 'pref_sat': pref.pref_sat,
                    'pref_sun': pref.pref_sun,
                    'has_pref': True,
                }
            else:
                return {
                    'id': None,
                    'member_id': m.id,
                    'member_name': m.name or '',
                    'template_id': tmpl.id,
                    'template_name': tmpl.name or '',
                    'program_name': tmpl.program_id.name if tmpl.program_id else '',
                    'enrolled': enrolled,
                    'active': enrolled,   # default: on if already rostered, off if not
                    'mode': 'permanent',
                    'date_from': None,
                    'date_to': None,
                    'tmpl_rec_mon': tmpl.rec_mon, 'tmpl_rec_tue': tmpl.rec_tue,
                    'tmpl_rec_wed': tmpl.rec_wed, 'tmpl_rec_thu': tmpl.rec_thu,
                    'tmpl_rec_fri': tmpl.rec_fri, 'tmpl_rec_sat': tmpl.rec_sat,
                    'tmpl_rec_sun': tmpl.rec_sun,
                    'pref_mon': False, 'pref_tue': False,
                    'pref_wed': False, 'pref_thu': False,
                    'pref_fri': False, 'pref_sat': False,
                    'pref_sun': False,
                    'has_pref': False,
                }

        data = []
        for m in household_members:
            for tmpl in all_templates:
                pref = pref_by_key.get((m.id, tmpl.id))
                data.append(_row(m, tmpl, pref))

        return request.make_response(
            json.dumps({'preferences': data}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/auto-enroll', type='http', auth='user', methods=['POST'])
    def portal_post_auto_enroll(self, **post):
        """Create or update a single auto-enroll preference.

        Expected JSON body keys:
            member_id       int   (required)
            template_id     int   (required)
            active          bool
            mode            str   'permanent' | 'multiday'
            date_from       str   ISO date, required for 'multiday'
            date_to         str   ISO date, required for 'multiday'
            pref_mon … pref_sun  bool
        """
        try:
            body = json.loads(request.httprequest.data or '{}')
        except Exception:
            body = {}

        # Validate caller has household rights over the target member
        member = self._get_current_member()
        if not member:
            return request.make_response(
                json.dumps({'success': False, 'error': 'not_authenticated'}),
                headers=[('Content-Type', 'application/json')],
            )
        try:
            target_member_id = int(body.get('member_id') or 0)
            template_id = int(body.get('template_id') or 0)
        except (TypeError, ValueError):
            return request.make_response(
                json.dumps({'success': False, 'error': 'invalid_ids'}),
                headers=[('Content-Type', 'application/json')],
            )
        household_ids = self._get_household_member_ids()
        if target_member_id not in household_ids:
            return request.make_response(
                json.dumps({'success': False, 'error': 'access_denied'}),
                headers=[('Content-Type', 'application/json')],
            )

        Pref = request.env['dojo.course.auto.enroll'].with_context(active_test=False).sudo()
        existing = Pref.search([
            ('member_id', '=', target_member_id),
            ('template_id', '=', template_id),
        ], limit=1)

        vals = {
            'active': bool(body.get('active', True)),
            'mode': body.get('mode', 'permanent'),
            'pref_mon': bool(body.get('pref_mon', False)),
            'pref_tue': bool(body.get('pref_tue', False)),
            'pref_wed': bool(body.get('pref_wed', False)),
            'pref_thu': bool(body.get('pref_thu', False)),
            'pref_fri': bool(body.get('pref_fri', False)),
            'pref_sat': bool(body.get('pref_sat', False)),
            'pref_sun': bool(body.get('pref_sun', False)),
        }
        if vals['mode'] == 'multiday':
            if body.get('date_from'):
                try:
                    vals['date_from'] = fields.Date.from_string(body['date_from'])
                except Exception:
                    pass
            if body.get('date_to'):
                try:
                    vals['date_to'] = fields.Date.from_string(body['date_to'])
                except Exception:
                    pass

        try:
            if existing:
                existing.write(vals)
                pref_id = existing.id
            else:
                vals['member_id'] = target_member_id
                vals['template_id'] = template_id
                pref = Pref.create(vals)
                pref_id = pref.id

            # Sync roster membership: opt-in → add to course_member_ids if not already there
            tmpl = request.env['dojo.class.template'].sudo().browse(template_id)
            enrolled_ids = tmpl.course_member_ids.ids
            if vals['active'] and target_member_id not in enrolled_ids:
                tmpl.write({'course_member_ids': [(4, target_member_id)]})
        except Exception as e:
            return request.make_response(
                json.dumps({'success': False, 'error': str(e)}),
                headers=[('Content-Type', 'application/json')],
            )

        return request.make_response(
            json.dumps({'success': True, 'pref_id': pref_id}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/json/attendance', type='http', auth='user')
    def portal_json_attendance(self, member_id=None, **kwargs):
        member_ids = self._resolve_view_member_ids(member_id)
        logs = request.env['dojo.attendance.log'].sudo().search(
            [('member_id', 'in', member_ids)],
            order='checkin_datetime desc',
            limit=100,
        )
        data = []
        for log in logs:
            # Build a clean session label: "Class Name — Mon, Mar 10, 2026 3:00 PM"
            sess = log.session_id
            if sess:
                class_name = (sess.template_id.name if sess.template_id else None) or sess.name or 'Session'
                if sess.start_datetime:
                    dt_utc = fields.Datetime.from_string(sess.start_datetime) if isinstance(sess.start_datetime, str) else sess.start_datetime
                    display_dt = dt_utc.strftime('%b %-d, %Y %-I:%M %p')
                    session_label = '%s — %s' % (class_name, display_dt)
                else:
                    session_label = class_name
            else:
                session_label = ''
            data.append({
                'id': log.id,
                'member_name': log.member_id.name or '',
                'session_name': session_label,
                'checkin_datetime': fields.Datetime.to_string(log.checkin_datetime)
                    if log.checkin_datetime else None,
                'status': log.status or 'present',
                'note': log.note or '',
            })
        return request.make_response(
            json.dumps({'logs': data}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/json/household', type='http', auth='user')
    def portal_json_household(self, **kwargs):
        member = self._get_current_member()
        if not member:
            return request.make_response(
                json.dumps({'error': 'No member found'}),
                headers=[('Content-Type', 'application/json')],
            )
        is_parent = member.role in ('parent', 'both')
        household = member.sudo().household_id
        hm_records = request.env['dojo.member'].sudo().browse(
            self._get_household_member_ids()
        )
        members_data = []
        for m in hm_records:
            contacts = []
            for ec in m.emergency_contact_ids:
                contacts.append({
                    'id': ec.id,
                    'name': ec.name or '',
                    'relationship': ec.relationship or '',
                    'phone': ec.phone or '',
                    'email': ec.email or '',
                    'is_primary': bool(ec.is_primary),
                })
            sub = m.active_subscription_id
            plan_data = None
            if sub and sub.plan_id:
                plan = sub.plan_id
                credits_per_period = getattr(plan, 'credits_per_period', 0)
                plan_data = {
                    'name': plan.name or '',
                    'state': sub.state or '',
                    'billing_period': plan.billing_period or '',
                    'price': plan.price,
                    'currency': plan.currency_id.name if plan.currency_id else 'USD',
                    'credits_per_period': credits_per_period,
                }
            members_data.append({
                'id': m.id,
                'name': m.name or '',
                'role': m.role or '',
                'emergency_contacts': contacts,
                'courses': [
                    {'id': t.id, 'name': t.name, 'level': t.level or 'all'}
                    for t in m.enrolled_template_ids
                ],
                'credit_balance': getattr(sub, 'credit_balance', 0) if sub else 0,
                'credit_pending': getattr(sub, 'credit_pending', 0) if sub else 0,
                'credit_confirmed': getattr(sub, 'credit_confirmed', 0) if sub else 0,
                'plan': plan_data,
            })
        return request.make_response(
            json.dumps({
                'can_edit': is_parent,
                'household_name': household.name if household else '',
                'members': members_data,
            }),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/enroll', type='http', auth='user', methods=['POST'])
    def portal_enroll(self, session_id=None, member_id=None, **kwargs):
        def _err(msg):
            return request.make_response(
                json.dumps({'ok': False, 'error': msg}),
                headers=[('Content-Type', 'application/json')],
            )
        member = self._get_current_member()
        if not member:
            return _err('Not authenticated.')
        try:
            session_id = int(session_id)
            member_id  = int(member_id)
        except (TypeError, ValueError):
            return _err('Invalid parameters.')
        household_member_ids = self._get_household_member_ids()
        if member_id not in household_member_ids:
            return _err('Not authorised to enroll this member.')
        env = request.env
        # Only members with a student role may be enrolled in classes
        enroll_target = env['dojo.member'].sudo().browse(member_id)
        if not enroll_target.exists() or enroll_target.role not in ('student', 'both'):
            return _err('Only students can be enrolled in classes.')
        session = env['dojo.class.session'].sudo().browse(session_id)
        if not session.exists() or session.state not in ('open', 'draft'):
            return _err('Session is not available for enrollment.')
        # Enforce course roster: auto-add if the member has a valid subscription
        # for this session's program/template, otherwise block with a friendly error.
        if session.template_id.course_member_ids:
            if enroll_target.id not in session.template_id.course_member_ids.ids:
                sub = env['dojo.member.subscription']._find_subscription_for_session(
                    enroll_target, session
                )
                if sub:
                    # Auto-add to course roster so future auto-enroll picks them up too
                    session.template_id.sudo().write(
                        {'course_member_ids': [(4, enroll_target.id)]}
                    )
                else:
                    return _err(
                        '%s is not enrolled in the course "%s". '
                        'Ask an instructor to add them to the course roster first.' %
                        (enroll_target.name, session.template_id.name)
                    )
        existing = env['dojo.class.enrollment'].sudo().search([
            ('session_id', '=', session_id),
            ('member_id', '=', member_id),
            ('status', '!=', 'cancelled'),
        ], limit=1)
        if existing:
            return _err('Already enrolled in this session.')
        try:
            # If a cancelled enrollment record exists, reactivate it instead of
            # creating a new one (DB has a unique constraint on session+member).
            cancelled = env['dojo.class.enrollment'].sudo().search([
                ('session_id', '=', session_id),
                ('member_id', '=', member_id),
                ('status', '=', 'cancelled'),
            ], limit=1)
            if cancelled:
                cancelled.write({'status': 'registered'})
            else:
                env['dojo.class.enrollment'].sudo().create({
                    'session_id': session_id,
                    'member_id': member_id,
                    'status': 'registered',
                })
        except (ValidationError, UserError) as ve:
            return _err(str(ve.args[0]) if ve.args else str(ve))
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/household/save', type='http', auth='user', methods=['POST'])
    def portal_household_save(self, **kwargs):
        def _err(msg):
            return request.make_response(
                json.dumps({'ok': False, 'error': msg}),
                headers=[('Content-Type', 'application/json')],
            )
        member = self._get_current_member()
        if not member or member.role not in ('parent', 'both'):
            return _err('Not authorised.')
        try:
            payload = json.loads(request.httprequest.data)
        except Exception:
            return _err('Invalid request body.')
        household = member.sudo().household_id
        if household and payload.get('household_name'):
            household.sudo().write({'name': payload['household_name'].strip()})
        nc = payload.get('new_contact')
        if nc and nc.get('name') and nc.get('phone'):
            household_member_ids = self._get_household_member_ids()
            nc_mid = nc.get('member_id')
            if nc_mid and int(nc_mid) in household_member_ids:
                request.env['dojo.emergency.contact'].sudo().create({
                    'member_id': int(nc_mid),
                    'name': nc['name'].strip(),
                    'relationship': (nc.get('relationship') or '').strip() or 'Other',
                    'phone': nc['phone'].strip(),
                    'email': (nc.get('email') or '').strip() or False,
                    'is_primary': False,
                })
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── Private helpers ────────────────────────────────────────────────────
    def _build_programs_for_member(self, target):
        """Build programs data list for a given dojo.member record.

        Uses ``dojo.program.enrollment`` as the authoritative source for which
        programs the member belongs to (active and historical).  Class-template
        associations are still populated from the course roster / session history
        so the card can show which classes are included.
        """
        env = request.env

        # ── Source: program enrollment records ──────────────────────────────
        enrollments = env['dojo.program.enrollment'].sudo().search([
            ('member_id', '=', target.id),
        ], order='is_active desc, enrolled_date desc')

        if not enrollments:
            return []

        # Deduplicate programs: for each unique program keep is_active=True if any
        # enrollment for that program is currently active.
        program_active_map = {}  # program_id → {'program': record, 'is_active': bool}
        for enr in enrollments:
            pid = enr.program_id.id
            if pid not in program_active_map:
                program_active_map[pid] = {
                    'program': enr.program_id,
                    'is_active': enr.is_active,
                }
            elif enr.is_active:
                program_active_map[pid]['is_active'] = True

        # ── Class templates shown in each program card ───────────────────────
        # Still inferred from roster + session history (independent of enrollments)
        roster_templates = target.enrolled_template_ids
        enrollment_recs = env['dojo.class.enrollment'].sudo().search([
            ('member_id', '=', target.id),
            ('status', '!=', 'cancelled'),
        ])
        enrollment_templates = enrollment_recs.mapped('session_id.template_id')
        all_templates = roster_templates | enrollment_templates

        templates_by_program = {}
        for t in all_templates:
            if t.program_id:
                pid = t.program_id.id
                if pid not in templates_by_program:
                    templates_by_program[pid] = []
                if t.id not in [x.id for x in templates_by_program[pid]]:
                    templates_by_program[pid].append(t)

        # ── Belt path metadata ────────────────────────────────────────────────
        ODOO_COLORS = [
            '#714B67', '#017E84', '#0D6EFD', '#17A2B8', '#28A745',
            '#FFC107', '#DC3545', '#6F42C1', '#E83E8C', '#FD7E14',
            '#20C997', '#6C757D',
        ]
        current_rank = getattr(target, 'current_rank_id', None) or None
        test_pending = bool(getattr(target, 'test_invite_pending', False))
        all_rank_history = getattr(target, 'rank_history_ids', env['dojo.member.rank'].sudo().browse([]))
        all_company_ranks = env['dojo.belt.rank'].sudo().search(
            [('company_id', '=', target.company_id.id), ('active', '=', True)],
            order='sequence asc',
        )

        programs_data = []
        for pdata in program_active_map.values():
            prog = pdata['program']
            is_active = pdata['is_active']
            prog_belts = prog.belt_rank_ids.sorted(lambda r: r.sequence)
            belt_path = prog_belts if prog_belts else all_company_ranks
            path_ids = belt_path.ids
            current_in_path = next_in_path = None
            rank_pct = 0
            if current_rank and path_ids:
                if current_rank.id in path_ids:
                    idx = path_ids.index(current_rank.id)
                else:
                    history_rank_ids = set(
                        target.rank_history_ids.mapped('rank_id').ids
                    ) if hasattr(target, 'rank_history_ids') else set()
                    achieved_in_path = [
                        i for i, rid in enumerate(path_ids)
                        if rid in history_rank_ids
                    ]
                    idx = max(achieved_in_path) if achieved_in_path else -1
                if idx >= 0:
                    total = len(path_ids)
                    current_in_path = belt_path[idx]
                    next_in_path = belt_path[idx + 1] if idx + 1 < total else None
                    rank_pct = int(((idx + 1) / total) * 100) if total else 0
            prog_color = ODOO_COLORS[(prog.color or 0) % len(ODOO_COLORS)] if prog.color else '#6C757D'
            programs_data.append({
                'id': prog.id,
                'name': prog.name or '',
                'code': prog.code or '',
                'color': prog_color,
                'is_active': is_active,
                'templates': [
                    {'id': t.id, 'name': t.name or '', 'level': t.level or 'all'}
                    for t in templates_by_program.get(prog.id, [])
                ],
                'belt_path': [
                    {'id': r.id, 'name': r.name or '', 'color': r.color or '#cccccc', 'sequence': r.sequence}
                    for r in belt_path
                ],
                'current_rank_id': current_in_path.id if current_in_path else None,
                'current_rank_name': current_in_path.name if current_in_path else None,
                'current_rank_color': (current_in_path.color or '#cccccc') if current_in_path else None,
                'next_rank_id': next_in_path.id if next_in_path else None,
                'next_rank_name': next_in_path.name if next_in_path else None,
                'rank_pct': rank_pct,
                'rank_position': (path_ids.index(current_in_path.id) + 1) if current_in_path else 0,
                'rank_total': len(path_ids),
                'test_invite_pending': test_pending,
                'rank_history': [
                    {
                        'rank_name': h.rank_id.name if h.rank_id else '',
                        'rank_color': h.rank_id.color if h.rank_id else '#cccccc',
                        'date_awarded': fields.Date.to_string(h.date_awarded) if h.date_awarded else None,
                        'awarded_by': h.awarded_by.name if h.awarded_by else None,
                    }
                    for h in all_rank_history.sorted(lambda r: r.date_awarded or fields.Date.today(), reverse=True)
                    # If the rank record has an explicit program, match by program;
                    # otherwise fall back to belt-path membership for legacy records.
                    if h.rank_id and (
                        (h.program_id and h.program_id.id == prog.id)
                        or (not h.program_id and h.rank_id.id in path_ids)
                    )
                ],
            })
        return programs_data

    def _build_belt_history_for_member(self, target):
        """Build belt rank award history list for a given dojo.member record."""
        history = getattr(target, 'rank_history_ids', request.env['dojo.member.rank'].sudo().browse([]))
        data = []
        for h in history.sorted(lambda r: r.date_awarded or fields.Date.today(), reverse=True):
            data.append({
                'rank_name': h.rank_id.name if h.rank_id else '',
                'rank_color': h.rank_id.color if h.rank_id else '#cccccc',
                'date_awarded': fields.Date.to_string(h.date_awarded) if h.date_awarded else None,
                'awarded_by': h.awarded_by.name if h.awarded_by else None,
            })
        return data

    # ── /my/dojo/json/programs ──────────────────────────────────────────────
    @http.route('/my/dojo/json/programs', type='http', auth='user')
    def portal_json_programs(self, member_id=None, **kwargs):
        """Return programs the member is enrolled in with per-program belt path.

        For parent users without a member_id, returns all household students'
        programs grouped: {programs: [], students: [{id, name, programs, belt_history}]}
        """
        current = self._get_current_member()
        if not current:
            return request.make_response(
                json.dumps({'programs': [], 'students': []}),
                headers=[('Content-Type', 'application/json')],
            )
        def _json(d):
            return request.make_response(
                json.dumps(d), headers=[('Content-Type', 'application/json')]
            )
        # Parent without a specific student selected → return all students' data
        if not member_id and current.role != 'student':
            hm_ids = self._get_household_member_ids()
            students_data = []
            for mid in hm_ids:
                m = request.env['dojo.member'].sudo().browse(mid)
                if not m.exists() or m.role not in ('student', 'both'):
                    continue
                students_data.append({
                    'id': m.id,
                    'name': m.name or '',
                    'programs': self._build_programs_for_member(m),
                    'belt_history': self._build_belt_history_for_member(m),
                })
            return _json({'programs': [], 'students': students_data})
        # Specific member or student self-view
        target = current
        if member_id and current.role != 'student':
            try:
                mid = int(member_id)
                hm_ids = self._get_household_member_ids()
                if mid in hm_ids:
                    target = request.env['dojo.member'].sudo().browse(mid)
            except (TypeError, ValueError):
                pass
        return _json({'programs': self._build_programs_for_member(target), 'students': []})

    # ── /my/dojo/json/belt-history ──────────────────────────────────────────
    @http.route('/my/dojo/json/belt-history', type='http', auth='user')
    def portal_json_belt_history(self, member_id=None, **kwargs):
        """Return rank award history for a member."""
        current = self._get_current_member()
        if not current:
            return request.make_response(
                json.dumps({'history': []}),
                headers=[('Content-Type', 'application/json')],
            )
        target = current
        if member_id and current.role != 'student':
            try:
                mid = int(member_id)
                hm_ids = self._get_household_member_ids()
                if mid in hm_ids:
                    target = request.env['dojo.member'].sudo().browse(mid)
            except (TypeError, ValueError):
                pass
        return request.make_response(
            json.dumps({'history': self._build_belt_history_for_member(target)}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── /my/dojo/unenroll ──────────────────────────────────────────────────
    @http.route('/my/dojo/unenroll', type='http', auth='user', methods=['POST'])
    def portal_unenroll(self, enrollment_id=None, **kwargs):
        def _err(msg):
            return request.make_response(
                json.dumps({'ok': False, 'error': msg}),
                headers=[('Content-Type', 'application/json')],
            )
        member = self._get_current_member()
        if not member:
            return _err('Not authenticated.')
        try:
            enrollment_id = int(enrollment_id)
        except (TypeError, ValueError):
            return _err('Invalid parameters.')
        household_member_ids = self._get_household_member_ids()
        enrollment = request.env['dojo.class.enrollment'].sudo().browse(enrollment_id)
        if not enrollment.exists() or enrollment.member_id.id not in household_member_ids:
            return _err('Not authorised.')
        now = fields.Datetime.now()
        if enrollment.session_id.start_datetime and enrollment.session_id.start_datetime <= now:
            return _err('Cannot cancel a session that has already started.')
        if enrollment.status == 'cancelled':
            return _err('Already cancelled.')
        enrollment.sudo().write({'status': 'cancelled'})
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── /my/dojo/belt-test-request ─────────────────────────────────────────
    @http.route('/my/dojo/belt-test-request', type='http', auth='user', methods=['POST'])
    def portal_belt_test_request(self, member_id=None, **kwargs):
        def _err(msg):
            return request.make_response(
                json.dumps({'ok': False, 'error': msg}),
                headers=[('Content-Type', 'application/json')],
            )
        member = self._get_current_member()
        if not member:
            return _err('Not authenticated.')
        target = member
        if member_id and member.role != 'student':
            try:
                mid = int(member_id)
                hm_ids = self._get_household_member_ids()
                if mid in hm_ids:
                    target = request.env['dojo.member'].sudo().browse(mid)
                    if not target.exists():
                        return _err('Member not found.')
            except (TypeError, ValueError):
                return _err('Invalid member ID.')
        if target.role not in ('student', 'both'):
            return _err('Belt tests are for students only.')
        if getattr(target, 'test_invite_pending', False):
            return _err('A belt test request is already pending.')
        target.sudo().write({'test_invite_pending': True})

        # ── Notify instructor(s) via their todo list ──────────────────────
        try:
            next_rank = target.sudo()._get_next_belt_rank()
            rank_label = next_rank.name if next_rank else 'next rank'
            users = target.sudo()._get_instructor_users_for_member()
            request.env['dojo.member'].sudo()._create_instructor_todo(
                users,
                '🥋 Belt test requested: %s → %s' % (target.name, rank_label),
                description=(
                    '%s has requested a belt test via the member portal. '
                    'Please review their eligibility and schedule the test.' % target.name
                ),
            )
        except Exception:
            pass  # Never block the portal response over a failed notification

        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── /my/dojo/message ───────────────────────────────────────────────────
    @http.route('/my/dojo/message', type='http', auth='user', methods=['POST'])
    def portal_message_instructor(self, **kwargs):
        def _err(msg):
            return request.make_response(
                json.dumps({'ok': False, 'error': msg}),
                headers=[('Content-Type', 'application/json')],
            )
        member = self._get_current_member()
        if not member:
            return _err('Not authenticated.')
        try:
            payload = json.loads(request.httprequest.data)
        except Exception:
            return _err('Invalid request body.')
        message_body = (payload.get('message') or '').strip()
        if not message_body:
            return _err('Message cannot be empty.')
        target = member
        mid_param = payload.get('member_id')
        if mid_param and member.role != 'student':
            try:
                mid = int(mid_param)
                hm_ids = self._get_household_member_ids()
                if mid in hm_ids:
                    t = request.env['dojo.member'].sudo().browse(mid)
                    if t.exists():
                        target = t
            except (TypeError, ValueError):
                pass
        author = member.sudo().partner_id
        target.sudo().message_post(
            body=message_body,
            author_id=author.id,
            message_type='comment',
            subtype_xmlid='mail.mt_comment',
        )
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    # ── /my/dojo/json/billing  (parents only) ──────────────────────────────
    @http.route('/my/dojo/json/billing', type='http', auth='user')
    def portal_json_billing(self, **kwargs):
        member = self._get_current_member()
        if not member or member.role not in ('parent', 'both'):
            return request.make_response(
                json.dumps({'error': 'Not authorised'}),
                headers=[('Content-Type', 'application/json')],
            )
        member_ids = self._get_household_member_ids()
        env = request.env

        # Active subscription for any household member
        sub = env['dojo.member.subscription'].sudo().search([
            ('member_id', 'in', member_ids),
            ('state', '=', 'active'),
        ], limit=1)
        # Fall back to any non-cancelled subscription
        if not sub:
            sub = env['dojo.member.subscription'].sudo().search([
                ('member_id', 'in', member_ids),
                ('state', 'not in', ('cancelled',)),
            ], order='start_date desc', limit=1)

        sub_data = None
        if sub:
            plan = sub.plan_id
            sub_data = {
                'id': sub.id,
                'plan_id': plan.id,
                'plan_name': plan.name or '',
                'price': plan.price,
                'currency': plan.currency_id.name if plan.currency_id else 'USD',
                'period': plan.billing_period or 'monthly',
                'state': sub.state,
                'start_date': fields.Date.to_string(sub.start_date) if sub.start_date else None,
                'next_billing_date': fields.Date.to_string(sub.next_billing_date) if sub.next_billing_date else None,
                'billing_failure_count': sub.billing_failure_count or 0,
                'grace_period_end': fields.Date.to_string(sub.grace_period_end) if sub.grace_period_end else None,
                'credits_per_period': getattr(plan, 'credits_per_period', 0),
                'credit_balance': getattr(sub, 'credit_balance', 0),
                'credit_pending': getattr(sub, 'credit_pending', 0),
                'credit_confirmed': getattr(sub, 'credit_confirmed', 0),
            }

        # Available plans (for plan-switch overlay)
        plans = env['dojo.subscription.plan'].sudo().search([('active', '=', True)])
        plans_data = [{
            'id': p.id,
            'name': p.name,
            'price': p.price,
            'period': p.billing_period,
            'currency': p.currency_id.name if p.currency_id else 'USD',
            'description': p.description or '',
        } for p in plans]

        # Last 12 invoices for this household's subscriptions
        invoices_data = []
        if sub:
            sorted_invoices = (sub.invoice_ids | sub.household_invoice_ids).sorted(
                key=lambda i: i.invoice_date or fields.Date.today(), reverse=True
            )[:12]
            for inv in sorted_invoices:
                invoices_data.append({
                    'id': inv.id,
                    'date': fields.Date.to_string(inv.invoice_date) if inv.invoice_date else None,
                    'amount': inv.amount_total,
                    'currency': inv.currency_id.name if inv.currency_id else 'USD',
                    'payment_state': inv.payment_state,
                })

        # Saved payment method (card-on-file) for the household
        payment_method_data = None
        household = member.household_id
        if household and household.primary_guardian_id:
            guardian = household.primary_guardian_id
            provider = env['payment.provider'].sudo().search(
                [('code', '=', 'stripe'), ('state', 'in', ('enabled', 'test'))], limit=1
            )
            if provider:
                token = env['payment.token'].sudo().search([
                    ('provider_id', '=', provider.id),
                    ('partner_id', '=', guardian.partner_id.id),
                    ('active', '=', True),
                ], limit=1)
                if token:
                    payment_method_data = {'name': token.payment_details or token.display_name or 'Card on file'}

        return request.make_response(
            json.dumps({
                'subscription': sub_data,
                'plans': plans_data,
                'invoices': invoices_data,
                'payment_method': payment_method_data,
            }),
            headers=[('Content-Type', 'application/json')],
        )

    # ── Billing action endpoints (parents only) ───────────────────────────
    def _get_household_active_sub(self):
        """Return the active subscription for the current household, or None."""
        member = self._get_current_member()
        if not member or member.role not in ('parent', 'both'):
            return None
        member_ids = self._get_household_member_ids()
        sub = request.env['dojo.member.subscription'].sudo().search([
            ('member_id', 'in', member_ids),
            ('state', 'in', ('active', 'paused')),
        ], order='start_date desc', limit=1)
        return sub or None

    @http.route('/my/dojo/billing/change-plan', type='http', auth='user', methods=['POST'])
    def portal_billing_change_plan(self, plan_id=None, **kwargs):
        def _err(msg):
            return request.make_response(
                json.dumps({'ok': False, 'error': msg}),
                headers=[('Content-Type', 'application/json')],
            )
        sub = self._get_household_active_sub()
        if not sub:
            return _err('No active subscription found.')
        try:
            plan_id = int(plan_id)
        except (TypeError, ValueError):
            return _err('Invalid plan.')
        plan = request.env['dojo.subscription.plan'].sudo().browse(plan_id)
        if not plan.exists() or not plan.active:
            return _err('Plan not available.')
        sub.sudo().write({'plan_id': plan_id})
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/billing/pause', type='http', auth='user', methods=['POST'])
    def portal_billing_pause(self, **kwargs):
        sub = self._get_household_active_sub()
        if not sub or sub.state != 'active':
            return request.make_response(
                json.dumps({'ok': False, 'error': 'No active subscription to pause.'}),
                headers=[('Content-Type', 'application/json')],
            )
        sub.sudo().write({'state': 'paused'})
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/billing/resume', type='http', auth='user', methods=['POST'])
    def portal_billing_resume(self, **kwargs):
        sub = self._get_household_active_sub()
        if not sub or sub.state != 'paused':
            return request.make_response(
                json.dumps({'ok': False, 'error': 'Subscription is not paused.'}),
                headers=[('Content-Type', 'application/json')],
            )
        sub.sudo().write({'state': 'active'})
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )

    @http.route('/my/dojo/billing/cancel', type='http', auth='user', methods=['POST'])
    def portal_billing_cancel(self, **kwargs):
        sub = self._get_household_active_sub()
        if not sub:
            return request.make_response(
                json.dumps({'ok': False, 'error': 'No active subscription found.'}),
                headers=[('Content-Type', 'application/json')],
            )
        sub.sudo().write({'state': 'cancelled', 'end_date': fields.Date.today()})
        return request.make_response(
            json.dumps({'ok': True}),
            headers=[('Content-Type', 'application/json')],
        )


    # ── /my/dojo/household ────────────────────────────────────────────────
    @http.route(
        '/my/dojo/household',
        type='http', auth='user', methods=['GET', 'POST'], website=True,
    )
    def portal_my_household(self, **post):
        member = self._get_current_member()
        if not member:
            return request.render('dojo_members_portal.portal_no_member', {})

        can_edit = member.role in ('parent', 'both')
        household = member.sudo().household_id
        error = {}
        success = False

        if request.httprequest.method == 'POST' and can_edit:
            # Update household name
            new_name = post.get('household_name', '').strip()
            if household and new_name:
                household.sudo().write({'name': new_name})

            # Process emergency contact updates for each household member
            member_ids = self._get_household_member_ids()
            for m_id in member_ids:
                # Delete removed contacts
                removed_ids = post.get(f'remove_contact_{m_id}', '').split(',')
                for rid in removed_ids:
                    try:
                        rid = int(rid)
                        contact = request.env['dojo.emergency.contact'].sudo().browse(rid)
                        if contact.member_id.id == m_id:
                            contact.unlink()
                    except (ValueError, Exception):
                        pass

            # Add new emergency contact if submitted
            new_contact_member_id = post.get('new_contact_member_id')
            new_contact_name = post.get('new_contact_name', '').strip()
            new_contact_relationship = post.get('new_contact_relationship', '').strip()
            new_contact_phone = post.get('new_contact_phone', '').strip()

            if new_contact_name and new_contact_phone and new_contact_member_id:
                try:
                    nc_member_id = int(new_contact_member_id)
                    if nc_member_id in member_ids:
                        request.env['dojo.emergency.contact'].sudo().create({
                            'member_id': nc_member_id,
                            'name': new_contact_name,
                            'relationship': new_contact_relationship or 'Other',
                            'phone': new_contact_phone,
                            'email': post.get('new_contact_email', '').strip() or False,
                            'is_primary': False,
                        })
                except (ValueError, Exception):
                    error['new_contact'] = _('Could not save the new contact.')

            if not error:
                return request.redirect('/my/dojo?tab=household&saved=1')

        # Re-fetch members for display (POST with errors falls through here)
        household_members = request.env['dojo.member'].sudo().browse(
            self._get_household_member_ids()
        )
        return request.render('dojo_members_portal.portal_my_household', {
            'member': member,
            'can_edit': can_edit,
            'household': household,
            'household_members': household_members,
            'page_name': 'dojo_household',
            'error': error,
            'success': False,
        })
