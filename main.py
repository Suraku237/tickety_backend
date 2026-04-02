from fastapi import FastAPI, Depends, HTTPException, status, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import database 

app = FastAPI()

# 1. ADD CORS MIDDLEWARE
# This allows your Flutter app (from any IP) to talk to this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 2. USE 'Form' FOR INPUTS
# This matches 'body: { ... }' in your Flutter http.post request
@app.post("/signup", status_code=status.HTTP_201_CREATED)
def signup(
    username: str = Form(...), 
    email: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    # Check if user exists
    existing_user = db.query(database.User).filter(database.User.username == username).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Hash password and save
    hashed_pw = pwd_context.hash(password)
    new_user = database.User(username=username, email=email, hashed_password=hashed_pw)
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return {"message": "User created successfully", "id": new_user.id}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Database error occurred")

@app.post("/login")
def login(
    username: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(database.User).filter(database.User.username == username).first()
    
    if not user or not pwd_context.verify(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="Invalid username or password"
        )
    
    return {
        "status": "success",
        "message": "Login successful", 
        "user": {
            "username": user.username,
            "email": user.email
        }
    }