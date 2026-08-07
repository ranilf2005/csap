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


def get_current_user(
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
