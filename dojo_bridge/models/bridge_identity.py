"""
bridge_identity.py
──────────────────
x.bridge.identity — one record per Firebase UID × company (tenant).

This is the authoritative link between a Firebase user and the Odoo
business objects (dojo.member + res.users) within a specific tenant company.

Lifecycle
─────────
1. NestJS Control Plane calls POST /bridge/v1/auth/resolve.
2. The controller calls BridgeIdentity.resolve_or_create().
3. If no identity exists, a new x.bridge.identity is created and —
   if a matching dojo.member can be found by email — linked automatically.
4. The returned identity record is injected into every subsequent
   request context by the @require_bridge_auth middleware.
"""
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class BridgeIdentity(models.Model):
    _name = "x.bridge.identity"
    _description = "Bridge Identity: Firebase UID → dojo.member"
    _order = "create_date desc"

    # ── core identity fields ──────────────────────────────────────────────────

    firebase_uid = fields.Char(
        string="Firebase UID",
        required=True,
        index=True,
        help="Immutable Firebase user ID from the JWT sub / firebase_uid claim.",
    )
    company_id = fields.Many2one(
        "res.company",
        string="Tenant Company",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.company,
        help="The Odoo company this identity belongs to (= tenant discriminator).",
    )
    member_id = fields.Many2one(
        "dojo.member",
        string="Member",
        ondelete="set null",
        index=True,
        help="Linked dojo.member record. May be NULL temporarily during provisioning.",
    )

    # ── status ────────────────────────────────────────────────────────────────

    is_active = fields.Boolean(
        string="Active",
        default=True,
        index=True,
        help="Set to False to revoke access without destroying the record.",
    )
    last_seen = fields.Datetime(
        string="Last Seen",
        readonly=True,
        help="Updated on every successfully authenticated request.",
    )

    # ── cached JWT claims (informational, not used for enforcement) ───────────

    firebase_email = fields.Char(
        string="Firebase Email",
        help="Email from the last JWT payload. May differ from dojo.member email.",
    )
    firebase_display_name = fields.Char(string="Firebase Display Name")
    granted_role = fields.Char(
        string="Role Claim",
        help="Role string from the last validated JWT (e.g. 'member', 'instructor', 'admin').",
    )
    granted_scope = fields.Char(
        string="Scope Claims",
        help="Space-separated scope string from the last JWT.",
    )

    # ── computed convenience ──────────────────────────────────────────────────

    member_number = fields.Char(
        string="Member Number",
        related="member_id.member_number",
        store=False,
        readonly=True,
    )

    # ── constraints ───────────────────────────────────────────────────────────

    # Odoo 19: DB-level constraints are declared as class-level Constraint descriptors
    _firebase_uid_company_uniq = models.Constraint(
        "UNIQUE(firebase_uid, company_id)",
        "A Firebase UID can only be linked to one identity per company.",
    )

    # ── public API ────────────────────────────────────────────────────────────

    @api.model
    def resolve(
        self,
        firebase_uid: str,
        company_id: int,
        jwt_payload: dict | None = None,
    ) -> "BridgeIdentity | None":
        """
        Look up an existing ACTIVE identity.  Returns None if not found or
        inactive. Does NOT create — use resolve_or_create() for that.

        Optionally refreshes the cached JWT claims if jwt_payload is given.
        """
        identity = self.search(
            [
                ("firebase_uid", "=", firebase_uid),
                ("company_id", "=", company_id),
                ("is_active", "=", True),
            ],
            limit=1,
        )
        if not identity:
            return None
        if jwt_payload:
            identity._refresh_from_payload(jwt_payload)
        return identity

    @api.model
    def resolve_or_create(
        self,
        firebase_uid: str,
        company_id: int,
        jwt_payload: dict | None = None,
    ) -> "BridgeIdentity":
        """
        Find or provision an identity record.

        Auto-link logic:
          - If jwt_payload contains an 'email', search for a dojo.member whose
            partner email matches; link if found and not already taken.
          - Never overwrites an existing member_id link.

        This is intentionally permissive for provisioning; the Control Plane is
        responsible for ensuring JWTs are only issued to legitimate users.
        """
        identity = self.search(
            [
                ("firebase_uid", "=", firebase_uid),
                ("company_id", "=", company_id),
            ],
            limit=1,
        )

        if not identity:
            vals = {
                "firebase_uid": firebase_uid,
                "company_id": company_id,
                "is_active": True,
            }

            # Attempt auto-link by email
            if jwt_payload:
                email = jwt_payload.get("email") or jwt_payload.get("firebase_email")
                if email:
                    member = self._find_member_by_email(email, company_id)
                    if member:
                        vals["member_id"] = member.id
                        _logger.info(
                            "Bridge: auto-linked firebase_uid=%s to member %s by email",
                            firebase_uid,
                            member.member_number,
                        )

            identity = self.create(vals)
            _logger.info(
                "Bridge: provisioned new identity id=%s for firebase_uid=%s company_id=%s",
                identity.id,
                firebase_uid,
                company_id,
            )

        if jwt_payload:
            identity._refresh_from_payload(jwt_payload)

        return identity

    def touch(self) -> None:
        """Stamp last_seen without triggering a full write auditing cycle."""
        self.write({"last_seen": fields.Datetime.now()})

    def to_api_dict(self) -> dict:
        """Serialise for the /auth/resolve response payload."""
        member = self.member_id
        return {
            "identity_id": self.id,
            "firebase_uid": self.firebase_uid,
            "company_id": self.company_id.id,
            "company_name": self.company_id.name,
            "is_active": self.is_active,
            "member_id": member.id if member else None,
            "member_number": member.member_number if member else None,
            "membership_state": member.membership_state if member else None,
            "role": self.granted_role,
            "display_name": (
                self.firebase_display_name
                or (member.name if member else None)
            ),
            "email": self.firebase_email,
            "last_seen": self.last_seen.isoformat() if self.last_seen else None,
        }

    # ── private helpers ───────────────────────────────────────────────────────

    def _refresh_from_payload(self, payload: dict) -> None:
        vals = {
            "last_seen": fields.Datetime.now(),
        }
        if payload.get("email"):
            vals["firebase_email"] = payload["email"]
        if payload.get("name"):
            vals["firebase_display_name"] = payload["name"]
        if payload.get("role"):
            vals["granted_role"] = payload["role"]
        if payload.get("scope"):
            scope = payload["scope"]
            vals["granted_scope"] = (
                " ".join(scope) if isinstance(scope, list) else scope
            )
        self.write(vals)

    @api.model
    def _find_member_by_email(self, email: str, company_id: int):
        """Return matching dojo.member for email within company, or None."""
        member = self.env["dojo.member"].search(
            [
                ("email", "=", email),
                ("company_id", "=", company_id),
            ],
            limit=1,
        )
        return member or None
