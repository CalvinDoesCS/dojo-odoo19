# Dojo CRM Workflow

## Overview

`dojo_crm` extends Odoo 19's built-in CRM with a martial-arts-studio-specific lead pipeline. It adds trial booking, lead scoring, automated follow-ups, and a one-click "Convert to Member" wizard.

---

## Pipeline Stages

| #   | Stage              | Description                                             |
| --- | ------------------ | ------------------------------------------------------- |
| 1   | **New Lead**       | Initial inquiry — no qualification yet                  |
| 2   | **Qualified**      | Interest confirmed; booking token generated and emailed |
| 3   | **Trial Booked**   | Trial class session scheduled via wizard                |
| 4   | **Trial Attended** | Lead showed up; offer sent                              |
| 5   | **Trial Expired**  | Offer window closed without conversion                  |
| 6   | **Offer Made**     | Custom membership offer presented                       |
| 7   | **Converted**      | Lead converted to `dojo.member`; lead archived          |

---

## Lead Scoring

Scores are computed automatically from `crm.lead` fields and tags (0–100 scale):

| Signal                                          | Points |
| ----------------------------------------------- | ------ |
| Email address present                           | +10    |
| Phone number present                            | +10    |
| Tag: Referral                                   | +20    |
| Tag: Walk-In                                    | +15    |
| Tag: Event                                      | +15    |
| Tag: Online                                     | +10    |
| Interest tag (Adult BJJ / Kids BJJ / Muay Thai) | +15    |
| Age tag (Adult / Teen / Child)                  | +5     |
| Booking link clicked                            | +10    |
| Trial attended                                  | +15    |

Score is displayed as a badge on the kanban card and as a percentage bar on the form view.

---

## Automated Actions (per Stage)

### Qualified

- Generates unique `trial_booking_token` and `trial_cancel_token` (UUID, 14-day expiry)
- Sends **"Qualified Invite"** email with a public booking link (`/trial/book/<token>`)
- Updates `last_engagement_date`

### Trial Booked

- Sends **"Trial Booked Confirmation"** email with session details and an ICS calendar attachment
- Creates a **Call** activity ("Follow up on trial booking for _name_") due 1 hour before the session
- Updates `last_engagement_date`

### Trial Attended

- Sets `trial_attended = True`
- Sends membership **offer email**
- Records `offer_sent_date`

### Converted (via wizard)

- Creates `dojo.member` record linked to lead
- Sets `is_converted = True`, archives the lead

---

## Cron Automations

| Cron                  | Trigger                                     | Action                                           |
| --------------------- | ------------------------------------------- | ------------------------------------------------ |
| Trial reminder        | 24 h before session                         | Email/SMS reminder to lead                       |
| No-show detection     | 48 h after Trial Booked (if still in stage) | Sets `no_show = True`, sends re-engagement email |
| No-show 2nd follow-up | 5 days after no-show                        | Sends second follow-up email                     |
| Offer expiry nudge    | 72 h before offer expiry                    | Sends urgency email                              |
| Trial expired         | Offer window passes                         | Moves lead to Trial Expired stage                |

---

## Book Trial Wizard

**Button**: "Book Trial" on the lead form header.

1. Wizard presents open class sessions as a dropdown
2. Representative selects a session and clicks **Confirm Booking**
3. On confirmation:
   - `trial_session_id` is set on the lead
   - Lead stage moves to **Trial Booked**
   - Confirmation email with ICS attachment is queued
   - A _Call_ activity is auto-scheduled

---

## Convert to Member Wizard

**Button**: "Convert to Member" on the lead form header (visible until `is_converted = True`).

### Fields

| Field                         | Default                                    |
| ----------------------------- | ------------------------------------------ |
| First / Last Name             | From linked partner or lead contact name   |
| Role                          | `student` (options: student, parent, both) |
| Email / Phone                 | From partner or lead                       |
| Date of Birth                 | Blank                                      |
| Create New Household          | ✓ (student role requires guardian name)    |
| Guardian Name / Email / Phone | Blank                                      |
| Create Subscription           | ✓                                          |
| Subscription Plan             | Dropdown from `dojo.subscription.plan`     |
| Start Date                    | Today                                      |

### On Confirm

1. Creates or updates `res.partner` record
2. If _Create New Household_: creates household company partner + guardian partner
3. Creates `dojo.member` (state: active)
4. If _Create Subscription_: creates `dojo.member.subscription` record
5. Links `dojo_member_id` on the lead, sets `trial_attended = True`
6. Moves lead to **Converted** stage and archives it
7. Returns form view of the new `dojo.member` record

---

## Public Trial Booking (Portal)

When a lead reaches **Qualified** stage, two URLs are generated:

- `/trial/book/<token>` — Public booking page; lead selects a class session
- `/trial/manage/<token>` — Public cancel/reschedule page

Tokens expire after 14 days. Clicking the booking URL sets `booking_link_clicked = True` (+10 lead score).

---

## Engagement & AI Tab

The form's **Engagement & AI** tab exposes:

- `ai_summary` — Auto-generated summary (populated by `dojo_assistant` if installed)
- `last_engagement_date` — Updated on stage changes, emails, and booking link visits
- AI intent and scoring fields

---

## Bugs Found & Fixed During Testing

| #   | File                                        | Bug                                                                                                                                                                                             | Fix                                                                                                      |
| --- | ------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| 1   | `models/crm_lead.py`                        | `_get_ics_attachment()` returned `attachment.id` (int); automation rule then called `.id` on it → `AttributeError`                                                                              | Changed `return attachment.id` → `return attachment`                                                     |
| 2   | `data/base_automation.xml`                  | Two automation rules referenced `rec.mobile` which doesn't exist on `crm.lead` in Odoo 19                                                                                                       | Changed to `rec.partner_id.mobile if rec.partner_id else False`                                          |
| 3   | `wizards/dojo_convert_lead_wizard.py`       | `default_get` accessed `lead.mobile` and `lead.partner_id.mobile`; `action_convert` wrote `"mobile"` into `res.partner` create/write dicts — `mobile` doesn't exist on `res.partner` in Odoo 19 | Removed all `mobile` from `res.partner` dicts; set wizard's own `mobile` field to `""` in `default_get`  |
| 4   | `models/ai_crm_service.py`                  | `lead.mobile` referenced in AI service phone lookup                                                                                                                                             | Changed to `lead.partner_id.mobile if lead.partner_id else None`                                         |
| 5   | `views/crm_dashboard.xml` _(prior session)_ | Kanban JS crash: field declarations missing for dojo-specific fields                                                                                                                            | Added `<field>` declarations in kanban xpath; changed template to use `record.dojo_lead_score.raw_value` |
