"""
bridge_config.py
────────────────
Thin helpers around ir.config_parameter so every other bridge file
reads/writes config through a single place.

Parameter keys (stored in ir.config_parameter):
  x_bridge.jwt_secret       – HS256 shared secret (min 32 chars) issued by NestJS
  x_bridge.webhook_secret   – HMAC-SHA256 secret for validating inbound webhook sigs
  x_bridge.tenant_map       – JSON dict  { "tenant_id": "odoo_db_name", ... }
  x_bridge.cors_origins     – comma-separated list of allowed CORS origins
  x_bridge.jwt_issuer       – expected "iss" claim value  (default: "dojo-control-plane")
  x_bridge.jwt_audience     – expected "aud" claim value  (default: "dojo-odoo-bridge")
"""
import json
import logging

_logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Sentinel used to distinguish "not found" from a stored empty string
# ──────────────────────────────────────────────────────────────────────────────
_MISSING = object()


class BridgeConfig:
    """
    Static helper — no Odoo model, just a namespace for config I/O.
    Always pass a *sudoed* ir.config_parameter recordset.

    Usage:
        params = env["ir.config_parameter"].sudo()
        secret = BridgeConfig.jwt_secret(params)
    """

    # ── individual getters ────────────────────────────────────────────────────

    @staticmethod
    def jwt_secret(params) -> str | None:
        return params.get_param("x_bridge.jwt_secret") or None

    @staticmethod
    def webhook_secret(params) -> str | None:
        return params.get_param("x_bridge.webhook_secret") or None

    @staticmethod
    def cors_origins(params) -> list[str]:
        raw = params.get_param("x_bridge.cors_origins", default="")
        return [o.strip() for o in raw.split(",") if o.strip()]

    @staticmethod
    def jwt_issuer(params) -> str:
        return params.get_param("x_bridge.jwt_issuer", default="dojo-control-plane")

    @staticmethod
    def jwt_audience(params) -> str:
        return params.get_param("x_bridge.jwt_audience", default="dojo-odoo-bridge")

    @staticmethod
    def tenant_map(params) -> dict:
        """
        Returns { tenant_id: db_name, ... }.
        An empty/invalid value returns {}.
        """
        raw = params.get_param("x_bridge.tenant_map", default="{}")
        try:
            mapping = json.loads(raw)
            if not isinstance(mapping, dict):
                raise ValueError("tenant_map must be a JSON object")
            return mapping
        except (json.JSONDecodeError, ValueError) as exc:
            _logger.error("x_bridge.tenant_map is invalid JSON: %s", exc)
            return {}

    @staticmethod
    def db_for_tenant(params, tenant_id: str) -> str | None:
        """
        Resolve tenant_id → Odoo DB name.
        Returns None if the tenant is unknown.

        Special-case: if tenant_map is empty and the current DB name is
        already set (single-tenant bootstrap mode), return the current DB
        name directly so the bridge works out-of-the-box before operators
        configure the map.
        """
        mapping = BridgeConfig.tenant_map(params)
        if tenant_id in mapping:
            return mapping[tenant_id]

        # Single-tenant convenience fallback —
        # if there is exactly ONE entry in the map, return it regardless of
        # tenant_id (useful during development / before multi-DB setup).
        if len(mapping) == 1:
            only_db = next(iter(mapping.values()))
            _logger.warning(
                "tenant_id %r not in map; falling back to single entry %r",
                tenant_id,
                only_db,
            )
            return only_db

        return None

    # ── setters (used by tests / install hooks) ───────────────────────────────

    @staticmethod
    def set(params, key: str, value: str) -> None:
        params.set_param(key, value)
