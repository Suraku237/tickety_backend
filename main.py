from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import database # Import our database.py

app = FastAPI()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Dependency to get DB session
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(username: str, email: str, password: str, db: Session = Depends(get_db)):
    # Check if user exists
    existing_user = db.query(database.User).filter(database.User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Hash password and save
    hashed_pw = pwd_context.hash(password)
    new_user = database.User(username=username, email=email, hashed_password=hashed_pw)
    db.add(new_user)
    db.commit()
    return {"message": "User created successfully"}

@app.post("/login")
def login(username: str, password: str, db: Session = Depends(get_db)):
    user = db.query(database.User).filter(database.User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    return {"message": "Login successful", "username": user.username}