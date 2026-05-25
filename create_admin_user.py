#!/usr/bin/env python3
"""
Create Admin User in Database
Creates default admin user with proper password hash
"""

from werkzeug.security import generate_password_hash
from db_connection import DatabaseConnection, test_connection

def create_admin_user(username='admin', password='admin123', role='admin'):
    """Create or update admin user in database"""
    print("=" * 60)
    print("👤 ANPR System: Create Admin User")
    print("=" * 60)
    print()
    
    # Test connection
    if not test_connection():
        print("❌ Database connection failed!")
        return False
    
    print("✅ Database connection successful!")
    print()
    
    # Generate password hash
    password_hash = generate_password_hash(password)
    
    try:
        with DatabaseConnection() as db:
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
            
            # Also create 'anpr' user if it doesn't exist
            db.execute("SELECT id FROM users WHERE username = 'anpr'")
            anpr_exists = db.fetchone()
            
            if not anpr_exists:
                anpr_hash = generate_password_hash('anpr2024')
                db.execute("""
                    INSERT INTO users (username, password_hash, role, is_active)
                    VALUES ('anpr', %s, 'viewer', TRUE)
                """, (anpr_hash,))
                print("✅ Created additional user: anpr (password: anpr2024)")
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
        print(f"❌ Error creating admin user: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import sys
    
    # Allow custom username/password via command line
    username = sys.argv[1] if len(sys.argv) > 1 else 'admin'
    password = sys.argv[2] if len(sys.argv) > 2 else 'admin123'
    role = sys.argv[3] if len(sys.argv) > 3 else 'admin'
    
    create_admin_user(username, password, role)
    
    print("=" * 60)
    print("✅ Admin user setup complete!")
    print("=" * 60)
    print()
    print("🔑 Default credentials:")
    print(f"   Username: {username}")
    print(f"   Password: {password}")
    print()
    print("🌐 You can now login to the admin panel!")

