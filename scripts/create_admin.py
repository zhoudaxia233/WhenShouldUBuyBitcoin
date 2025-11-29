#!/usr/bin/env python3
"""
Create an admin user for the DCA Service.

Usage:
    poetry run python scripts/create_admin.py

This script will prompt for email and password, then create an admin user.
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from getpass import getpass
from sqlmodel import Session, select
from dca_service.database import engine
from dca_service.models import User
from dca_service.auth.password import hash_password


def create_admin():
    """Interactively create an admin user."""
    print("=" * 50)
    print("DCA Service - Create Admin User")
    print("=" * 50)
    print()
    
    # Get email
    email = input("Email: ").strip()
    if not email or "@" not in email:
        print("Error: Invalid email address")
        return
    
    # Get password
    password = getpass("Password: ")
    password_confirm = getpass("Confirm Password: ")
    
    if password != password_confirm:
        print("Error: Passwords do not match")
        return
    
    # Validate password length (bcrypt has a 72-byte maximum)
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        print("Error: Password is too long (max 72 bytes)")
        print(f"Your password is {len(password_bytes)} bytes")
        print("Tip: Use a shorter password or a passphrase with fewer special characters")
        return
    
    if len(password) < 12:
        print("Error: Password must be at least 12 characters (recommended security practice)")
        return
    
    # Check if user already exists
    with Session(engine) as session:
        statement = select(User).where(User.email == email)
        existing_user = session.exec(statement).first()
        
        if existing_user:
            print(f"Error: User with email '{email}' already exists")
            return
        
        # Create user
        user = User(
            email=email,
            password_hash=hash_password(password),
            is_active=True,
            is_admin=True
        )
        
        session.add(user)
        session.commit()
        session.refresh(user)
        
        print()
        print("✓ Admin user created successfully!")
        print(f"  Email: {user.email}")
        print(f"  ID: {user.id}")
        print(f"  Admin: {user.is_admin}")
        print()


if __name__ == "__main__":
    try:
        create_admin()
    except KeyboardInterrupt:
        print("\n\nAborted.")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
