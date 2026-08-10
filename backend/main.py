from fastapi import FastAPI, Depends, HTTPException, status, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
import logging
import os
import shutil

from database import engine, Base, get_db, User, UserRole
from auth import get_password_hash, verify_password, create_access_token, decode_access_token
from schemas import UserCreate, UserLogin

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eepy-backend")

def sync_database_schema():
    """
    Ensures the database schema is up to date without wiping data.
    Adds missing columns for Phase 3 features (User profiles & analytics).
    """
    try:
        with engine.connect() as conn:
            # Check current columns in users table
            result = conn.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name='users'"))
            existing_columns = {row[0] for row in result}

            # Define required columns and their SQL types
            required_columns = {
                "full_name": "VARCHAR",
                "profile_picture": "VARCHAR",
                "total_requests": "INTEGER DEFAULT 0 NOT NULL"
            }

            for col, col_type in required_columns.items():
                if col not in existing_columns:
                    logger.info(f"Adding missing column {col} to users table...")
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {col_type}"))
            
            conn.commit()
            logger.info("Database schema synchronized successfully.")
    except Exception as e:
        logger.error(f"Schema synchronization failed: {e}")

# Initialize Database
try:
    Base.metadata.create_all(bind=engine)
    sync_database_schema()
    logger.info("Database initialized and synchronized.")
except Exception as e:
    logger.error(f"Critical error initializing database: {e}")

app = FastAPI(title="Eepy Host API")

# Ensure uploads directory exists
UPLOAD_DIR = "static/avatars"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# Mount static files to serve profile pictures
app.mount("/static", StaticFiles(directory="static"), name="static")

# Handle Validation Errors (422) globally to provide a cleaner response
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    logger.warning(f"Validation error on {request.url.path}: {exc.errors()}")
    first_error = exc.errors()[0] if exc.errors() else {"msg": "Invalid request data"}
    return JSONResponse(
        status_code=422,
        content={"detail": first_error.get("msg", "Validation failed")},
    )

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

# Dependency to get current authenticated user
async def get_current_user(request: Request, db: Session = Depends(get_db)):
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authentication token")
    
    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

async def get_superuser(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.SUPERUSER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Operation restricted to superusers only"
        )
    return current_user

@app.get("/")
async def root():
    return {"status": "online", "message": "Welcome to Eepy Host API. Stay cozy."}

@app.get("/health")
async def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}

@app.post("/auth/signup")
def signup(user_in: UserCreate, db: Session = Depends(get_db)):
    try:
        logger.info(f"Signup request received for user: {user_in.username}")
        # Check if user exists
        existing_user = db.query(User).filter((User.username == user_in.username) | (User.email == user_in.email)).first()
        if existing_user:
            raise HTTPException(status_code=400, detail="Username or email already registered")

        # Safe Enum casting
        try:
            role = UserRole(user_in.role)
        except ValueError:
            logger.warning(f"Invalid role provided: {user_in.role}. Defaulting to USER.")
            role = UserRole.USER

        # SECONDARY DEFENSE: Explicitly truncate password before passing to hash function
        safe_password = user_in.password[:72]

        new_user = User(
            username=user_in.username,
            email=user_in.email,
            hashed_password=get_password_hash(safe_password),
            role=role
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        logger.info(f"New user created: {user_in.username}")
        return {"message": "Account created successfully", "user_id": new_user.id}

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception("Unexpected error during signup")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.post("/auth/login")
def login(credentials: UserLogin, db: Session = Depends(get_db)):
    try:
        logger.info(f"Login request received for user: {credentials.username}")
        user = db.query(User).filter(User.username == credentials.username).first()
        
        # SECONDARY DEFENSE: Truncate login password as well
        if not user or not verify_password(credentials.password[:72], user.hashed_password):
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

# --- Profile Management Endpoints ---

@app.get("/user/profile")
def get_profile(current_user: User = Depends(get_current_user)):
    return {
        "full_name": current_user.full_name,
        "email": current_user.email,
        "profile_picture": current_user.profile_picture,
        "username": current_user.username
    }

@app.patch("/user/profile")
async def update_profile(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        data = await request.json()
        if "full_name" in data:
            current_user.full_name = data["full_name"]
            db.commit()
            db.refresh(current_user)
        
        return {"message": "Profile updated successfully", "full_name": current_user.full_name}
    except Exception as e:
        logger.error(f"Error updating profile: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")

@app.post("/user/avatar")
async def upload_avatar(file: UploadFile = File(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        # Validate file type
        if not file.content_type.startswith("image/"):
            raise HTTPException(status_code=400, detail="Invalid file type. Please upload an image.")

        # Save file to disk using username as filename for uniqueness and simplicity
        extension = os.path.splitext(file.filename)[1] or ".png"
        filename = f"{current_user.username}{extension}"
        file_path = os.path.join(UPLOAD_DIR, filename)

        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Update database path (relative to static folder)
        db_path = f"/static/avatars/{filename}"
        current_user.profile_picture = db_path
        db.commit()
        db.refresh(current_user)

        return {"message": "Avatar uploaded successfully", "profile_picture": db_path}
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.exception(f"Error uploading avatar for {current_user.username}")
        raise HTTPException(status_code=500, detail="Failed to upload avatar")
