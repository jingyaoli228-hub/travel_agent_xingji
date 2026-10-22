from travel_agent.api.auth import TOKEN_TTL_SECONDS, issue_token, verify_token


def test_owner_token_is_signed_and_expires():
    now = 1_800_000_000
    token = issue_token("owner-openid", "a-long-secret-for-tests", now=now)

    assert verify_token(token, "a-long-secret-for-tests", now=now) == {
        "sub": "owner-openid", "exp": now + TOKEN_TTL_SECONDS,
    }
    assert verify_token(token, "a-different-secret", now=now) is None
    assert verify_token(token, "a-long-secret-for-tests", now=now + TOKEN_TTL_SECONDS) is None
    payload, signature = token.split(".")
    tampered = ("A" if signature[0] != "A" else "B") + signature[1:]
    assert verify_token(f"{payload}.{tampered}", "a-long-secret-for-tests", now=now) is None
