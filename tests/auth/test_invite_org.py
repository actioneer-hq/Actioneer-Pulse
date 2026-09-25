"""LOW-2: the org an invite is accepted in comes from the signed token, not the client cookie."""

from __future__ import annotations

from voiceobs.auth import decode_invite, decode_invite_org, encode_invite


def test_invite_binds_org_into_token():
    tok = encode_invite("u1", "acme")
    assert decode_invite(tok) == "u1"
    assert decode_invite_org(tok) == "acme"


def test_legacy_invite_without_org_defaults():
    # a token minted without an org (old flow) resolves to the default schema, not an error
    from voiceobs.auth import jwt as vjwt
    tok = vjwt._encode({"sub": "u1"}, vjwt.INVITE_TTL, "invite")
    assert decode_invite_org(tok) == "default"


def test_tampered_invite_rejected():
    assert decode_invite_org("not.a.token") is None
