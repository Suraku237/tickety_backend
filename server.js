const express = require('express');
const cors = require('cors');
const db = require('./db');
const app = express();

app.use(cors());
app.use(express.json());

// Signup Endpoint
app.post('/signup', (req, res) => {
  const { username, email, password } = req.body;
  const sql = "INSERT INTO users (username, email, password) VALUES (?, ?, ?)";
  db.query(sql, [username, email, password], (err, result) => {
    if (err) return res.status(500).send(err);
    res.status(201).send("User created");
  });
});

// Login Endpoint
app.post('/login', (req, res) => {
  const { email, password } = req.body;
  const sql = "SELECT * FROM users WHERE email = ? AND password = ?";
  db.query(sql, [email, password], (err, result) => {
    if (err || result.length === 0) return res.status(401).send("Invalid credentials");
    res.status(200).send("Login successful");
  });
});

app.listen(3000, () => console.log('Server running on port 3000'));