#!/usr/bin/env python3
"""
Database setup script for TICKETY - creates all tables in Aiven MySQL
Uses credentials from environment or directly specified
"""

import os
import sys
from dotenv import load_dotenv
from app import create_app

load_dotenv()

def setup_database():
    """Initialize database with all tables"""
    app = create_app()

    with app.app_context():
        try:
            # Test connection
            with app.app.app_context() as ctx:
                db.engine.connect()
            print('✅ Connected to Aiven MySQL database.')

            # Create all tables
            db.create_all()
            print('✅ All tables created successfully:')
            print('   - users')
            print('   - resets')
            print('   - services')
            print('   - qr_codes')
            print('   - tickets')
            print('\n✅ Database initialization complete!')
            return True

        except Exception as e:
            print(f'❌ Database setup failed: {e}')
            sys.exit(1)

if __name__ == '__main__':
    setup_database()
