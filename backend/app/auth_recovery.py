"""Regain sign-in for one account, from a shell on the API's host.

    python -m app.auth_recovery unlock  someone@example.com
    python -m app.auth_recovery reset-mfa someone@example.com --reason "lost phone, verified by call"
    python -m app.auth_recovery end-sessions someone@example.com --reason "laptop stolen"

The web console cannot remove anyone's two-step sign-in: a stolen owner
session that could strip other people's second factor would make the second
factor decorative. This is the one path, and it is deliberately narrow.

**It needs shell access to the database's host.** Whoever can run it can
already read the database directly, so it grants nothing new.

**It never handles a password, code or token.** ``reset-mfa`` removes the
second factor and ends every session; the person then signs in with their
password and enrols again. ``unlock`` lifts a sign-in lock early (they expire
on their own after ``LOGIN_LOCKOUT_MINUTES``).

**Every use is written to the security event log**, with the reason, and a
reason is required for anything beyond an unlock. Confirm who is asking by a
channel other than the one the request arrived on before running it.
"""
from __future__ import annotations

import argparse
import sys

from app.database import Base, SessionLocal, apply_column_patches, engine
from app.migrations import run_migrations
from app.models import User
from app.services import auth_security


def _user(db, email: str) -> User:
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if user is None or user.role in ("system", "machine"):
        raise SystemExit(f"No person signs in as {email}")
    return user


def run(action: str, email: str, reason: str | None) -> str:
    Base.metadata.create_all(bind=engine)
    apply_column_patches()
    run_migrations(engine)
    db = SessionLocal()
    try:
        detail = {"via": "app.auth_recovery", "reason": reason or ""}
        if action == "unlock":
            lifted = auth_security.unlock(db, email)
            auth_security.event(db, None, kind="unlock", outcome="changed", subject=email,
                                detail={**detail, "locks_lifted": lifted})
            db.commit()
            return f"Lifted {lifted} lock(s) on {email}."
        if not reason or len(reason.strip()) < 8:
            raise SystemExit("--reason is required (at least 8 characters): it is kept in the security log.")
        user = _user(db, email)
        if action == "reset-mfa":
            had = auth_security.mfa_enabled(user)
            user.mfa_secret_enc = None
            user.mfa_enabled_at = None
            user.mfa_recovery_hashes = None
            user.mfa_last_step = None
            auth_security.event(db, None, kind="mfa_disabled", outcome="changed", user=user,
                                detail={**detail, "by": "operator", "was_enabled": had})
            auth_security.end_all_sessions(db, None, user, reason="mfa_reset_by_operator")
            db.commit()
            return (f"Two-step sign-in removed for {user.email} and every session ended. "
                    "They sign in with their password and enrol again.")
        if action == "end-sessions":
            auth_security.end_all_sessions(db, None, user, reason=f"operator: {reason.strip()}")
            db.commit()
            return f"Every session of {user.email} has ended."
        raise SystemExit(f"Unknown action {action}")
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("action", choices=("unlock", "reset-mfa", "end-sessions"))
    parser.add_argument("email")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    print(run(args.action, args.email, args.reason))
    return 0


if __name__ == "__main__":
    sys.exit(main())
