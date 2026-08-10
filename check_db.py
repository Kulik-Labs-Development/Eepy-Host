import sys
import os

# Add backend directory to path so we can import database.py
sys.path.append(os.path.join(os.getcwd(), "backend"))

from database import engine, User
from sqlalchemy.orm import Session

def check_max():
    try:
        with Session(engine) as session:
            user = session.query(User).filter(User.username == '[ROTATED_SUPERUSER_USERNAME]').first()
            if user:
                print("--- USER DATA FOUND ---")
                print(f"Username: {user.username}")
                print(f"Role: {user.role}")
                print(f"Full Name: {user.full_name}")
                print("----------------------")
            else:
                print("User [ROTATED_SUPERUSER_USERNAME] not found in database.")
    except Exception as e:
        print(f"Error checking database: {e}")

if __name__ == "__main__":
    check_max()
