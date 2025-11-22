from cryptography.fernet import Fernet
from pathlib import Path
from dca_service.config import settings

def _generate_and_save_key() -> str:
    """
    Generates a new Fernet key and saves it to .env file.
    Returns the generated key.
    """
    key = Fernet.generate_key().decode()
    
    # Use current working directory (same as config.py does)
    env_file = Path(".env")
    
    # Read existing .env content if it exists
    existing_content = ""
    if env_file.exists():
        existing_content = env_file.read_text()
    
    # Check if BINANCE_CRED_ENC_KEY already exists in .env
    if "BINANCE_CRED_ENC_KEY" in existing_content:
        # Update existing line
        lines = existing_content.splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith("BINANCE_CRED_ENC_KEY"):
                lines[i] = f"BINANCE_CRED_ENC_KEY={key}"
                updated = True
                break
        if updated:
            env_file.write_text("\n".join(lines) + "\n")
        else:
            env_file.write_text(existing_content + f"\nBINANCE_CRED_ENC_KEY={key}\n")
    else:
        # Append new line
        env_file.write_text(existing_content + ("" if not existing_content or existing_content.endswith("\n") else "\n") + f"BINANCE_CRED_ENC_KEY={key}\n")
    
    return key

def get_fernet() -> Fernet:
    """
    Returns a Fernet instance using the configured encryption key.
    Automatically generates and saves a key to .env if not set.
    Raises ValueError if the key is invalid.
    """
    key = settings.BINANCE_CRED_ENC_KEY
    if not key:
        # Auto-generate and save key on first use
        key = _generate_and_save_key()
        # Reload settings to get the new key
        from dca_service.config import Settings
        settings.BINANCE_CRED_ENC_KEY = key
    
    try:
        return Fernet(key.encode())
    except Exception as e:
        raise ValueError(f"Invalid BINANCE_CRED_ENC_KEY: {e}")

def encrypt_text(text: str) -> str:
    """
    Encrypts a plain text string.
    """
    f = get_fernet()
    return f.encrypt(text.encode()).decode()

def decrypt_text(encrypted_text: str) -> str:
    """
    Decrypts an encrypted string.
    """
    f = get_fernet()
    return f.decrypt(encrypted_text.encode()).decode()
