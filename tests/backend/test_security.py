from backend.app.core.security import hash_password, verify_password


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    password = "example-only-strong-password"

    password_hash = hash_password(password)

    assert password_hash != password
    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")
    assert verify_password(password, password_hash)
    assert not verify_password("incorrect-password", password_hash)
