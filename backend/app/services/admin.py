"""Admin-role resolution.

The single source of truth for "is this email an admin" is:

    settings.admin_emails  (immutable config root admins)
      UNION
    admin_emails table     (granted at runtime by an existing admin)

User.role is a cached projection of that, kept in sync at register, at
login/2FA success, and once at startup - so require_admin (which checks
User.role, re-fetched per request) stays correct without an extra query
on every admin call.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AdminEmail, User, UserRole


def _root_admin_emails_lower() -> set[str]:
    return {e.strip().lower() for e in settings.admin_emails if e.strip()}


def is_root_admin_email(email: str) -> bool:
    """A config-level root admin - can never be demoted or deleted."""
    return email.strip().lower() in _root_admin_emails_lower()


def is_admin_email(db: Session, email: str) -> bool:
    """Effective admin status for an address: config root OR granted row."""
    if is_root_admin_email(email):
        return True
    normalized = email.strip().lower()
    return (
        db.scalar(
            select(AdminEmail.id).where(func.lower(AdminEmail.email) == normalized)
        )
        is not None
    )


def sync_user_role(db: Session, user: User) -> bool:
    """Force user.role to match the allowlist. Returns True if it changed.

    Does not commit - the caller owns the transaction. Demotes as well as
    promotes: the allowlist (config UNION table) is authoritative, so a
    user whose grant was revoked drops back to `user` the next time this
    runs for them.
    """
    should_be_admin = is_admin_email(db, user.email)
    target = UserRole.admin if should_be_admin else UserRole.user
    if user.role != target:
        user.role = target
        return True
    return False


def sync_all_admin_roles(db: Session) -> int:
    """Promote/demote every existing user to match the allowlist.

    Run once at startup so a freshly deployed allowlist change (or the
    initial rollout) takes effect without each user having to log in
    again. Returns the number of rows changed.
    """
    changed = 0
    for user in db.scalars(select(User)).all():
        if sync_user_role(db, user):
            changed += 1
    if changed:
        db.commit()
    return changed
