from ui.auth import _create_remember_token, _validate_remember_token


def test_remember_token_is_valid_for_configured_period(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    token = _create_remember_token("admin", "strong-password", now=1_000)

    assert _validate_remember_token(
        token, "admin", "strong-password", now=1_001
    )


def test_remember_token_rejects_tampering(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    token = _create_remember_token("admin", "strong-password", now=1_000)
    body, signature = token.split(".", 1)
    tampered = f"{body}.{signature[:-1]}A"

    assert not _validate_remember_token(
        tampered, "admin", "strong-password", now=1_001
    )


def test_remember_token_expires_after_thirty_days(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "test-secret")
    token = _create_remember_token("admin", "strong-password", now=1_000)

    assert not _validate_remember_token(
        token, "admin", "strong-password", now=1_000 + (30 * 24 * 60 * 60)
    )


def test_remember_token_is_invalidated_when_secret_changes(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "first-secret")
    token = _create_remember_token("admin", "strong-password", now=1_000)
    monkeypatch.setenv("AUTH_SECRET", "second-secret")

    assert not _validate_remember_token(
        token, "admin", "strong-password", now=1_001
    )
