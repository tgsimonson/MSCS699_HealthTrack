"""request dependencies: current user, role checks, and patient scope checks"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AuthenticationError, NotFoundError, PermissionDenied
from app.models import Patient, User
from app.models.enums import AuditAction, UserRole
from app.repositories import AuditRepository, PatientRepository, UserRepository
from app.security import decode_access_token

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

DB = Annotated[Session, Depends(get_db)]
CARE_ROLES = {UserRole.clinician, UserRole.physician}


def get_current_user(request: Request, db: DB, token: Annotated[str | None, Depends(oauth2)]) -> User:
    if not token:
        raise AuthenticationError("missing bearer token")
    claims = decode_access_token(token)
    try:
        user_id, session_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except ValueError as exc:
        raise AuthenticationError("access token invalid") from exc
    users = UserRepository(db)
    user = db.get(User, user_id)
    sess = users.get_session(session_id)
    # a revoked session (logout, password change, token reuse) kills its access tokens immediately
    if user is None or not user.is_active or sess is None or sess.user_id != user_id or sess.revoked_at is not None:
        raise AuthenticationError("session is no longer valid")
    if claims.get("role") != user.role.value:
        raise AuthenticationError("role changed; log in again")
    request.state.session_id = session_id
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], User]:
    allowed = set(roles)

    def dep(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise PermissionDenied(f"role {user.role.value} cannot perform this action")
        return user

    return dep


class PatientAccess:
    """resolves {patient_id} and enforces role plus relationship

    patients reach only their own record; clinicians and physicians reach patients on their current care team;
    administrators reach demographics only (allow_admin); everyone else is refused. an out-of-scope patient
    returns 404 rather than 403 so the api never confirms that a record exists.
    """

    def __init__(self, *, allow_patient: bool = True, allow_admin: bool = False, care_roles: set[UserRole] | None = None,
                 action: AuditAction = AuditAction.read, entity: str = "patients") -> None:
        self.allow_patient, self.allow_admin = allow_patient, allow_admin
        self.care_roles = care_roles if care_roles is not None else CARE_ROLES
        self.action, self.entity = action, entity

    def __call__(self, db: DB, user: CurrentUser, patient_id: Annotated[uuid.UUID, Path()]) -> Patient:
        repo = PatientRepository(db)
        role_ok = (user.role in self.care_roles or (self.allow_patient and user.role == UserRole.patient)
                   or (self.allow_admin and user.role == UserRole.admin))
        if not role_ok:
            raise PermissionDenied(f"role {user.role.value} cannot access this resource")
        try:
            patient = repo.get(patient_id)
        except NotFoundError:
            raise
        in_scope = ((user.role == UserRole.patient and patient.user_id == user.user_id)
                    or (user.role in self.care_roles and repo.is_on_care_team(user.user_id, patient_id))
                    or (self.allow_admin and user.role == UserRole.admin))
        if not in_scope:
            AuditRepository(db).record(self.action, self.entity, actor=user, entity_id=patient_id,
                                       patient_id=patient_id, outcome="denied", details={"reason": "out of scope"})
            db.commit()   # keep the denial on record even though the request fails
            raise NotFoundError("patient not found")
        return patient
