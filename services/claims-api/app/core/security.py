import bcrypt

MAX_PASSWORD_BYTES = 72


def hash_password(plain: str) -> str:
    _reject_oversized(plain)
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _reject_oversized(plain: str) -> None:
    if len(plain.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password exceeds {MAX_PASSWORD_BYTES} bytes")
