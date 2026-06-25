#!/usr/bin/env python3
"""
Create Admin User in Database
Creates default admin user with proper password hash
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from werkzeug.security import generate_password_hash
from db_connection import DatabaseConnection, test_connection

def create_admin_user():
    """Create or update default system users in database"""
    print("=" * 60)
    print("👤 ANPR System: Create Default Users")
    print("=" * 60)
    print()
    
    # Test connection
    if not test_connection():
        print("❌ Database connection failed!")
        return False
    
    print("✅ Database connection successful!")
    print()
    
    users_to_create = [
        {
            'username': 'superadmin',
            'password': 'superadmin@123',
            'role': 'superadmin'
        },
        {
            'username': 'admin',
            'password': 'admin@123',
            'role': 'admin'
        },
        {
            'username': 'viewer',
            'password': 'viewer@123',
            'role': 'viewer'
        }
    ]
    
    try:
        with DatabaseConnection() as db:
            for u in users_to_create:
                username = u['username']
                password = u['password']
                role = u['role']
                
                # Generate password hash
                password_hash = generate_password_hash(password)
                
                # Check if user already exists
                db.execute("SELECT id, username FROM users WHERE username = %s", (username,))
                existing = db.fetchone()
                
                if existing:
                    # Update existing user
                    db.execute("""
                        UPDATE users 
                        SET password_hash = %s, role = %s, is_active = TRUE, updated_at = NOW()
                        WHERE username = %s
                    """, (password_hash, role, username))
                    print(f"✅ Updated existing user: {username}")
                else:
                    # Create new user
                    db.execute("""
                        INSERT INTO users (username, password_hash, role, is_active)
                        VALUES (%s, %s, %s, TRUE)
                    """, (username, password_hash, role))
                    print(f"✅ Created new user: {username}")
                
                print(f"   Username: {username}")
                print(f"   Password: {password}")
                print(f"   Role: {role}")
                print()
            
            # List all users
            db.execute("SELECT username, role, is_active FROM users ORDER BY username")
            all_users = db.fetchall()
            
            print("📋 All users in database:")
            for user in all_users:
                status = "✅ Active" if user['is_active'] else "❌ Inactive"
                print(f"   - {user['username']} ({user['role']}) - {status}")
            print()
            
            return True
            
    except Exception as e:
        print(f"❌ Error creating default users: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    create_admin_user()
    
    print("=" * 60)
    print("✅ Default users setup complete!")
    print("=" * 60)
    print()
    print("🌐 You can now login to the admin panel with the default credentials!")

