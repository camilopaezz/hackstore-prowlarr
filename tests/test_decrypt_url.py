import base64

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from decrypt_url import decrypt_acortalink, evp_bytes_to_key


PASSWORD = b"fee631d2cffda38a78b96ee6d2dfb43a"


def _encrypt_acortalink(plaintext: str, salt: bytes) -> str:
    key, iv = evp_bytes_to_key(PASSWORD, salt, key_len=32, iv_len=16)
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    encryptor = cipher.encryptor()

    raw = plaintext.encode("utf-8")
    pad_len = 16 - (len(raw) % 16)
    raw += bytes([pad_len]) * pad_len

    encrypted = encryptor.update(raw) + encryptor.finalize()
    payload = b"Salted__" + salt + encrypted
    inner = base64.b64encode(payload)
    return base64.b64encode(inner).decode("ascii")


def test_evp_bytes_to_key_matches_expected_lengths():
    key, iv = evp_bytes_to_key(b"password", b"12345678")

    assert len(key) == 32
    assert len(iv) == 16


def test_decrypt_acortalink_round_trip():
    encoded = _encrypt_acortalink("magnet:?xt=urn:btih:abc123", b"12345678")

    assert decrypt_acortalink(encoded) == "magnet:?xt=urn:btih:abc123"


def test_decrypt_acortalink_rejects_invalid_payload():
    bad = base64.b64encode(base64.b64encode(b"not-salted-data")).decode("ascii")

    try:
        decrypt_acortalink(bad)
    except ValueError as exc:
        assert "Not a valid OpenSSL salted encrypted data" in str(exc)
    else:
        raise AssertionError("decrypt_acortalink() should reject invalid data")
