import pytest

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_round_trip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_password_length_limit_is_explicit():
    with pytest.raises(ValueError):
        hash_password("x" * 73)


def test_token_round_trip():
    token = create_access_token("user-123", {"role": "admin"})
    claims = decode_access_token(token)
    assert claims["sub"] == "user-123"
    assert claims["role"] == "admin"
    assert claims["iss"] == "csap"


def test_tampered_token_is_rejected():
    import jwt

    token = create_access_token("user-123")
    with pytest.raises(jwt.PyJWTError):
        decode_access_token(token[:-4] + "abcd")
