#!/usr/bin/env python3
"""
Initialize Database Tables
Creates all required tables in the MySQL database
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import initialize_database, test_connection

def main():
    print("=" * 60)
    print("🔧 ANPR System: Database Initialization")
    print("=" * 60)
    print()
    
    # Test connection first
    print("🔌 Testing database connection...")
    if not test_connection():
        print("❌ Database connection failed!")
        print("\nPlease ensure:")
        print("1. XAMPP MySQL is running")
        print("2. Database 'anpr_system' exists")
        print("3. User credentials are correct in environment variables")
        return
    
    print("✅ Database connection successful!")
    print()
    
    # Initialize database tables
    print("📋 Creating database tables...")
    if initialize_database():
        print("✅ Database tables created successfully!")
        print()
        print("📝 Created tables:")
        print("  - detections")
        print("  - allowed_plates")
        print("  - users")
        print("  - cameras")
        print()
        print("✅ You can now run the migration script or start using the system!")
    else:
        print("❌ Failed to create database tables")
        print("\nYou can manually import the schema:")
        print("1. Open phpMyAdmin (http://localhost/phpmyadmin)")
        print("2. Select 'anpr_system' database")
        print("3. Click 'Import' tab")
        print("4. Choose 'database_schema.sql' file")
        print("5. Click 'Go'")

if __name__ == "__main__":
    main()

