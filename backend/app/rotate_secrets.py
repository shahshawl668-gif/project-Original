"""Re-seal every stored secret under the first key in STUDIO_SECRET_KEY.

    python -m app.rotate_secrets            # count what would change
    python -m app.rotate_secrets --apply    # do it

Rotating the application secrets key is three steps, and the service stays up
through all of them:

1. Set ``STUDIO_SECRET_KEY=new,old`` and redeploy. New secrets are sealed with
   ``new``; everything already stored still opens with ``old``.
2. Run this with ``--apply``. Every stored secret is re-sealed with ``new``.
3. Set ``STUDIO_SECRET_KEY=new`` and redeploy.

Skipping step 2 and dropping the old key makes every connection credential,
webhook secret and **two-step sign-in secret** unreadable — the connections
must be re-entered and every enrolled person must enrol again. The run is one
transaction: it re-seals everything or nothing, and it never prints a secret.
"""
from __future__ import annotations

import argparse
import sys

from app.database import SessionLocal
from app.models import StudioConnection, StudioInboundEndpoint, StudioOAuthState, StudioWebhook, User
from app.services.studio import secrets as vault

#: (model, column, stored as text) — every place a sealed value lives.
SEALED = (
    (StudioConnection, "secret_ciphertext", False),
    (StudioOAuthState, "verifier_ciphertext", False),
    (StudioWebhook, "secret_ciphertext", False),
    (StudioInboundEndpoint, "secret_ciphertext", False),
    (User, "mfa_secret_enc", True),
)


def run(apply: bool) -> dict[str, int]:
    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        for model, column, as_text in SEALED:
            n = 0
            for row in db.query(model).filter(getattr(model, column).is_not(None)):
                value = getattr(row, column)
                token = value.encode() if as_text else bytes(value)
                resealed = vault.reencrypt(token)
                setattr(row, column, resealed.decode() if as_text else resealed)
                n += 1
            counts[f"{model.__tablename__}.{column}"] = n
        if apply:
            db.commit()
        else:
            db.rollback()
    finally:
        db.close()
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="write the re-sealed values")
    args = parser.parse_args(argv)
    counts = run(args.apply)
    for name, n in counts.items():
        print(f"{name}: {n}")
    print("Re-sealed under the first key." if args.apply else "Dry run: nothing written. Add --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
