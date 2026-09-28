"""Create the first platform owner on an installation that has none.

    python -m app.bootstrap_owner owner@example.com

Production closes public signup, and platform staff are invited by an existing
platform owner. That leaves one situation with no way in: an installation with
no platform owner at all. A fresh database is the obvious case, and not a
hypothetical one — a free-tier database that expires, or a restore into a new
instance, both start empty.

This is the way in, and it is deliberately narrow:

**It only ever bootstraps.** It refuses to run if any platform owner or admin
already exists. It cannot be used to add a second owner, or to regain access to
a platform someone else controls; those go through the platform console, where
they are visible.

**It never handles a password.** It issues a single-use invitation and prints
the link. The person it is for opens it and sets their own password, so nothing
secret passes through a shell history, a CI log or a deploy console. The link
expires in 24 hours rather than the web console's seven days, because it
carries the keys to everything.

**It needs shell access to the database's host**, which is the point: whoever
can run this can already read the database directly.

The invitation is recorded as issued by the system account, which exists in
every installation, because there is no person to name — that is what it means
to be the first.
"""
from __future__ import annotations

import argparse
import logging
import secrets
import sys
from datetime import UTC, datetime, timedelta

from pydantic import EmailStr, TypeAdapter, ValidationError

from app.database import Base, SessionLocal, apply_column_patches, engine
from app.deps import SYSTEM_USER_EMAIL
from app.migrations import run_migrations
from app.models import User
from app.models.user import PlatformInvitation
from app.security import token_fingerprint

logger = logging.getLogger("payroll.bootstrap")

#: Shorter than the console's seven days. This one carries the owner role.
EXPIRES_AFTER = timedelta(hours=24)


class RefuseToBootstrap(Exception):
    """The installation is not in a state this command is allowed to change."""


def issue(email: str) -> str:
    """Issue the first owner's invitation and return the raw token.

    Raises ``RefuseToBootstrap`` rather than doing anything partial.
    """
    try:
        email = str(TypeAdapter(EmailStr).validate_python(email)).lower().strip()
    except ValidationError as exc:
        raise RefuseToBootstrap(f"{email!r} is not an email address") from exc
    if email == SYSTEM_USER_EMAIL:
        raise RefuseToBootstrap("that address is reserved for the system account")

    Base.metadata.create_all(bind=engine)
    apply_column_patches()
    run_migrations(engine)

    db = SessionLocal()
    try:
        staff = (
            db.query(User)
            .filter(User.platform_role.in_(("owner", "admin")))
            .order_by(User.created_at)
            .first()
        )
        if staff is not None:
            raise RefuseToBootstrap(
                "this installation already has platform staff "
                f"({staff.email}, {staff.platform_role}). Invite further staff from the "
                "platform console, where it is recorded — this command only ever creates "
                "the first."
            )
        if db.query(User).filter(User.email == email).first() is not None:
            raise RefuseToBootstrap(
                f"{email} already has an account. The first owner must be a new account, "
                "so that a client login cannot be quietly turned into platform access."
            )

        # The system account is the inviter of record; make sure it exists on a
        # database the API has never booted against.
        from app.main import _ensure_system_user

        _ensure_system_user(db)
        system = db.query(User).filter(User.email == SYSTEM_USER_EMAIL).one()

        # Retire anything outstanding for this address, as the console does.
        now = datetime.now(UTC)
        db.query(PlatformInvitation).filter(
            PlatformInvitation.email == email, PlatformInvitation.used_at.is_(None)
        ).update({"used_at": now})

        token = secrets.token_urlsafe(32)
        db.add(PlatformInvitation(
            email=email,
            role="owner",
            token_hash=token_fingerprint(token),
            invited_by_user_id=system.id,
            expires_at=now + EXPIRES_AFTER,
        ))
        db.commit()
        logger.warning("issued the first platform owner invitation for %s", email)
        return token
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.bootstrap_owner",
        description="Create the first platform owner on an installation that has none.",
    )
    parser.add_argument("email", help="the address the first owner will sign in with")
    parser.add_argument(
        "--site",
        default="https://www.peopleopslab.in",
        help="the site's public address, used to print a clickable link",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        token = issue(args.email)
    except RefuseToBootstrap as exc:
        print(f"Refused: {exc}", file=sys.stderr)
        return 2

    link = f"{args.site.rstrip('/')}/platform/join?token={token}"
    print(
        "\nThe first platform owner has been invited.\n\n"
        f"  {link}\n\n"
        "Open it within 24 hours and set a password. It works once.\n"
        "This link is the only copy of the token — it is not stored, only its hash.\n"
        "Treat it like a password until it has been used.\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
