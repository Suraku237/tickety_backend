import os

class Config:
    # Replace with your actual MySQL credentials
    SQLALCHEMY_DATABASE_URI = 'mysql+mysqlconnector://root:12345@localhost/tickety_db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False