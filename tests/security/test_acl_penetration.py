"""Penetration tests for chunk-level ACL isolation."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import jwt
import pytest

from proxy.app.auth import jwt as jwt_auth
from proxy.app.auth.jwt import UserContext
from proxy.app.auth.user_db import UserDatabase
from proxy.app.shared.access_control import filter_chunks
from proxy.app.shared.config import JWT_SECRET

CHUNKS = [
    {"id": "public", "access_level": "public"},
    {"id": "confidential", "access_level": "confidential", "allowed_groups": ["security"]},
    {"id": "alice-only", "access_level": "restricted", "allowed_users": ["alice"]},
    {"id": "bob-only", "access_level": "restricted", "allowed_users": ["bob"]},
]


def test_admin_role_bypasses_all_acl() -> None:
    admin = UserContext(user_id="1", username="admin", roles=["admin"])
    assert filter_chunks(CHUNKS, admin) == CHUNKS


def test_user_cannot_access_restricted_chunks() -> None:
    user = UserContext(user_id="2", username="charlie", roles=["viewer"])
    assert [chunk["id"] for chunk in filter_chunks(CHUNKS, user)] == ["public"]


def test_user_cannot_access_chunks_of_other_users() -> None:
    alice = UserContext(user_id="3", username="alice", roles=["admin"])
    alice.roles = ["viewer"]
    visible = filter_chunks(CHUNKS, alice)
    assert "bob-only" not in {chunk["id"] for chunk in visible}


def test_role_downgrade_immediately_loses_access() -> None:
    user = UserContext(user_id="4", username="alice", roles=["admin"], groups=["security"])
    assert len(filter_chunks(CHUNKS, user)) == len(CHUNKS)
    user.roles = ["viewer"]
    user.groups = []
    assert [chunk["id"] for chunk in filter_chunks(CHUNKS, user)] == ["public"]


def test_expired_tokens_lose_access() -> None:
    token = jwt.encode(
        {
            "sub": "5",
            "preferred_username": "alice",
            "roles": ["admin"],
            "exp": datetime.now(UTC) - timedelta(seconds=1),
        },
        JWT_SECRET,
        algorithm="HS256",
    )
    with patch.object(jwt_auth, "JWT_ALGORITHM", "HS256"), patch.object(jwt_auth, "JWT_SECRET", JWT_SECRET):
        assert jwt_auth.get_user_from_token(token) is None


@pytest.mark.asyncio
async def test_deleted_users_lose_access(tmp_path) -> None:
    database = UserDatabase(str(tmp_path / "users.db"))
    created = await database.create_user("deleted-user", "StrongPassword1!", roles=["admin"])
    assert await database.get_user(created["user_id"]) is not None
    assert await database.delete_user(created["user_id"])
    assert await database.get_user(created["user_id"]) is None
