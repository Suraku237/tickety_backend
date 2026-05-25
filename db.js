const mysql = require('mysql2');
require('dotenv').config();

const connection = mysql.createConnection({
  host: 'localhost',
  user: 'root',      // Your MySQL username
  password: '12345', // Your MySQL password
  database: 'tickety_db'
});

connection.connect((err) => {
  if (err) throw err;
  console.log('Connected to MySQL Database.');
});

module.exports = connection;