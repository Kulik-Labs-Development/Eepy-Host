from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from typing import List

from .database import engine, Base, get_db, User, UserRole
from .auth import get_password_hash, verify_password, create_access_token

# Initialize Database
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Eepy Host API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "online", "message": "Welcome to Eepy Host API. Stay cozy."}

@app.post("/auth/signup")
def signup(user_data: dict, db: Session = Depends(get_db)):
    # Simple validation for prototype
    username = user_data.get("username")
    email = user_data.get("email")
    password = user_data.get("password")
    role = user_data.get("role", UserRole.USER)

    if not username or not email or not password:
        raise HTTPException(status_code=400, detail="Missing required fields")

    # Check if user exists
    existing_user = db.query(User).filter((User.username == username) | (User.email == email)).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username or email already registered")

    new_user = User(
        username=username,
        email=email,
        hashed_password=get_password_hash(password),
        role=UserRole(role)
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return {"message": "Account created successfully", "user_id": new_user.id}

@app.post("/auth/login")
def login(credentials: dict, db: Session = Depends(get_db)):
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

@app.get("/health")
async def health():
    return {"status": "healthy"}
