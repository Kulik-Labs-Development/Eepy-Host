from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List
import logging

from database import engine, Base, get_db, User, UserRole
from .auth import get_password_hash, verify_password, create_access_token

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eepy-backend")

# Initialize Database
try:
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully.")
except Exception as e:
    logger.error(f"Critical error creating database tables: {e}")

app = FastAPI(title="Eepy Host API")

# Explicit CORS Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://dev.eepy.host",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "online", "message": "Welcome to Eepy Host API. Stay cozy."}

@app.get("/health")
async def health():
    try:
        # Simple DB check
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

@app.post("/auth/signup")
def signup(user_data: dict, db: Session = Depends(get_db)):
    try:
        username = user_data.get("username")
        email = user_data.get("email")
        password = user_data.get("password")
        role_input = user_data.get("role", "user")

        if not username or not email or not password:
            raise HTTPException(status_code=400, detail="Missing required fields")

        # Check if user exists
        existing_user = db.query(User).filter((User.username == username) | (User.email == email)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username or email already registered")

        # Safe Enum casting
        try:
            role = UserRole(role_input)
        except ValueError:
            logger.warning(f"Invalid role provided: {role_input}. Defaulting to USER.")
            role = UserRole.USER

        new_user = User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            role=role
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"New user created: {username}")
        return {"message": "Account created successfully", "user_id": new_user.id}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Unexpected error during signup")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/auth/login")
def login(credentials: dict, db: Session = Depends(get_db)):
    try:
        username = credentials.get("username")
        password = credentials.get("password")

        user = db.query(User).filter(User.username == username).first()
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")

        token = create_access_token({"sub": user.username, "role": user.role})
        return {
            "access_token": token,
            "token_type": "bearer",
            "user": {
                "username": user.username,
                "role": user.role,
                "email": user.email
            }
        }
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Unexpected error during login")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")
