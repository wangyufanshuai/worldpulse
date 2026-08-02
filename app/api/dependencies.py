"""Shared API dependencies backed by public application ports."""

from __future__ import annotations

from fastapi import Request

from app.core.trust_models import UserIdentity
from app.services.identity import IdentityApplicationPort, identity_service


identity: IdentityApplicationPort = identity_service


def current_actor(request: Request) -> UserIdentity:
    """Return the middleware actor or the compatibility system actor."""
    return getattr(request.state, "user", None) or identity.ensure_system_user()
