"""
Install / migrate hooks for dojo_base.

Grants the built-in 'admin' user the Dojo Admin group so the Admin Dashboard
menu is visible without manual configuration.  The logic runs both on first
install (post_init_hook) and on every subsequent upgrade (post_migrate_hook)
so the permission is never accidentally lost.
"""


def _ensure_admin_dojo_group(env):
    """Core helper: give the admin user the Dojo Admin group if missing."""
    # Use the canonical base.user_admin reference so this works regardless of
    # what the administrator's login address happens to be.
    admin_user = env.ref("base.user_admin", raise_if_not_found=False)
    if not admin_user:
        return
    group_admin = env.ref("dojo_base.group_dojo_admin", raise_if_not_found=False)
    if not group_admin:
        return
    if group_admin not in admin_user.group_ids:
        admin_user.write({"group_ids": [(4, group_admin.id)]})


def post_init_hook(env):
    """Add the admin user to the Dojo Admin group on first install."""
    _ensure_admin_dojo_group(env)


def post_migrate_hook(env, *args, **kwargs):
    """Re-apply admin group on every install or upgrade of dojo_base."""
    _ensure_admin_dojo_group(env)
