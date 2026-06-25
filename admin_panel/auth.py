from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
import os
import sys
import time
import hashlib
from datetime import datetime, timedelta

# Add parent directory to path for db_connection import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection

auth_bp = Blueprint('auth', __name__)

# Fallback users (if database is not available)
FALLBACK_USERS = {
    'superadmin': {
        'password': generate_password_hash('superadmin@123'),
        'role': 'superadmin',
        'last_login': None,
        'failed_attempts': 0,
        'locked_until': None
    },
    'admin': {
        'password': generate_password_hash('admin@123'),
        'role': 'admin',
        'last_login': None,
        'failed_attempts': 0,
        'locked_until': None
    },
    'viewer': {
        'password': generate_password_hash('viewer@123'),
        'role': 'viewer',
        'last_login': None,
        'failed_attempts': 0,
        'locked_until': None
    }
}

# In-memory cache for failed attempts (per session)
failed_attempts_cache = {}

# Security settings
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = 300  # 5 minutes in seconds
SESSION_TIMEOUT = 3600  # 1 hour in seconds

def get_user_from_db(username):
    """Get user from database"""
    try:
        with DatabaseConnection() as db:
            db.execute("SELECT id, username, password_hash, role, is_active FROM users WHERE username = %s", (username,))
            result = db.fetchone()
            if result and result['is_active']:
                return {
                    'id': result['id'],
                    'username': result['username'],
                    'password_hash': result['password_hash'],
                    'role': result['role'],
                    'is_active': result['is_active']
                }
    except Exception as e:
        print(f"Error getting user from database: {e}")
    return None

def is_account_locked(username):
    """Check if account is locked due to failed attempts"""
    # Check in-memory cache
    if username in failed_attempts_cache:
        cache_entry = failed_attempts_cache[username]
        if cache_entry['locked_until'] and datetime.now() < cache_entry['locked_until']:
            return True
        # Unlock if expired
        if cache_entry['locked_until'] and datetime.now() >= cache_entry['locked_until']:
            failed_attempts_cache[username] = {'failed_attempts': 0, 'locked_until': None}
    
    return False

def record_failed_attempt(username):
    """Record a failed login attempt"""
    if username not in failed_attempts_cache:
        failed_attempts_cache[username] = {'failed_attempts': 0, 'locked_until': None}
    
    failed_attempts_cache[username]['failed_attempts'] += 1
    
    if failed_attempts_cache[username]['failed_attempts'] >= MAX_FAILED_ATTEMPTS:
        failed_attempts_cache[username]['locked_until'] = datetime.now() + timedelta(seconds=LOCKOUT_DURATION)
        flash(f'Account locked due to {MAX_FAILED_ATTEMPTS} failed attempts. Try again in {LOCKOUT_DURATION//60} minutes.', 'error')

def record_successful_login(username):
    """Record a successful login"""
    # Reset failed attempts
    if username in failed_attempts_cache:
        failed_attempts_cache[username] = {'failed_attempts': 0, 'locked_until': None}
    
    # Update last login in database
    try:
        with DatabaseConnection() as db:
            db.execute("UPDATE users SET updated_at = NOW() WHERE username = %s", (username,))
    except Exception as e:
        print(f"Error updating last login: {e}")

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Enhanced login page with security measures"""
    # Check if already logged in
    if 'logged_in' in session and session.get('logged_in'):
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember_me = request.form.get('remember_me')
        
        # Basic validation
        if not username or not password:
            flash('Please enter both username and password!', 'error')
            return render_template('login.html')
        
        # Check if account is locked
        if is_account_locked(username):
            cache_entry = failed_attempts_cache.get(username, {})
            if cache_entry.get('locked_until'):
                remaining_time = (cache_entry['locked_until'] - datetime.now()).seconds
                flash(f'Account is locked. Try again in {remaining_time//60} minutes.', 'error')
            return render_template('login.html')
        
        # Try to get user from database first
        user = get_user_from_db(username)
        
        # Fallback to hardcoded users if database fails
        if not user:
            if username in FALLBACK_USERS:
                user = {
                    'username': username,
                    'password_hash': FALLBACK_USERS[username]['password'],
                    'role': FALLBACK_USERS[username]['role']
                }
            else:
                user = None
        
        # Validate credentials
        if user and check_password_hash(user['password_hash'], password):
            # Successful login
            record_successful_login(username)
            
            # Set session
            session['logged_in'] = True
            session['username'] = username
            session['user_role'] = user['role']
            session['login_time'] = time.time()
            
            # Set session timeout
            if remember_me:
                session.permanent = True
            else:
                session.permanent = False
            
            flash('Login successful!', 'success')
            
            # Redirect to intended page or dashboard
            next_page = request.args.get('next')
            if next_page and next_page.startswith('/'):
                return redirect(next_page)
            return redirect(url_for('dashboard'))
        else:
            # Failed login
            record_failed_attempt(username)
            flash('Invalid username or password!', 'error')
    
    return render_template('login.html')

def is_session_valid():
    """Check if current session is valid and not expired"""
    if 'logged_in' not in session or not session.get('logged_in'):
        return False
    
    # Check session timeout
    if 'login_time' in session:
        if time.time() - session['login_time'] > SESSION_TIMEOUT:
            return False
    
    return True

def require_auth(f):
    """Enhanced authentication decorator with session validation"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_session_valid():
            session.clear()
            flash('Session expired. Please login again.', 'warning')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin or superadmin role"""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        role = session.get('user_role', 'viewer')
        if role not in ['admin', 'superadmin']:
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'success': False, 'message': 'Access denied: Admin privileges required'}), 403
            flash('Access denied. Administrator privileges required.', 'error')
            return redirect(request.referrer or url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@auth_bp.route('/logout')
def logout():
    """Enhanced logout with security cleanup"""
    username = session.get('username')
    # Clear failed attempts cache for this user
    if username in failed_attempts_cache:
        del failed_attempts_cache[username]
    
    session.clear()
    flash('You have been logged out!', 'info')
    return redirect(url_for('auth.login'))

@auth_bp.route('/check-session')
def check_session():
    """API endpoint to check session validity"""
    if is_session_valid():
        return jsonify({'valid': True, 'username': session.get('username')})
    else:
        return jsonify({'valid': False})
