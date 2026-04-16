import sqlite3
import hashlib
import random
from flask import Flask, request, jsonify

app = Flask(__name__)
DATABASE_FILE = 'my_database.db'

# --- DATABASE HELPER FUNCTIONS ---

def get_db_connection():
    """Connects to the SQLite database and returns the connection."""
    conn = sqlite3.connect(DATABASE_FILE)
    # This allows us to access columns by name (e.g., user['Email'])
    conn.row_factory = sqlite3.Row 
    return conn

def init_db():
    """Initializes the database and creates the userdata table if it doesn't exist."""
    conn = get_db_connection()
    conn.execute("""
    CREATE TABLE IF NOT EXISTS userdata (
         id INTEGER PRIMARY KEY AUTOINCREMENT,
         Username VARCHAR(255) UNIQUE NOT NULL,
         Email VARCHAR(255) UNIQUE NOT NULL,
         Password VARCHAR(255) NOT NULL,
         Role VARCHAR(50) NOT NULL,
         VerificationCode VARCHAR(6),
         IsVerified INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()
    print("Database initialized successfully.")

# --- API ROUTES ---

@app.route('/signup', methods=['POST'])
def signup():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role', 'User') # Default to 'User'
    
    if not username or not email or not password:
        return jsonify({"message": "Username, email, and password are required"}), 400
    
    if len(password) < 6:
        return jsonify({"message": "Password must be at least 6 characters long"}), 400
    
    v_code = str(random.randint(100000, 999999))
    hashed_pw = hashlib.sha256(password.encode()).hexdigest()

    conn = get_db_connection()
    try:
        conn.execute("""INSERT INTO userdata (Username, Email, Password, Role, VerificationCode, IsVerified) 
                        VALUES (?, ?, ?, ?, ?, 0)""", 
                     (username, email, hashed_pw, role, v_code))
        conn.commit()
        conn.close()
        
        # In a real app, send the email here. For now, we print to console.
        print(f"DEBUG: Verification code for {email} is: {v_code}")
        
        return jsonify({"message": "Signup successful. Please verify your email."}), 201
    except sqlite3.IntegrityError:
        return jsonify({"message": "Username or Email already exists"}), 400

@app.route('/verify', methods=['POST'])
def verify_email():
    data = request.get_json()
    email = data.get('email')
    user_code = data.get('code')

    if not email or not user_code:
        return jsonify({"message": "Email and verification code are required"}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM userdata WHERE Email = ?", (email,)).fetchone()

    if user and user['VerificationCode'] == user_code:
        conn.execute("UPDATE userdata SET IsVerified = 1, VerificationCode = NULL WHERE Email = ?", (email,))
        conn.commit()
        conn.close()
        return jsonify({"message": "Email verified! You can now login."}), 200
    else:
        conn.close()
        return jsonify({"message": "Invalid verification code"}), 400

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"message": "Username and password are required"}), 400

    conn = get_db_connection()
    # Check if user exists by username
    user = conn.execute("SELECT * FROM userdata WHERE Username = ?", (username,)).fetchone()
    conn.close()

    if not user:
        return jsonify({"message": "User not found"}), 404
    
    # Security check: Is the email verified?
    if user['IsVerified'] == 0:
        return jsonify({"message": "Please verify your email before logging in."}), 403
    
    # Password check
    hashed_input = hashlib.sha256(password.encode()).hexdigest()
    if hashed_input == user['Password']:
        return jsonify({
            "message": "Login successful",
            "username": user['Username'],
            "role": user['Role']
        }), 200
    else:
        return jsonify({"message": "Incorrect password"}), 401

if __name__ == '__main__':
    # Initialize the database table before starting the server
    init_db()
    # Run the server
    app.run(host='0.0.0.0', port=5000, debug=True)