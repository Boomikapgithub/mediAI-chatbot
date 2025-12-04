import hashlib
from sqlalchemy.orm import Session
from models import User


# -------------------------------
# Password Utility Functions
# -------------------------------
def hash_password(password: str) -> str:
    """Hash password using SHA256 (no length restrictions)."""
    if not isinstance(password, str):
        password = str(password)
    password = password.strip()
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify SHA256 password."""
    plain_password = plain_password.strip()
    return hash_password(plain_password) == hashed_password


# -------------------------------
# Register User
# -------------------------------
def register_user(db: Session, email: str, password: str):
    """Register a new user."""
    email = email.strip().lower()
    password = password.strip()

    existing_user = db.query(User).filter(User.email == email).first()
    if existing_user:
        raise ValueError("Email already registered. Please log in.")

    hashed = hash_password(password)
    new_user = User(email=email, hashed_password=hashed)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


# -------------------------------
# Login User
# -------------------------------
def login_user(db: Session, email: str, password: str):
    """Validate user login credentials."""
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.hashed_password):
        return None
    return user


# -------------------------------
# Get Current User
# -------------------------------
def get_current_user(db: Session, email: str):
    """Fetch a user by email."""
    return db.query(User).filter(User.email == email.strip().lower()).first()


# -------------------------------
# Logout User (optional)
# -------------------------------
def logout_user():
    """Stub function for session logout."""
    return True
