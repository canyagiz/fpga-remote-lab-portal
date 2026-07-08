import secrets

import bcrypt


def hash_password(plain_password: str) -> str:
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_two_factor_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if not domain:
        return email
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}***@{domain}"
