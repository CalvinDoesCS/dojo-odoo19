from odoo import api, fields, models, _
from odoo.exceptions import UserError


class DojoOnboardingWizard(models.TransientModel):
    _name = 'dojo.onboarding.wizard'
    _description = 'Member Onboarding Wizard'

    # ── Phase & Step navigation ──────────────────────────────────────────────
    wizard_phase = fields.Selection(
        selection=[
            ('guardian', 'Guardian & Household'),
            ('student', 'Student Registration'),
        ],
        default='guardian',
        required=True,
    )
    step = fields.Selection(
        selection=[
            # Guardian phase
            ('guardian_contact',  'Guardian Contact'),
            ('household',        'Household'),
            ('guardian_portal',   'Guardian Portal'),
            # Student phase
            ('student_contact',   'Student Contact'),
            ('member_details',    'Member Details'),
            ('enrollment',        'Enrollment'),
            ('auto_enroll',       'Auto-Enroll'),
            ('subscription',      'Subscription'),
            ('student_portal',    'Student Portal'),
            ('summary',           'Summary'),
        ],
        default='guardian_contact',
        required=True,
    )

    # ── Phase 1, Step 1: Guardian Contact ────────────────────────────────────
    guardian_name = fields.Char('Guardian Full Name')
    guardian_email = fields.Char('Guardian Email')
    guardian_phone = fields.Char('Guardian Phone')
    guardian_street = fields.Char('Street')
    guardian_street2 = fields.Char('Street 2')
    guardian_city = fields.Char('City')
    guardian_state_id = fields.Many2one('res.country.state', string='State')
    guardian_zip = fields.Char('ZIP')
    guardian_country_id = fields.Many2one('res.country', string='Country')
    guardian_is_also_student = fields.Boolean(
        'I am also a student',
        default=False,
        help='Check this if the guardian also trains at the dojo.',
    )

    # ── Phase 1, Step 2: Household ───────────────────────────────────────────
    use_existing_household = fields.Boolean('Join Existing Household', default=False)
    household_id = fields.Many2one(
        'res.partner',
        string='Existing Household',
        domain=[('is_household', '=', True)],
    )
    new_household_name = fields.Char(
        'Household Name',
        help="Leave blank to auto-generate from the guardian's name.",
    )

    # ── Phase 1, Step 3: Guardian Portal ─────────────────────────────────────
    create_guardian_portal_login = fields.Boolean(
        'Create Portal Login for Guardian',
        default=True,
    )
    send_guardian_welcome_email = fields.Boolean(
        'Send Welcome Email to Guardian',
        default=True,
    )
    send_guardian_welcome_sms = fields.Boolean(
        'Send Welcome SMS to Guardian',
        default=False,
    )

    # ── Persistent refs (survive across student loops) ───────────────────────
    created_household_id = fields.Many2one('res.partner', string='Created Household', readonly=True)
    created_guardian_partner_id = fields.Many2one('res.partner', string='Created Guardian', readonly=True)
    students_created_ids = fields.Many2many(
        'dojo.member',
        'dojo_onboarding_wizard_student_rel',
        'wizard_id', 'member_id',
        string='Students Created',
        readonly=True,
    )
    guardian_portal_credentials = fields.Text(readonly=True)

    # ── Phase 2, Step 4: Student Contact ─────────────────────────────────────
    student_name = fields.Char('Student Full Name')
    student_email = fields.Char('Student Email')
    student_phone = fields.Char('Student Phone')
    student_date_of_birth = fields.Date('Date of Birth')
    student_is_minor = fields.Boolean('Is Minor', default=True)

    # ── Phase 2, Step 5: Member Details ──────────────────────────────────────
    emergency_note = fields.Text('Emergency / Medical Notes')

    # ── Phase 2, Step 6: Enrollment ──────────────────────────────────────────
    program_id = fields.Many2one(
        'dojo.program',
        string='Program',
        domain="[('active', '=', True)]",
    )
    template_ids = fields.Many2many(
        'dojo.class.template',
        string='Add to Class Rosters',
    )
    session_ids = fields.Many2many(
        'dojo.class.session',
        string='Specific Sessions (optional)',
        domain="[('state', '=', 'open')]",
    )

    # ── Phase 2, Step 7: Auto-Enroll ────────────────────────────────────────
    auto_enroll_active = fields.Boolean('Enable Auto-Enroll', default=True)
    auto_enroll_mode = fields.Selection(
        [
            ('permanent', 'Permanent (Never Remove)'),
            ('multiday', 'Limited Date Range'),
        ],
        string='Recurrence Mode',
        default='permanent',
    )
    auto_enroll_mon = fields.Boolean('Mon')
    auto_enroll_tue = fields.Boolean('Tue')
    auto_enroll_wed = fields.Boolean('Wed')
    auto_enroll_thu = fields.Boolean('Thu')
    auto_enroll_fri = fields.Boolean('Fri')
    auto_enroll_sat = fields.Boolean('Sat')
    auto_enroll_sun = fields.Boolean('Sun')
    auto_enroll_date_from = fields.Date('Auto-Enroll From')
    auto_enroll_date_to = fields.Date('Auto-Enroll To')

    # ── Phase 2, Step 8: Subscription ────────────────────────────────────────
    plan_id = fields.Many2one(
        'dojo.subscription.plan',
        string='Subscription Plan',
        domain="['|', '&', ('plan_type', '=', 'program'), ('program_id', '=', program_id), ('plan_type', '=', 'course')]",
    )
    subscription_start_date = fields.Date(
        'Subscription Start Date',
        default=fields.Date.today,
    )
    plan_currency_id = fields.Many2one(
        related='plan_id.currency_id', readonly=True, string='Currency',
    )
    plan_price = fields.Monetary(
        related='plan_id.price', readonly=True, string='Recurring Fee',
        currency_field='plan_currency_id',
    )
    plan_initial_fee = fields.Monetary(
        related='plan_id.initial_fee', readonly=True, string='Enrollment Fee',
        currency_field='plan_currency_id',
    )
    plan_billing_period = fields.Selection(
        related='plan_id.billing_period', readonly=True, string='Billing Period',
    )
    plan_credits_per_period = fields.Integer(
        compute='_compute_plan_credits_per_period', string='Credits / Billing Cycle',
    )
    plan_description = fields.Text(
        related='plan_id.description', readonly=True, string='Plan Notes',
    )
    defer_payment = fields.Boolean(
        'Pay Later',
        default=False,
        help='Create the subscription as Pending Payment instead of Active.',
    )

    @api.depends('plan_id')
    def _compute_plan_credits_per_period(self):
        for rec in self:
            rec.plan_credits_per_period = getattr(rec.plan_id, 'credits_per_period', 0) or 0

    # ── Phase 2, Step 9: Student Portal ──────────────────────────────────────
    create_portal_login = fields.Boolean(
        'Create Portal Login for Student',
        default=True,
    )
    send_welcome_email = fields.Boolean(
        'Send Welcome Email to Student',
        default=True,
    )
    send_welcome_sms = fields.Boolean(
        'Send Welcome SMS to Student',
        default=False,
    )

    # ── Result (set after each student creation, used by bridge modules) ─────
    created_member_id = fields.Many2one('dojo.member', string='Last Created Member', readonly=True)

    # ── Step helpers ─────────────────────────────────────────────────────────
    _GUARDIAN_STEPS = ['guardian_contact', 'household', 'guardian_portal']
    _STUDENT_STEPS = ['student_contact', 'member_details', 'enrollment', 'auto_enroll', 'subscription', 'student_portal', 'summary']

    @property
    def _STEP_ORDER(self):
        return self._GUARDIAN_STEPS + self._STUDENT_STEPS

    def _reopen_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    @api.onchange('use_existing_household')
    def _onchange_use_existing_household(self):
        if self.use_existing_household and self.household_id:
            guardian = self.household_id.primary_guardian_id
            if guardian:
                self.guardian_name = guardian.name
                self.guardian_email = guardian.email
                self.guardian_phone = guardian.phone

    def _should_skip_step(self, step_name):
        """Return True if the given step should be skipped given the current wizard state.
        Override in sub-modules (always call super()) to add additional skip conditions."""
        # When using existing household, skip household and guardian_portal steps
        if self.use_existing_household and step_name in ('household', 'guardian_portal'):
            return True
        if step_name == 'auto_enroll':
            return not self.template_ids
        return False

    # ── Validation ───────────────────────────────────────────────────────────
    def _validate_current_step(self):
        """Validate the current step before advancing. Raises UserError on failure."""
        if self.step == 'guardian_contact':
            if self.use_existing_household:
                if not self.household_id:
                    raise UserError(_('Please select an existing household or uncheck "Join Existing Household".'))
            else:
                if not self.guardian_name:
                    raise UserError(_('Guardian full name is required.'))
                if not self.guardian_email:
                    raise UserError(_('Guardian email is required.'))
                if not self.guardian_phone:
                    raise UserError(_('Guardian phone is required.'))
        elif self.step == 'household':
            pass  # Household choice now handled in guardian_contact
        elif self.step == 'student_contact':
            if not self.student_name:
                raise UserError(_('Student full name is required.'))
        elif self.step == 'enrollment':
            if not self.program_id:
                raise UserError(_('Please select a program for this student.'))
        elif self.step == 'auto_enroll':
            if self.auto_enroll_active and self.auto_enroll_mode == 'multiday':
                if not self.auto_enroll_date_from or not self.auto_enroll_date_to:
                    raise UserError(_('A From and To date are required for Multiday Range mode.'))
                if self.auto_enroll_date_from > self.auto_enroll_date_to:
                    raise UserError(_('"From" date must be on or before the "To" date.'))
        elif self.step == 'subscription':
            if not self.plan_id:
                raise UserError(_('A subscription plan is required.'))

    # ── Navigation ───────────────────────────────────────────────────────────
    def action_next(self):
        self.ensure_one()
        self._validate_current_step()

        # Existing household selected on step 1 → use it, then advance normally
        # (Stripe override intercepts this to route to the payment step)
        if self.step == 'guardian_contact' and self.use_existing_household:
            self._use_existing_household()
            self.wizard_phase = 'student'
            self.step = 'student_contact'
            return self._reopen_wizard()

        # End of guardian_portal → create guardian + household, then advance normally
        # (Stripe override intercepts this to route to the payment step)
        if self.step == 'guardian_portal':
            self._create_guardian_and_household()
            self.wizard_phase = 'student'
            self.step = 'student_contact'
            return self._reopen_wizard()

        # Normal step advancement within the current phase
        step_order = self._STEP_ORDER
        idx = step_order.index(self.step)
        if idx < len(step_order) - 1:
            next_idx = idx + 1
            while next_idx < len(step_order) - 1 and self._should_skip_step(step_order[next_idx]):
                next_idx += 1
            self.step = step_order[next_idx]
            # Transition wizard_phase when crossing into student steps
            if self.step in self._STUDENT_STEPS:
                self.wizard_phase = 'student'
        return self._reopen_wizard()

    def action_back(self):
        self.ensure_one()
        # Prevent going back into guardian phase from student phase
        if self.step == 'student_contact' and self.created_household_id:
            return self._reopen_wizard()

        step_order = self._STEP_ORDER
        idx = step_order.index(self.step)
        if idx > 0:
            prev_idx = idx - 1
            while prev_idx > 0 and self._should_skip_step(step_order[prev_idx]):
                prev_idx -= 1
            self.step = step_order[prev_idx]
        return self._reopen_wizard()

    # ── Student confirm (called from Summary step) ───────────────────────────
    def action_confirm_student(self):
        """Create the current student's member record and all related data."""
        self.ensure_one()
        member = self._create_student_member()
        self.created_member_id = member.id
        self.students_created_ids = [(4, member.id)]
        self.step = 'summary'
        return self._reopen_wizard()

    # ── Add another student (called from Summary step) ───────────────────────
    def action_add_another_student(self):
        """Reset student-specific fields and go back to student contact step."""
        self.ensure_one()
        self._reset_student_fields()
        self.step = 'student_contact'
        return self._reopen_wizard()

    # ── Finish (called from Summary step) ────────────────────────────────────
    def action_finish(self):
        """Close the wizard and open the household or last student."""
        self.ensure_one()

        # If guardian is also a student and hasn't been registered yet, register them
        if self.guardian_is_also_student and self.created_guardian_partner_id:
            guardian_already_member = self.env['dojo.member'].sudo().search(
                [('partner_id', '=', self.created_guardian_partner_id.id)], limit=1)
            if not guardian_already_member:
                # The admin needs to go through the student flow for the guardian too
                pass

        # Build portal credentials notification
        portal_credentials = []
        if self.guardian_portal_credentials:
            portal_credentials.append(self.guardian_portal_credentials)

        household = self.created_household_id
        if household:
            result_action = {
                'type': 'ir.actions.act_window',
                'res_model': 'res.partner',
                'res_id': household.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
            }
        elif self.students_created_ids:
            last = self.students_created_ids[-1]
            result_action = {
                'type': 'ir.actions.act_window',
                'res_model': 'dojo.member',
                'res_id': last.id,
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
            }
        else:
            result_action = {'type': 'ir.actions.act_window_close'}

        if portal_credentials:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Onboarding Complete'),
                    'message': '\n\n'.join(portal_credentials),
                    'type': 'success',
                    'sticky': True,
                    'next': result_action,
                },
            }
        return result_action

    # ── Guardian & Household creation ────────────────────────────────────────
    def _create_guardian_and_household(self):
        """Create the guardian res.partner and household. Called once at end of guardian phase."""
        self.ensure_one()
        # Guard against double-creation (e.g. user navigates back from payment
        # to guardian_portal and forward again).
        if self.created_guardian_partner_id:
            return

        # Create guardian partner
        guardian_vals = {
            'name': self.guardian_name,
            'email': self.guardian_email or False,
            'phone': self.guardian_phone or False,
            'street': self.guardian_street or False,
            'street2': self.guardian_street2 or False,
            'city': self.guardian_city or False,
            'state_id': self.guardian_state_id.id if self.guardian_state_id else False,
            'zip': self.guardian_zip or False,
            'country_id': self.guardian_country_id.id if self.guardian_country_id else False,
            'is_guardian': True,
            'company_id': self.env.company.id,
        }
        guardian = self.env['res.partner'].create(guardian_vals)

        # Create household
        hh_name = self.new_household_name or (self.guardian_name + ' Household')
        household = self.env['res.partner'].create({
            'name': hh_name,
            'is_household': True,
            'is_company': True,
            'primary_guardian_id': guardian.id,
            'street': self.guardian_street or False,
            'street2': self.guardian_street2 or False,
            'city': self.guardian_city or False,
            'state_id': self.guardian_state_id.id if self.guardian_state_id else False,
            'zip': self.guardian_zip or False,
            'country_id': self.guardian_country_id.id if self.guardian_country_id else False,
            'company_id': self.env.company.id,
        })
        guardian.write({'parent_id': household.id})

        self.created_guardian_partner_id = guardian.id
        self.created_household_id = household.id

        # Guardian portal access
        portal_credentials = []
        if self.create_guardian_portal_login and guardian.email:
            creds = guardian._grant_portal_access_credentials()
            if creds:
                line = _(
                    '%(name)s\nUsername: %(login)s\nTemp Password: %(pw)s',
                    name=creds['name'], login=creds['login'], pw=creds['temp_password'],
                )
                portal_credentials.append(line)
                if self.send_guardian_welcome_email:
                    user = self.env['res.users'].sudo().search(
                        [('partner_id', '=', guardian.id)], limit=1)
                    if user:
                        try:
                            user.action_reset_password()
                        except Exception:
                            pass
                if self.send_guardian_welcome_sms:
                    self._send_welcome_sms_to_partner(guardian)
        if portal_credentials:
            self.guardian_portal_credentials = '\n\n'.join(portal_credentials)

    def _use_existing_household(self):
        """Pre-fill wizard from an existing household selection."""
        self.ensure_one()
        household = self.household_id
        if not household:
            raise UserError(_('Please select an existing household.'))
        self.created_household_id = household.id
        guardian = household.primary_guardian_id
        if guardian:
            self.created_guardian_partner_id = guardian.id

    # ── Student member creation ──────────────────────────────────────────────
    def _create_student_member(self):
        """Create a student res.partner + dojo.member + subscription + enrollments + portal."""
        self.ensure_one()
        household = self.created_household_id

        # Create student partner
        partner_vals = {
            'name': self.student_name,
            'email': self.student_email or False,
            'phone': self.student_phone or False,
            'is_student': True,
            'is_minor': self.student_is_minor,
            'company_id': self.env.company.id,
        }
        if household:
            partner_vals['parent_id'] = household.id

        # Ensure member number sequence is past existing numbers to avoid unique constraint violations
        self._sync_member_sequence()

        # Create dojo.member (auto-creates res.partner if partner_id not given,
        # but we want to set is_minor etc. so we create partner explicitly)
        partner = self.env['res.partner'].create(partner_vals)
        member = self.env['dojo.member'].create({
            'partner_id': partner.id,
            'date_of_birth': self.student_date_of_birth or False,
            'emergency_note': self.emergency_note or False,
            'company_id': self.env.company.id,
        })

        # Subscription
        sub = None
        if self.plan_id:
            sub_start = self.subscription_start_date or fields.Date.today()
            sub_state = 'pending' if self.defer_payment else 'active'
            sub = self.env['dojo.member.subscription'].create({
                'member_id': member.id,
                'plan_id': self.plan_id.id,
                'start_date': sub_start,
                'next_billing_date': sub_start,
                'state': sub_state,
                'company_id': self.env.company.id,
            })
        if not self.defer_payment:
            member.action_set_active()

        # Session enrollments
        for session in self.session_ids:
            if session.seats_taken >= session.capacity:
                raise UserError(_(
                    'Session "%s" is at full capacity (%s/%s). '
                    'Remove it from the enrollment list or increase its capacity.',
                    session.name, session.seats_taken, session.capacity,
                ))
            self.env['dojo.class.enrollment'].create({
                'session_id': session.id,
                'member_id': member.id,
                'status': 'registered',
                'attendance_state': 'pending',
            })

        # Course roster + auto-enroll
        if self.template_ids:
            for tmpl in self.template_ids:
                if member not in tmpl.course_member_ids:
                    tmpl.write({'course_member_ids': [(4, member.id)]})
            if self.auto_enroll_active:
                Pref = self.env['dojo.course.auto.enroll']
                mode = self.auto_enroll_mode or 'permanent'
                for tmpl in self.template_ids:
                    pref_vals = {
                        'member_id': member.id,
                        'template_id': tmpl.id,
                        'active': True,
                        'mode': mode,
                        'pref_mon': self.auto_enroll_mon,
                        'pref_tue': self.auto_enroll_tue,
                        'pref_wed': self.auto_enroll_wed,
                        'pref_thu': self.auto_enroll_thu,
                        'pref_fri': self.auto_enroll_fri,
                        'pref_sat': self.auto_enroll_sat,
                        'pref_sun': self.auto_enroll_sun,
                    }
                    if mode == 'multiday':
                        pref_vals['date_from'] = self.auto_enroll_date_from
                        pref_vals['date_to'] = self.auto_enroll_date_to
                    Pref.create(pref_vals)

        # Student portal access
        portal_credentials = []
        if self.create_portal_login and partner.email:
            creds = partner._grant_portal_access_credentials()
            if creds:
                portal_credentials.append(creds)
                if self.send_welcome_email:
                    user = self.env['res.users'].sudo().search(
                        [('partner_id', '=', partner.id)], limit=1)
                    if user:
                        try:
                            user.action_reset_password()
                        except Exception:
                            pass
                if self.send_welcome_sms:
                    self._send_welcome_sms_to_partner(partner)

        # Onboarding record
        self.env['dojo.onboarding.record'].create({
            'member_id': member.id,
            'step_member_info': True,
            'step_household': bool(household),
            'step_enrollment': bool(self.program_id),
            'step_subscription': bool(self.plan_id),
            'step_portal_access': self.create_portal_login,
            'state': 'completed',
            'company_id': self.env.company.id,
        })

        return member

    def _sync_member_sequence(self):
        """Advance the dojo.member sequence past any existing member numbers.

        Prevents unique constraint violations when the sequence falls behind
        (e.g. after data imports or manual number assignments).
        """
        import re as _re
        sequence = self.env['ir.sequence'].sudo().search(
            [('code', '=', 'dojo.member')], limit=1)
        if not sequence:
            return
        result = self.env['dojo.member'].sudo().search_read(
            [('member_number', '!=', False)],
            fields=['member_number'],
            order='id desc', limit=100,
        )
        max_num = 0
        for row in result:
            match = _re.search(r'(\d+)$', row.get('member_number') or '')
            if match:
                max_num = max(max_num, int(match.group(1)))
        if max_num >= sequence.number_next:
            sequence.sudo().write({'number_next': max_num + 1})

    def _reset_student_fields(self):
        """Clear student-phase fields to prepare for another student registration."""
        self.write({
            'student_name': False,
            'student_email': False,
            'student_phone': False,
            'student_date_of_birth': False,
            'student_is_minor': True,
            'emergency_note': False,
            'program_id': False,
            'template_ids': [(5,)],
            'session_ids': [(5,)],
            'auto_enroll_active': True,
            'auto_enroll_mode': 'permanent',
            'auto_enroll_mon': False,
            'auto_enroll_tue': False,
            'auto_enroll_wed': False,
            'auto_enroll_thu': False,
            'auto_enroll_fri': False,
            'auto_enroll_sat': False,
            'auto_enroll_sun': False,
            'auto_enroll_date_from': False,
            'auto_enroll_date_to': False,
            'plan_id': False,
            'subscription_start_date': fields.Date.today(),
            'defer_payment': False,
            'create_portal_login': True,
            'send_welcome_email': True,
            'send_welcome_sms': False,
            'created_member_id': False,
        })

    def _send_welcome_sms_to_partner(self, partner):
        """Send a welcome SMS to a partner's mobile/phone via sms.sms (Twilio)."""
        number = getattr(partner, 'mobile', None) or partner.phone
        if not number:
            return
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        portal_url = base_url.rstrip('/') + '/my/dojo'
        company_name = self.env.company.name
        body = _(
            'Welcome to %(company)s, %(name)s! '
            'Your member portal is ready — log in at %(url)s',
            company=company_name,
            name=partner.name,
            url=portal_url,
        )
        try:
            self.env['sms.sms'].sudo().create({
                'number': number,
                'body': body,
                'partner_id': partner.id,
            }).send()
        except Exception:
            pass
