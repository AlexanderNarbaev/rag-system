# proxy/app/ldap_auth.py
"""
LDAP / Active Directory authentication module.

Provides optional LDAP authentication alongside the local SQLite user database.
When AD_ENABLED=true, the login endpoint first attempts LDAP bind before
falling back to local authentication.

Uses ldap3 library (pure Python, no system dependencies).
Graceful degradation: if the LDAP server is unreachable, logs a warning
and falls through to local auth.
"""

import logging
from typing import Any

from proxy.app.auth.user_db import get_user_db
from proxy.app.shared.config import (
  AD_BASE_DN,
  AD_ENABLED,
  AD_URL,
  AD_USER_DN_TEMPLATE,
)

logger = logging.getLogger (__name__)


async def authenticate_ldap (username: str, password: str) -> dict [str, Any] | None:
  """Authenticate a user against LDAP/AD.

  On successful bind:
  - Looks up the user in the local SQLite database
  - If not found, auto-creates a local user record with default 'user' role
  - Returns the user dict for token creation

  Args:
      username: The username to authenticate.
      password: The password for LDAP bind.

  Returns:
      User dict (from SQLite) or None if authentication fails.
  """
  if not AD_ENABLED or not AD_URL:
    return None

  try:
    from ldap3 import ALL, Connection, Server
  except ImportError:
    logger.warning ("ldap3 not installed — LDAP auth disabled")
    return None

  user_dn = _build_user_dn (username)
  if not user_dn:
    logger.warning ("Could not build user DN for %s", username)
    return None

  try:
    server = Server (AD_URL, get_info = ALL, connect_timeout = 5)
    conn = Connection (server, user = user_dn, password = password, auto_bind = True)
  except Exception as e:
    logger.warning ("LDAP bind failed for %s: %s", username, e)
    return None

  # Bind successful — get or create local user
  try:  # noqa: SIM105
    conn.unbind ()
  except Exception:
    pass

  return await _sync_ldap_user (username)


def _build_user_dn (username: str) -> str:
  """Build the LDAP user DN from the template."""
  template = AD_USER_DN_TEMPLATE or "cn={username},{base_dn}"
  base_dn = AD_BASE_DN

  dn = template.replace ("{username}", username)
  if "{base_dn}" in dn and base_dn:
    dn = dn.replace ("{base_dn}", base_dn)

  return dn


async def _sync_ldap_user (username: str) -> dict [str, Any]:
  """Ensure a local user record exists for an LDAP-authenticated user.

  Returns the user dict from the local database.
  """
  db = get_user_db ()

  # Check if user already exists locally
  user = await db.get_user_by_username (username)
  if user:
    return user

  # Auto-create local user
  import hashlib
  import secrets as _secrets

  _user_id = hashlib.sha256 (f"ldap:{username}:{_secrets.token_hex (8)}".encode ()).hexdigest () [:24]
  random_password = _secrets.token_urlsafe (32)  # LDAP users don't need local password

  try:
    user = await db.create_user (username = username, password = random_password, email = f"{username}@ldap",
        roles = ["user"],  # Default role; AD group mapping can be added later
        groups = [], access_level = "internal", namespace = "", )
    logger.info ("Auto-created local user for LDAP account: %s", username)
    # Re-fetch to get full user dict
    return await db.get_user (user ["user_id"]) or user
  except ValueError:
    # Race condition: user was created between check and create
    return await db.get_user_by_username (username) or {}
