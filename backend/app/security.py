import hashlib
import secrets

import bcrypt

# Agent tokens look like "frl_<shuttle_id>_<secret>". Embedding the id
# keeps verification a single indexed lookup instead of hashing the
# candidate against every shuttle row in turn; the id is not a secret
# and leaks nothing on its own.
_SHUTTLE_TOKEN_PREFIX = "frl"


def hash_password(plain_password: str) -> str:
    hashed = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_two_factor_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_shuttle_secret(secret: str) -> str:
    """SHA-256, not bcrypt.

    The secret is 256 bits of CSPRNG output, so there is no dictionary
    for a slow hash to defend against, and this runs on every report
    from every shuttle - bcrypt's deliberate cost would be pure waste
    here. This is the standard treatment for API tokens, and differs
    from user passwords for exactly that reason.
    """
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def generate_shuttle_token(shuttle_id: int) -> tuple[str, str]:
    """Mint a token for a shuttle.

    Returns (token, token_hash). The plaintext token is shown to the
    admin once at enrolment and never stored - only the hash is kept, so
    a database read cannot yield a working credential.
    """
    secret = secrets.token_urlsafe(32)
    return f"{_SHUTTLE_TOKEN_PREFIX}_{shuttle_id}_{secret}", hash_shuttle_secret(secret)


def parse_shuttle_token(token: str) -> tuple[int, str] | None:
    """Split a token into (shuttle_id, secret), or None if malformed."""
    parts = token.split("_", 2)
    if len(parts) != 3 or parts[0] != _SHUTTLE_TOKEN_PREFIX:
        return None
    try:
        shuttle_id = int(parts[1])
    except ValueError:
        return None
    if not parts[2]:
        return None
    return shuttle_id, parts[2]


def verify_shuttle_secret(secret: str, token_hash: str) -> bool:
    # compare_digest, not ==: a plain comparison leaks how many leading
    # characters matched through its timing.
    return secrets.compare_digest(hash_shuttle_secret(secret), token_hash)


def mask_email(email: str) -> str:
    name, _, domain = email.partition("@")
    if not domain:
        return email
    visible = name[:2] if len(name) > 2 else name[:1]
    return f"{visible}***@{domain}"
