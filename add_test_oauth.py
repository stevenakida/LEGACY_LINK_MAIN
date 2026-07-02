"""
Simple script to add test OAuth credentials without full migrations
This script modifies settings to bypass allauth and adds test data directly
"""
import os
import sys
import sqlite3

# Path to your database
DB_PATH = r"c:\Users\.~Barson\LEGACY AFRICA\db.sqlite3"

def add_test_oauth_credentials():
    """Add test OAuth credentials directly to database"""
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # Step 1: Ensure sites table exists and has entry
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS django_site (
                id INTEGER PRIMARY KEY,
                domain VARCHAR(100),
                name VARCHAR(50)
            )
        ''')
        
        cursor.execute('SELECT * FROM django_site WHERE id = 1')
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO django_site (id, domain, name) 
                VALUES (1, 'localhost:8000', 'LegacyLink Africa Dev')
            ''')
            print("✓ Created site entry")
        else:
            print("✓ Site entry already exists")
        
        # Step 2: Create socialaccount app table if needed
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS socialaccount_socialapp (
                id INTEGER PRIMARY KEY,
                provider VARCHAR(50),
                name VARCHAR(100),
                client_id VARCHAR(255),
                secret VARCHAR(255)
            )
        ''')
        
        # Check if test credentials already exist
        cursor.execute("SELECT * FROM socialaccount_socialapp WHERE provider = 'google'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO socialaccount_socialapp 
                (provider, name, client_id, secret) 
                VALUES (?, ?, ?, ?)
            ''', ('google', 'Google OAuth (Test)', 'test-google-client-id.apps.googleusercontent.com', 'test-google-secret-123'))
            print("✓ Added Google OAuth credentials")
        else:
            print("✓ Google OAuth credentials already exist")
        
        cursor.execute("SELECT * FROM socialaccount_socialapp WHERE provider = 'facebook'")
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO socialaccount_socialapp 
                (provider, name, client_id, secret) 
                VALUES (?, ?, ?, ?)
            ''', ('facebook', 'Facebook OAuth (Test)', '1234567890', 'test-facebook-secret-789'))
            print("✓ Added Facebook OAuth credentials")
        else:
            print("✓ Facebook OAuth credentials already exist")
        
        conn.commit()
        print("\n✅ OAuth test credentials configured successfully!")
        print("\nTest Credentials:")
        print("  Google Client ID: test-google-client-id.apps.googleusercontent.com")
        print("  Facebook App ID: 1234567890")
        print("\nThese are test credentials. Replace with real ones for production.")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found at {DB_PATH}")
        sys.exit(1)
    
    add_test_oauth_credentials()
