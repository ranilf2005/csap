from datetime import UTC, datetime
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_access_token
from app.models import AuditLog, User

bearer_scheme = HTTPBearer(auto_error=True)

DbSession = Annotated[Session, Depends(get_db)]

# Reachable while the installation password is still in place.
_PASSWORD_CHANGE_EXEMPT = ("/api/v1/auth/change-password", "/api/v1/auth/me")


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(bearer_scheme)],
    db: DbSession,
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise unauthorized from None

    user = db.get(User, payload.get("sub", ""))
    if user is None or not user.is_active:
        raise unauthorized

    # A password change ends sessions that were already open.
    issued_at = payload.get("iat")
    changed_at = user.password_changed_at
    if issued_at and changed_at:
        if changed_at.tzinfo is None:
            changed_at = changed_at.replace(tzinfo=UTC)
        if datetime.fromtimestamp(issued_at, tz=UTC) < changed_at:
            raise unauthorized

    # The installation password must be replaced before anything else is reachable.
    if user.must_change_password and request.url.path not in _PASSWORD_CHANGE_EXEMPT:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Change the installation password before using the platform",
        )

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str):
    def _check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient privileges")
        return user

    return _check


def record_audit(
    db: Session,
    request: Request,
    action: str,
    actor: str | None = None,
    outcome: str = "success",
    target_type: str | None = None,
    target_id: str | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            outcome=outcome,
            target_type=target_type,
            target_id=target_id,
            source_ip=request.client.host if request.client else None,
            detail=detail,
        )
    )
    db.commit()
