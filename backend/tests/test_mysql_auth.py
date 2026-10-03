"""Exercise the full password exchange used after MySQL restarts."""

from asyncmy.auth import sha2_rsa_encrypt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa


def test_mysql_full_password_authentication() -> None:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    password = b"test-password"
    salt = b"01234567890123456789"

    encrypted = sha2_rsa_encrypt(password, salt, public_key)
    decrypted = private_key.decrypt(
        encrypted,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA1()),
            algorithm=hashes.SHA1(),
            label=None,
        ),
    )
    recovered = bytes(value ^ salt[index % len(salt)] for index, value in enumerate(decrypted))
    assert recovered == password + b"\0"
