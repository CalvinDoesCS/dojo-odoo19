from odoo import api, fields, models, _
from odoo.exceptions import UserError
from dateutil.relativedelta import relativedelta


class DojoOnboardingWizard(models.TransientModel):
    _name = 'dojo.onboarding.wizard'
    _description = 'Member Onboarding Wizard'

    # ── Step navigation ──────────────────────────────────────────────────────
    step = fields.Selection(
        selection=[
            ('member_info',    '1. Member Info'),
            ('household',      '2. Household'),
            ('guardian_setup', '3. Guardian Setup'),
            ('enrollment',     '4. Program Enrollment'),
            ('auto_enroll',    '4b. Auto-Enroll Schedule'),
            ('subscription',   '5. Subscription'),
            ('portal_access',  '6. Portal Access'),
        ],
        default='member_info',
        required=True,
    )

    # ── Step 1: Member Info ───────────────────────────────────────────────────
    name = fields.Char('Full Name', required=True)
    email = fields.Char('Email')
    phone = fields.Char('Phone')
    date_of_birth = fields.Date('Date of Birth')
    role = fields.Selection(
        selection=[
            ('student', 'Student'),
            ('parent', 'Parent'),
            ('both', 'Parent & Student'),
        ],
        default='student',
        required=True,
        string='Role',
    )
    emergency_note = fields.Text('Emergency / Medical Notes')

    # ── Step 2: Household ────────────────────────────────────────────────────
    household_id = fields.Many2one(
        'dojo.household',
        string='Existing Household',
    )
    create_new_household = fields.Boolean('Create a New Household', default=False)

    # New household: guardian member to create first
    new_guardian_name = fields.Char('Guardian Full Name')
    new_guardian_email = fields.Char('Guardian Email')
    new_guardian_phone = fields.Char('Guardian Phone')
    new_guardian_role = fields.Selection(
        selection=[
            ('parent', 'Parent'),
            ('both', 'Parent & Student'),
        ],
        default='parent',
        string='Guardian Role',
    )
    new_household_name = fields.Char(
        'New Household Name',
        help="Leave blank to auto-generate from the guardian's name.",
    )

    guardian_member_id = fields.Many2one(
        'dojo.member',
        string='Guardian Member',
        help='Select an existing member to link as guardian (for students).',
    )
    guardian_relation = fields.Selection(
        selection=[
            ('mother', 'Mother'),
            ('father', 'Father'),
            ('guardian', 'Guardian'),
            ('other', 'Other'),
        ],
        string="Guardian's Relation to New Member",
    )

    # ── Step 3: Program ────────────────────────────────────────────────────
    program_id = fields.Many2one(
        'dojo.program',
        string='Program',
        domain="[('active', '=', True)]",
        help='The program / curriculum this member is enrolling in (required).',
    )
    template_ids = fields.Many2many(
        'dojo.class.template',
        string='Add to Class Rosters',
        help='Add this member to recurring course rosters so they are auto-enrolled in future sessions.',
    )
    session_ids = fields.Many2many(
        'dojo.class.session',
        string='Specific Sessions (optional)',
        domain="[('state', '=', 'open')]",
        help='Optionally pre-register the member in specific upcoming sessions.',
    )

    # ── Step 4b: Auto-Enroll Preferences ─────────────────────────────────────
    auto_enroll_active = fields.Boolean(
        'Enable Auto-Enroll',
        default=True,
        help='If enabled, the member will be auto-enrolled in sessions based on the chosen days and mode.',
    )
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
    auto_enroll_date_from = fields.Date(
        'Auto-Enroll From',
        help='Required when mode is Multiday Range. First day of the date range.',
    )
    auto_enroll_date_to = fields.Date(
        'Auto-Enroll To',
        help='Required when mode is Multiday Range. Last day (inclusive) of the date range.',
    )

    # ── Step 4: Subscription ─────────────────────────────────────────────────
    plan_id = fields.Many2one(
        'dojo.subscription.plan',
        string='Subscription Plan',
        domain="['|', '&', ('plan_type', '=', 'program'), ('program_id', '=', program_id), ('plan_type', '=', 'course')]",
        help='Choose a plan that covers the selected program, or any course-based plan.',
    )
    subscription_start_date = fields.Date(
        'Subscription Start Date',
        default=fields.Date.today,
    )

    # ── Plan billing display fields (related, read-only — for UI only) ───────
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
    plan_sessions_per_period = fields.Integer(
        related='plan_id.sessions_per_period', readonly=True, string='Sessions / Period',
    )
    plan_unlimited_sessions = fields.Boolean(
        related='plan_id.unlimited_sessions', readonly=True,
    )
    plan_description = fields.Text(
        related='plan_id.description', readonly=True, string='Plan Notes',
    )

    # ── Step 5: Portal Access ────────────────────────────────────────────────
    create_portal_login = fields.Boolean(
        'Create Portal Login for New Member',
        default=True,
        help='Creates a user account linked to the new member so they can log into the portal.',
    )
    send_welcome_email = fields.Boolean(
        'Send Welcome Email to Member',
        default=True,
    )
    send_welcome_sms = fields.Boolean(
        'Send Welcome SMS to Member',
        default=False,
    )
    create_guardian_portal_login = fields.Boolean(
        'Create Portal Login for Guardian',
        default=True,
        help='Also creates a portal account for the new guardian so they can manage their household online.',
    )
    send_guardian_welcome_email = fields.Boolean(
        'Send Welcome Email to Guardian',
        default=True,
    )
    send_guardian_welcome_sms = fields.Boolean(
        'Send Welcome SMS to Guardian',
        default=False,
    )

    # ── Result (set after confirm) ────────────────────────────────────────────
    created_member_id = fields.Many2one('dojo.member', string='Created Member', readonly=True)

    # ── Step helpers ─────────────────────────────────────────────────────────
    _STEP_ORDER = ['member_info', 'household', 'guardian_setup', 'enrollment', 'auto_enroll', 'subscription', 'portal_access']

    def _reopen_wizard(self):
        """Return an action that re-opens this transient record (keeps state)."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    @api.onchange('role')
    def _onchange_role(self):
        """Auto-enable new-household when registering a parent (they are their own guardian)."""
        if self.role == 'parent':
            self.create_new_household = True

    def _should_skip_step(self, step_name):
        """Return True if the given step should be skipped given the current wizard state.
        Override in sub-modules (always call super()) to add additional skip conditions."""
        if step_name == 'guardian_setup':
            # Skip when not creating a new household, or member IS their own guardian
            return not self.create_new_household or self.role in ('both', 'parent')
        if step_name == 'enrollment':
            # Parents don't enrol in a program — they register as account holders only
            return self.role == 'parent'
        if step_name == 'auto_enroll':
            return self.role == 'parent' or not self.template_ids
        if step_name == 'subscription':
            # Parents don't need a subscription at registration time
            return self.role == 'parent'
        return False

    def action_next(self):
        self.ensure_one()

        # ── Step-specific validation ───────────────────────────────────────
        if self.step == 'member_info':
            if not self.email:
                raise UserError(_(
                    'An email address is required for the member.'
                ))
            if not self.phone:
                raise UserError(_(
                    'A phone number is required for the member.'
                ))
        elif self.step == 'household':
            if not self.create_new_household:
                if not self.household_id:
                    raise UserError(_(
                        'Please select an existing household or choose to create a new one.'
                    ))
        elif self.step == 'guardian_setup':
            if not self.new_guardian_name:
                raise UserError(_(
                    'Guardian full name is required to create a new household.'
                ))
            if not self.new_guardian_email:
                raise UserError(_(
                    'An email address is required for the guardian.'
                ))
            if not self.new_guardian_phone:
                raise UserError(_(
                    'A phone number is required for the guardian.'
                ))
            if not self.guardian_relation:
                raise UserError(_(
                    "Please specify the guardian's relation to the new member."
                ))
        elif self.step == 'enrollment':
            if not self.program_id:
                raise UserError(_(
                    'Please select a program for this member.'
                ))
        elif self.step == 'auto_enroll':
            if self.auto_enroll_active and self.auto_enroll_mode == 'multiday':
                if not self.auto_enroll_date_from or not self.auto_enroll_date_to:
                    raise UserError(_(
                        'A From and To date are required for Multiday Range mode.'
                    ))
                if self.auto_enroll_date_from > self.auto_enroll_date_to:
                    raise UserError(_(
                        '"From" date must be on or before the "To" date.'
                    ))
        elif self.step == 'subscription':
            if not self.plan_id:
                raise UserError(_(
                    'A subscription plan is required. Please select a plan to continue.'
                ))

        # ── Advance step, cascading over any steps that should be skipped ──────
        idx = self._STEP_ORDER.index(self.step)
        if idx < len(self._STEP_ORDER) - 1:
            next_idx = idx + 1
            while next_idx < len(self._STEP_ORDER) - 1 and self._should_skip_step(self._STEP_ORDER[next_idx]):
                next_idx += 1
            self.step = self._STEP_ORDER[next_idx]
        return self._reopen_wizard()

    def action_back(self):
        self.ensure_one()
        idx = self._STEP_ORDER.index(self.step)
        if idx > 0:
            prev_idx = idx - 1
            while prev_idx > 0 and self._should_skip_step(self._STEP_ORDER[prev_idx]):
                prev_idx -= 1
            self.step = self._STEP_ORDER[prev_idx]
        return self._reopen_wizard()

    def action_confirm(self):
        self.ensure_one()

        if not self.name:
            raise UserError(_('Member name is required.'))
        if self.role != 'parent':
            if not self.program_id:
                raise UserError(_('A program selection is required.'))
            if not self.plan_id:
                raise UserError(_('A subscription plan is required.'))

        # ── Resolve / create household ────────────────────────────────────────
        household = self.household_id
        guardian_member = None

        if self.create_new_household:
            if self.role in ('both', 'parent'):
                # The member IS their own guardian — create the household now
                # and set them as primary_guardian_id after they are created below.
                hh_name = self.new_household_name or (self.name + ' Household')
                household = self.env['dojo.household'].create({
                    'name': hh_name,
                    'company_id': self.env.company.id,
                })
            else:
                # Standard path: create a separate guardian member first.
                guardian_vals = {
                    'name': self.new_guardian_name,
                    'email': self.new_guardian_email or False,
                    'phone': self.new_guardian_phone or False,
                    'role': self.new_guardian_role or 'parent',
                    'company_id': self.env.company.id,
                }
                guardian_member = self.env['dojo.member'].create(guardian_vals)

                hh_name = self.new_household_name or (self.new_guardian_name + ' Household')
                household = self.env['dojo.household'].create({
                    'name': hh_name,
                    'primary_guardian_id': guardian_member.id,
                    'company_id': self.env.company.id,
                })
                guardian_member.write({'household_id': household.id})

        # ── Create new member ─────────────────────────────────────────────────
        member_vals = {
            'name': self.name,
            'email': self.email or False,
            'phone': self.phone or False,
            'date_of_birth': self.date_of_birth or False,
            'role': self.role,
            'emergency_note': self.emergency_note or False,
            'company_id': self.env.company.id,
        }
        if household:
            member_vals['household_id'] = household.id

        member = self.env['dojo.member'].create(member_vals)

        # ── Set primary guardian on household (existing household path) ─────────
        if household and not household.primary_guardian_id:
            if self.role in ('parent', 'both'):
                household.primary_guardian_id = member.id

        # ── Guardian link ─────────────────────────────────────────────────────
        if self.create_new_household and guardian_member and household:
            # New household: newly created guardian → new member
            self.env['dojo.guardian.link'].create({
                'household_id': household.id,
                'guardian_member_id': guardian_member.id,
                'student_member_id': member.id,
                'relation': self.guardian_relation,
                'is_primary': True,
            })
        elif self.guardian_member_id and self.guardian_relation and household:
            # Existing household: selected guardian → new member
            self.env['dojo.guardian.link'].create({
                'household_id': household.id,
                'guardian_member_id': self.guardian_member_id.id,
                'student_member_id': member.id,
                'relation': self.guardian_relation,
                'is_primary': True,
            })

        # ── Subscription (required) — must be created BEFORE session/template
        # enrollments so the subscription constraint can validate new enrolments.
        # ─────────────────────────────────────────────────────────────────────
        if self.plan_id:
            sub_start = self.subscription_start_date or fields.Date.today()
            self.env['dojo.member.subscription'].create({
                'member_id': member.id,
                'plan_id': self.plan_id.id,
                'start_date': sub_start,
                'next_billing_date': sub_start,  # first invoice covers sub_start → sub_start+period
                'state': 'active',
                'company_id': self.env.company.id,
            })
        # Transition membership state to active
        member.action_set_active()

        # ── Program enrollment — access is now controlled by subscription ─────
        # No action needed here; the subscription plan links member to program.

        # ── Specific session enrollments (optional) ───────────────────────────
        for session in self.session_ids:
            # Enforce capacity before enrolling
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
        # ── Course roster assignment + auto-enroll preferences ───────────────────
        if self.template_ids:
            # Add member to each template's course roster
            for tmpl in self.template_ids:
                if member not in tmpl.course_member_ids:
                    tmpl.write({'course_member_ids': [(4, member.id)]})

            # Create auto-enroll preference (if active option was chosen)
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

        # ── Issue Stripe card for new households ──────────────────────────────
        if self.create_new_household and household:
            try:
                household.action_create_stripe_cardholder()
                household.action_create_stripe_card()
            except Exception:
                pass  # Stripe not configured yet — admin can issue the card manually from the household form

        # ── Portal login — new member ─────────────────────────────────────────
        portal_credentials = []
        if self.create_portal_login:
            if not member.email:
                raise UserError(_(
                    'An email address is required to create a portal login. '
                    'Please add an email in Step 1.'
                ))
            creds = member._grant_portal_access_credentials()
            if creds:
                portal_credentials.append(creds)
                if self.send_welcome_email:
                    user = self.env['res.users'].sudo().search(
                        [('partner_id', '=', member.partner_id.id)], limit=1
                    )
                    if user:
                        try:
                            user.action_reset_password()
                        except Exception:
                            pass  # non-fatal — credentials are shown on screen
                if self.send_welcome_sms:
                    self._send_welcome_sms(member)

        # ── Portal login — guardian (new household path only) ─────────────────
        if self.create_new_household and guardian_member and self.create_guardian_portal_login:
            if not guardian_member.email:
                raise UserError(_(
                    'A guardian email address is required to create a guardian portal login. '
                    'Please go back to Step 3 and enter the guardian\'s email.'
                ))
            creds = guardian_member._grant_portal_access_credentials()
            if creds:
                portal_credentials.append(creds)
                if self.send_guardian_welcome_email:
                    user = self.env['res.users'].sudo().search(
                        [('partner_id', '=', guardian_member.partner_id.id)], limit=1
                    )
                    if user:
                        try:
                            user.action_reset_password()
                        except Exception:
                            pass  # non-fatal — credentials are shown on screen
                if self.send_guardian_welcome_sms:
                    self._send_welcome_sms(guardian_member)

        # ── Onboarding record ──────────────────────────────────────────────────
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

        # Store reference so bridge modules (e.g. dojo_onboarding_stripe) can
        # access the newly created member after super().action_confirm() returns.
        self.created_member_id = member.id

        # Open the newly created member form
        member_form_action = {
            'type': 'ir.actions.act_window',
            'res_model': 'dojo.member',
            'res_id': member.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }

        if portal_credentials:
            lines = []
            for c in portal_credentials:
                lines.append(
                    _('%(name)s\nUsername: %(login)s\nTemp Password: %(pw)s',
                      name=c['name'], login=c['login'], pw=c['temp_password'])
                )
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Portal Access Created'),
                    'message': '\n\n'.join(lines),
                    'type': 'success',
                    'sticky': True,
                    'next': member_form_action,
                },
            }

        return member_form_action

    def _send_welcome_sms(self, member):
        """Send a welcome SMS to the member's mobile/phone via sms.sms (Twilio)."""
        partner = member.partner_id
        number = partner.mobile or partner.phone
        if not number:
            return
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url', '')
        portal_url = base_url.rstrip('/') + '/my/dojo'
        company_name = self.env.company.name
        body = _(
            'Welcome to %(company)s, %(name)s! '
            'Your member portal is ready — log in at %(url)s',
            company=company_name,
            name=member.name,
            url=portal_url,
        )
        try:
            self.env['sms.sms'].sudo().create({
                'number': number,
                'body': body,
                'partner_id': partner.id,
            }).send()
        except Exception:
            pass  # non-fatal — welcome SMS failure should not block onboarding
