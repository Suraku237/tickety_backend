from fastapi import FastAPI, Depends, HTTPException, status, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
import database 

app = FastAPI(title="Tickety API")

# 1. CORS Setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 2. Database Dependency
def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 3. Ensure tables are created on startup
@app.on_event("startup")
def startup():
    database.Base.metadata.create_all(bind=database.engine)

# --- ENDPOINTS ---

@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(
    username: str = Form(...), 
    email: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    # Check if username or email already exists
    user_exists = db.query(database.User).filter(
        (database.User.username == username) | (database.User.email == email)
    ).first()
    
    if user_exists:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Username or Email already registered"
        )
    
    # Secure Password Hashing
    hashed_pw = pwd_context.hash(password)
    new_user = database.User(username=username, email=email, hashed_password=hashed_pw)
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return {
            "status": "success",
            "message": "Account created successfully", 
            "user_id": new_user.id
        }
    except Exception as e:
        db.rollback()
        print(f"Database Error: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")

@app.post("/login")
def login(
    username: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    # Search for user
    user = db.query(database.User).filter(database.User.username == username).first()
    
    # Verify presence and password
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid credentials"
        )
    
    return {
        "status": "success",
        "message": "Welcome back!", 
        "user": {
            "id": user.id,
            "username": user.username,
            "email": user.email
        }
    }

@app.get("/health")
def health_check():
    return {"status": "online", "vps_ip": "109.199.120.38"}