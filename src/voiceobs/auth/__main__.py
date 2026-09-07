"""Headless bootstrap for self-host: create the first owner + org when the DB is empty.

    python -m voiceobs.auth bootstrap --email you@co.com --password '...' [--org "My Co"]

Or set VOICEOBS_BOOTSTRAP_EMAIL / VOICEOBS_BOOTSTRAP_PASSWORD and run `bootstrap` with no
flags. No-ops (exit 0) if any user already exists, so it is safe to run on every deploy.
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from voiceobs.auth.env import DEV_EMAIL, DEV_PASSWORD, dev_open
from voiceobs.auth.password import hash_password, normalize_email
from voiceobs.config import get_config
from voiceobs.db.models import AppUser, Membership
from voiceobs.db.provision import provision_org
from voiceobs.db.session import DEFAULT_ORG, get_session


def bootstrap(email: str, password: str, org_name: str) -> int:
    # Under dev-open, fall back to the seeded dev account so `python -m voiceobs.auth
    # bootstrap` with no flags always produces the account the login page prefills. A real
    # deployment (dev_open() false) still requires explicit credentials.
    if dev_open():
        email = email or DEV_EMAIL
        password = password or DEV_PASSWORD
    email = normalize_email(email)
    if not email or not password:
        print("error: email and password are required", file=sys.stderr)
        return 2
    gen = get_session()
    db = next(gen)
    try:
        # Provision (or adopt) the default org's schema, then bootstrap the first owner inside it.
        org = provision_org(db, DEFAULT_ORG, org_name or "Default")
        if db.scalar(select(func.count()).select_from(AppUser)):
            print("users already exist — nothing to bootstrap.")
            return 0
        if org_name:
            org.name = org_name
        user = AppUser(email=email, password_hash=hash_password(password), is_active=True)
        db.add(user)
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
    s = get_config()
    b = sub.add_parser("bootstrap", help="create the first owner + org when the DB is empty")
    b.add_argument("--email", default=s.bootstrap_email)
    b.add_argument("--password", default=s.bootstrap_password)
    b.add_argument("--org", default=s.bootstrap_org)
    args = parser.parse_args(argv)
    if args.cmd == "bootstrap":
        return bootstrap(args.email, args.password, args.org)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
