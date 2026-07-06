import logging
import os

logger = logging.getLogger("federation")

FEDERATION_AUTH_ENABLED = os.getenv("FEDERATION_AUTH_ENABLED", "false").lower() == "true"
FEDERATION_JWT_SECRET = os.getenv("FEDERATION_JWT_SECRET", os.getenv("JWT_SECRET", ""))
FEDERATION_JWT_ALGORITHM = os.getenv("FEDERATION_JWT_ALGORITHM", os.getenv("JWT_ALGORITHM", "HS256"))


def extract_user_groups_from_token(token: str) -> list[str]:
    try:
        import jwt
    except ImportError:
        logger.warning("PyJWT not installed — cannot decode tokens")
        return []

    if not FEDERATION_JWT_SECRET:
        logger.warning("No JWT secret configured — returning empty groups")
        try:
            payload = jwt.decode(token, options={"verify_signature": False})
            return payload.get("groups", payload.get("realm_access", {}).get("roles", []))
        except Exception:
            return []

    try:
        payload = jwt.decode(
            token,
            key=FEDERATION_JWT_SECRET,
            algorithms=[FEDERATION_JWT_ALGORITHM],
            options={"verify_exp": True},
        )
        groups = payload.get("groups", [])
        realm_roles = payload.get("realm_access", {}).get("roles", [])
        return groups + realm_roles
    except jwt.ExpiredSignatureError:
        logger.warning("JWT token has expired")
        return []
    except jwt.InvalidTokenError as exc:
        logger.warning(f"Invalid JWT token: {exc}")
        return []
    except Exception as exc:
        logger.warning(f"JWT decode error: {exc}")
        return []


def extract_user_groups(request) -> list[str]:
    if not FEDERATION_AUTH_ENABLED:
        groups_env = os.getenv("FEDERATION_DEFAULT_GROUPS", "admin")
        return [g.strip() for g in groups_env.split(",")]

    auth_header = request.headers.get("Authorization") or request.headers.get("x-auth-token", "")
    if not auth_header:
        return []

    token = auth_header
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]

    if not token:
        return []

    return extract_user_groups_from_token(token)
