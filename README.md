# Tickety Backend

A simple Flask-based backend for user authentication with email verification.

## Features

- User signup with email verification
- User login
- SQLite database for user storage
- Password hashing with SHA-256

## Installation

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Run the application: `python main.py`

## API Endpoints

### POST /signup
Register a new user.

**Request Body:**
```json
{
  "username": "string",
  "email": "string",
  "password": "string",
  "role": "string" // optional, defaults to "User"
}
```

**Response:**
- 201: Signup successful, check console for verification code
- 400: Validation error or user already exists

### POST /verify
Verify user email with code.

**Request Body:**
```json
{
  "email": "string",
  "code": "string"
}
```

**Response:**
- 200: Email verified
- 400: Invalid code

### POST /login
Login user.

**Request Body:**
```json
{
  "username": "string",
  "password": "string"
}
```

**Response:**
- 200: Login successful
- 401: Incorrect password
- 403: Email not verified
- 404: User not found

## Development

The application runs on `http://0.0.0.0:5000` in debug mode.