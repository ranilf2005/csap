from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession, record_audit
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas import LoginRequest, PasswordChangeRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: DbSession) -> TokenResponse:
    user = db.query(User).filter(User.email == payload.email.lower()).one_or_none()

    # Same message and comparable timing for unknown user vs. wrong password.
    if user is None or not verify_password(payload.password, user.hashed_password) or not user.is_active:
        record_audit(db, request, "auth.login", actor=payload.email, outcome="failure")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")

    record_audit(db, request, "auth.login", actor=user.email, target_type="user", target_id=user.id)
    return TokenResponse(
        access_token=create_access_token(user.id, {"email": user.email, "role": user.role}),
        expires_in=settings.access_token_expire_minutes * 60,
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: PasswordChangeRequest, request: Request, user: CurrentUser, db: DbSession
) -> None:
    if not verify_password(payload.current_password, user.hashed_password):
        record_audit(db, request, "auth.change_password", actor=user.email, outcome="failure")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    db.commit()
    record_audit(db, request, "auth.change_password", actor=user.email, target_type="user", target_id=user.id)
