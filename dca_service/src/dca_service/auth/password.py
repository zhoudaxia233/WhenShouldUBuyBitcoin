"""
Password hashing and verification using bcrypt directly.

Security notes:
- Uses bcrypt for password hashing (industry standard)
- Bcrypt includes automatic salting (no manual salt management needed)
- Never store or log plaintext passwords
- Hashes are one-way: cannot recover original password
- bcrypt has a 72-byte maximum password length

Why direct bcrypt instead of passlib:
- passlib is unmaintained (last release 2020)
- passlib 1.7.4 incompatible with bcrypt 5.0+
- Direct bcrypt usage is simpler and more maintainable
"""
import bcrypt


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using bcrypt.
    
    Note: bcrypt has a maximum password length of 72 bytes.
    Passwords longer than this will raise a ValueError.
    
    Args:
        plain_password: The plaintext password to hash
        
    Returns:
        Bcrypt hashed password string (includes salt)
        
    Raises:
        ValueError: If password is longer than 72 bytes
        
    Example:
        >>> hashed = hash_password("my_secure_password")
        >>> print(hashed)
        $2b$12$...
    """
    # Validate password length (bcrypt maximum is 72 bytes)
    password_bytes = plain_password.encode('utf-8')
    if len(password_bytes) > 72:
        raise ValueError(
            f"Password is too long ({len(password_bytes)} bytes). "
            f"Maximum is 72 bytes. Use a shorter password."
        )
    
    # Hash the password with automatic salt generation
    # Cost factor of 12 is a good balance of security and performance
    hashed = bcrypt.hashpw(password_bytes, bcrypt.gensalt(rounds=12))
    return hashed.decode('utf-8')


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verify a plaintext password against a bcrypt hash.
    
    Args:
        plain_password: The plaintext password to verify
        password_hash: The bcrypt hash to verify against
        
    Returns:
        True if password matches, False otherwise
        
    Example:
        >>> hashed = hash_password("my_secure_password")
        >>> verify_password("my_secure_password", hashed)
        True
        >>> verify_password("wrong_password", hashed)
        False
    """
    try:
        password_bytes = plain_password.encode('utf-8')
        hash_bytes = password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, hash_bytes)
    except Exception:
        # If verification fails for any reason, return False
        return False

