from app.core.crypto import decrypt, encrypt


def test_credentials_round_trip():
    secret = "Fmc-Api-P@ssw0rd"
    ciphertext = encrypt(secret)
    assert ciphertext != secret
    assert decrypt(ciphertext) == secret


def test_ciphertext_is_non_deterministic():
    assert encrypt("same") != encrypt("same")
