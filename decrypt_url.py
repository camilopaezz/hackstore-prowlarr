# /// script
# requires-python = ">=3.10"
# dependencies = ["cryptography"]
# ///

import base64
import hashlib

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


def evp_bytes_to_key(password, salt, key_len=32, iv_len=16):
    """OpenSSL's EVP_BytesToKey with MD5 hash"""
    dtot = b""
    d = b""
    while len(dtot) < key_len + iv_len:
        d = hashlib.md5(d + password + salt).digest()
        dtot += d
    return dtot[:key_len], dtot[key_len : key_len + iv_len]


def _strip_pkcs7_padding(data, block_size=16):
    if not data or len(data) % block_size != 0:
        raise ValueError("Invalid padded plaintext length")

    pad_len = data[-1]
    if pad_len < 1 or pad_len > block_size:
        raise ValueError("Invalid PKCS#7 padding length")
    if data[-pad_len:] != bytes([pad_len]) * pad_len:
        raise ValueError("Invalid PKCS#7 padding bytes")

    return data[:-pad_len]


def decrypt_acortalink(encoded):
    try:
        # First base64 decode
        decoded = base64.b64decode(encoded, validate=True)
        # The result is another base64 string; convert to string first
        inner_b64 = decoded.decode("ascii")
        # Second base64 decode to get the actual encrypted data
        raw = base64.b64decode(inner_b64, validate=True)
    except Exception as exc:
        raise ValueError("Invalid acortalink payload") from exc

    if raw[:8] != b"Salted__":
        raise ValueError(
            f"Not a valid OpenSSL salted encrypted data, got: {raw[:20]!r}"
        )

    salt = raw[8:16]
    encrypted = raw[16:]

    password = b"fee631d2cffda38a78b96ee6d2dfb43a"
    key, iv = evp_bytes_to_key(password, salt, key_len=32, iv_len=16)

    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted) + decryptor.finalize()

    decrypted = _strip_pkcs7_padding(decrypted)

    return decrypted.decode("utf-8")


if __name__ == "__main__":
    import sys

    encoded = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "VTJGc2RHVmtYMSsveGNVSFRONlQ1eGhmYldpWHptd3ZhUnBYaStIN2V5ZGhKeElUVDZCRXpzYnpNbEdOUXhKbm03UnZFOVQzaFpvS3dGTFBhNXM2STBsS0lJRTR6RGhWT2VWcmxHREdPL2xsdm9hLzdTa0kxeGtmQVdDV29xS2l0Y3FUM1J5eVNIemljRTJIN2xEcjNyT0ZEaVhaUXYvZzA0NFFVWFhQbzNTaGVwN3lYU3RKTURIWGJ3bk1lSk5raTZHbGIyN09Rd0Rabm9DQTNBUHRJczZwbFY4VWdZOE15d2VPTWRIN1JJcWgrc1l4bUlHTmxCeHh2Q3d6dUMzb21TZWJld1FESUR4dlBEZktpT1JkK1U4WWJYUXQ1bEo1S2h2MCtzTlQ3ak0rRTBsQjBScUZaK3RBckFlQzhiaDVqdzMxK1lmTkxacG83NVNWbzdMSW0zZk4xNXNwYnhlKzl5MzJCMGhlbFR1UWNYZndYK3RuMStmSEtnbU43RnJCZjZLMFlZUklqQm9QVXVUYlYrbjkwUG44SFNqbDY3SlZveHpIQVlvQTVqND0="  # noqa: E501
    )
    result = decrypt_acortalink(encoded)
    print(result)
