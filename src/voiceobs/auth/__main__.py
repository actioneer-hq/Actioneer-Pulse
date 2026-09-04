"""Headless bootstrap for self-host: create the first owner + org when the DB is empty.

    python -m voiceobs.auth bootstrap --email you@co.com --password '...' [--org "My Co"]

Or set VOICEOBS_BOOTSTRAP_EMAIL / VOICEOBS_BOOTSTRAP_PASSWORD and run `bootstrap` with no
flags. No-ops (exit 0) if any user already exists, so it is safe to run on every deploy.
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import func, select

from voiceobs.auth.password import hash_password, normalize_email
from voiceobs.db.models import AppUser, Membership, Organization
from voiceobs.db.session import get_session


def _slug(name: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "org"


def bootstrap(email: str, password: str, org_name: str) -> int:
    email = normalize_email(email)
    if not email or not password:
        print("error: email and password are required", file=sys.stderr)
        return 2
    gen = get_session()
    db = next(gen)
    try:
        if db.scalar(select(func.count()).select_from(AppUser)):
            print("users already exist — nothing to bootstrap.")
            return 0
        user = AppUser(email=email, password_hash=hash_password(password), is_active=True)
        db.add(user)
        db.flush()
        org = Organization(name=org_name or "Default", slug=_slug(org_name or "default"))
        db.add(org)
        db.flush()
        db.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
        db.commit()
        print(f"bootstrapped owner {email} + org {org.name!r} ({org.id})")
        return 0
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m voiceobs.auth")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap", help="create the first owner + org when the DB is empty")
    b.add_argument("--email", default=os.getenv("VOICEOBS_BOOTSTRAP_EMAIL", ""))
    b.add_argument("--password", default=os.getenv("VOICEOBS_BOOTSTRAP_PASSWORD", ""))
    b.add_argument("--org", default=os.getenv("VOICEOBS_BOOTSTRAP_ORG", "Default"))
    args = parser.parse_args(argv)
    if args.cmd == "bootstrap":
        return bootstrap(args.email, args.password, args.org)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
