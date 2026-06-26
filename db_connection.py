"""
Database Connection Module for ANPR System
Uses mysql-connector-python for MySQL/MariaDB connectivity
"""

import mysql.connector
from mysql.connector import Error, pooling
import os
import json
import threading
from typing import Optional, Dict, Any, List
import logging

# Default database configuration
DEFAULT_DB_CONFIG = {
    'host': '127.0.0.1',
    'port': 3307,
    'user': 'root',
    'password': '',  # Default XAMPP MySQL password (empty)
    'database': 'anpr_system',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'autocommit': True,
    'connect_timeout': 10,
    'pool_name': 'anpr_pool',
    'pool_size': 10,
    'pool_reset_session': True
}

# Global connection pool
_connection_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = threading.Lock()


def load_db_config() -> Dict[str, Any]:
    """Load database configuration from Environment Variables or use defaults"""
    try:
        merged_config = DEFAULT_DB_CONFIG.copy()
        
        # Load from env vars if present
        if os.environ.get('DB_HOST'): merged_config['host'] = os.environ.get('DB_HOST')
        if os.environ.get('DB_PORT'): merged_config['port'] = int(os.environ.get('DB_PORT'))
        if os.environ.get('DB_USER'): merged_config['user'] = os.environ.get('DB_USER')
        if os.environ.get('DB_PASSWORD') is not None: merged_config['password'] = os.environ.get('DB_PASSWORD')
        if os.environ.get('DB_NAME'): merged_config['database'] = os.environ.get('DB_NAME')
        
        return merged_config
    except Exception as e:
        print(f"Warning: Could not load database config from Environment: {e}")
    
    return DEFAULT_DB_CONFIG.copy()


def get_connection_pool() -> Optional[pooling.MySQLConnectionPool]:
    """Get or create database connection pool"""
    global _connection_pool
    
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                try:
                    db_config = load_db_config()
                    
                    # Ensure database exists first
                    try:
                        temp_config = db_config.copy()
                        db_name = temp_config.pop('database', 'anpr_system')
                        temp_config.pop('pool_name', None)
                        temp_config.pop('pool_size', None)
                        temp_config.pop('pool_reset_session', None)
                        
                        temp_conn = mysql.connector.connect(**temp_config)
                        temp_cursor = temp_conn.cursor()
                        temp_cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                        temp_cursor.close()
                        temp_conn.close()
                        print(f"✅ Verified database '{db_name}' exists")
                    except Error as e:
                        print(f"⚠️ Could not verify/create database before pool: {e}")
                    
                    # Extract pool-specific config
                    pool_config = {
                        'host': db_config.get('host', 'localhost'),
                        'port': db_config.get('port', 3307),
                        'user': db_config.get('user', 'root'),
                        'password': db_config.get('password', ''),
                        'database': db_config.get('database', 'anpr_system'),
                        'charset': db_config.get('charset', 'utf8mb4'),
                        'autocommit': db_config.get('autocommit', True),
                        'pool_name': db_config.get('pool_name', 'anpr_pool'),
                        'pool_size': db_config.get('pool_size', 10),
                        'pool_reset_session': db_config.get('pool_reset_session', True)
                    }
                    
                    _connection_pool = pooling.MySQLConnectionPool(**pool_config)
                    print("✅ Database connection pool created successfully")
                    
                except Error as e:
                    print(f"❌ Error creating connection pool: {e}")
                    _connection_pool = None
    
    return _connection_pool


def get_connection():
    """Get a database connection from the pool"""
    try:
        pool = get_connection_pool()
        if pool is None:
            # Try to recreate pool if it was None
            global _connection_pool
            with _pool_lock:
                _connection_pool = None
            pool = get_connection_pool()
            if pool is None:
                return None
        
        connection = pool.get_connection()
        if not connection.is_connected():
            connection.ping(reconnect=True, attempts=3, delay=2)
        return connection
        
    except Error as e:
        print(f"❌ Error getting database connection: {e}")
        return None

def wait_for_db_connection(max_retries=30, retry_delay=2):
    """Wait for database to become available (useful on startup)"""
    import time
    for i in range(max_retries):
        try:
            pool = get_connection_pool()
            if pool:
                conn = pool.get_connection()
                conn.ping(reconnect=True, attempts=1, delay=1)
                conn.close()
                print("✅ Database is ready!")
                return True
        except Exception:
            pass
        print(f"⏳ Waiting for database to start... (Attempt {i+1}/{max_retries})")
        time.sleep(retry_delay)
    return False


def execute_query(query: str, params: Optional[tuple] = None, fetch: bool = False) -> Optional[Any]:
    """
    Execute a database query
    
    Args:
        query: SQL query string
        params: Query parameters (tuple)
        fetch: Whether to fetch results (True) or just execute (False)
    
    Returns:
        Query results if fetch=True, None otherwise
    """
    connection = None
    cursor = None
    
    try:
        connection = get_connection()
        if connection is None:
            return None
        
        cursor = connection.cursor(dictionary=True)
        
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
        except Error as e:
            # If connection was lost, try to ping and retry once
            if e.errno == 2006 or "MySQL server has gone away" in str(e):
                connection.ping(reconnect=True, attempts=3, delay=2)
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)
            else:
                raise e
        
        if fetch:
            result = cursor.fetchall()
            return result
        else:
            connection.commit()
            return cursor.rowcount
            
    except Error as e:
        print(f"❌ Database query error: {e}")
        if connection:
            connection.rollback()
        return None
        
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def execute_many(query: str, params_list: List[tuple]) -> Optional[int]:
    """
    Execute a query multiple times with different parameters (bulk insert/update)
    
    Args:
        query: SQL query string
        params_list: List of parameter tuples
    
    Returns:
        Number of affected rows
    """
    connection = None
    cursor = None
    
    try:
        connection = get_connection()
        if connection is None:
            return None
        
        cursor = connection.cursor()
        cursor.executemany(query, params_list)
        connection.commit()
        
        return cursor.rowcount
        
    except Error as e:
        print(f"❌ Database bulk query error: {e}")
        if connection:
            connection.rollback()
        return None
        
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


def test_connection() -> bool:
    """Test database connection"""
    try:
        connection = get_connection()
        if connection is None:
            return False
        
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()
        connection.close()
        
        print("✅ Database connection test successful")
        return True
        
    except Error as e:
        print(f"❌ Database connection test failed: {e}")
        return False


def initialize_database() -> bool:
    """Initialize database tables (create if not exist)"""
    try:
        # Read SQL schema file
        schema_path = 'database_schema.sql'
        if not os.path.exists(schema_path):
            print(f"⚠️ Schema file not found: {schema_path}")
            return False
        
        connection = get_connection()
        if connection is None:
            return False
        
        cursor = connection.cursor()
        
        # Read and execute schema
        with open(schema_path, 'r', encoding='utf-8') as f:
            schema_sql = f.read()
        
        # Remove comments and split by semicolon
        lines = schema_sql.split('\n')
        cleaned_lines = []
        for line in lines:
            # Remove full-line comments
            if line.strip().startswith('--'):
                continue
            # Remove inline comments (but keep the SQL part)
            if '--' in line:
                line = line[:line.index('--')]
            cleaned_lines.append(line)
        
        cleaned_sql = '\n'.join(cleaned_lines)
        
        # Split by semicolon and execute each statement
        statements = [s.strip() for s in cleaned_sql.split(';') if s.strip()]
        
        executed = 0
        for statement in statements:
            if statement and not statement.isspace():
                try:
                    cursor.execute(statement)
                    executed += 1
                except Error as e:
                    error_msg = str(e)
                    # Ignore "table already exists" errors and duplicate key errors
                    if "already exists" not in error_msg.lower() and "duplicate" not in error_msg.lower():
                        print(f"⚠️ Warning executing statement: {error_msg}")
                        print(f"   Statement: {statement[:100]}...")
        
        connection.commit()
        cursor.close()
        connection.close()
        
        if executed > 0:
            print(f"✅ Database initialized successfully ({executed} statements executed)")
        else:
            print("⚠️ No statements were executed")
        
        return True
        
    except Exception as e:
        print(f"❌ Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        return False


# Context manager for database connections
class DatabaseConnection:
    """Context manager for database connections"""
    
    def __init__(self):
        self.connection = None
        self.cursor = None
    
    def __enter__(self):
        self.connection = get_connection()
        if self.connection:
            try:
                self.connection.ping(reconnect=True, attempts=3, delay=1)
            except Error as e:
                print(f"DatabaseConnection ping failed: {e}")
            self.cursor = self.connection.cursor(dictionary=True)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            if exc_type:
                self.connection.rollback()
            else:
                self.connection.commit()
            self.connection.close()
        return False
    
    def execute(self, query: str, params: Optional[tuple] = None):
        """Execute a query"""
        if self.cursor:
            try:
                if params:
                    self.cursor.execute(query, params)
                else:
                    self.cursor.execute(query)
            except Error as e:
                if e.errno == 2006 or "gone away" in str(e).lower() or "lost connection" in str(e).lower():
                    try:
                        print("Database connection lost. Reconnecting...")
                        self.connection.ping(reconnect=True, attempts=3, delay=1)
                        self.cursor = self.connection.cursor(dictionary=True)
                        if params:
                            self.cursor.execute(query, params)
                        else:
                            self.cursor.execute(query)
                    except Error as retry_e:
                        print(f"Failed to retry query: {retry_e}")
                        raise e
                else:
                    raise e
            return self.cursor
        return None
    
    def fetchall(self):
        """Fetch all results"""
        if self.cursor:
            return self.cursor.fetchall()
        return []
    
    def fetchone(self):
        """Fetch one result"""
        if self.cursor:
            return self.cursor.fetchone()
        return None


if __name__ == "__main__":
    # Test the database connection
    print("Testing database connection...")
    if test_connection():
        print("✅ Connection successful!")
    else:
        print("❌ Connection failed!")
        print("\nPlease ensure:")
        print("1. XAMPP MySQL is running")
        print("2. Database 'anpr_system' exists")
        print("3. User credentials are correct in environment variables")

