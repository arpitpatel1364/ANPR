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
    'host': 'localhost',
    'port': 3306,
    'user': 'root',
    'password': '',  # Default XAMPP MySQL password (empty)
    'database': 'anpr_system',
    'charset': 'utf8mb4',
    'collation': 'utf8mb4_unicode_ci',
    'autocommit': True,
    'connect_timeout': 10,
    'pool_name': 'anpr_pool',
    'pool_size': 5,
    'pool_reset_session': True
}

# Global connection pool
_connection_pool: Optional[pooling.MySQLConnectionPool] = None
_pool_lock = threading.Lock()


def load_db_config() -> Dict[str, Any]:
    """Load database configuration from config.json or use defaults"""
    try:
        config_path = 'config.json'
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = json.load(f)
                db_config = config.get('database', {})
                if db_config:
                    # Merge with defaults
                    merged_config = DEFAULT_DB_CONFIG.copy()
                    merged_config.update(db_config)
                    return merged_config
    except Exception as e:
        print(f"Warning: Could not load database config from config.json: {e}")
    
    return DEFAULT_DB_CONFIG.copy()


def get_connection_pool() -> Optional[pooling.MySQLConnectionPool]:
    """Get or create database connection pool"""
    global _connection_pool
    
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                try:
                    db_config = load_db_config()
                    
                    # Extract pool-specific config
                    pool_config = {
                        'host': db_config.get('host', 'localhost'),
                        'port': db_config.get('port', 3306),
                        'user': db_config.get('user', 'root'),
                        'password': db_config.get('password', ''),
                        'database': db_config.get('database', 'anpr_system'),
                        'charset': db_config.get('charset', 'utf8mb4'),
                        'autocommit': db_config.get('autocommit', True),
                        'pool_name': db_config.get('pool_name', 'anpr_pool'),
                        'pool_size': db_config.get('pool_size', 5),
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
            return None
        
        connection = pool.get_connection()
        return connection
        
    except Error as e:
        print(f"❌ Error getting database connection: {e}")
        return None


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
        
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
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
            if params:
                self.cursor.execute(query, params)
            else:
                self.cursor.execute(query)
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
        print("2. Database 'anpr_system' exists (or update config.json)")
        print("3. User credentials are correct in config.json")

