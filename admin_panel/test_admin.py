#!/usr/bin/env python3
"""
ANPR Admin Panel Test Script
This script tests the basic functionality of the admin panel
"""

import os
import sys
import json
import requests
import time
from pathlib import Path

def test_file_structure():
    """Test if all required files exist"""
    print("🔍 Testing file structure...")
    
    required_files = [
        'app.py',
        'auth.py',
        'plate_manager.py',
        'camera_manager.py',
        'detection_manager.py',
        'requirements.txt',
        'start_admin.sh',
        'templates/base.html',
        'templates/login.html',
        'templates/dashboard.html',
        'templates/plates.html',
        'templates/cameras.html',
        'templates/detections.html',
        'static/css/admin.css',
        'static/css/login.css',
        'static/js/admin.js'
    ]
    
    missing_files = []
    for file_path in required_files:
        if not os.path.exists(file_path):
            missing_files.append(file_path)
    
    if missing_files:
        print(f"❌ Missing files: {missing_files}")
        return False
    else:
        print("✅ All required files exist")
        return True

def test_dependencies():
    """Test if required dependencies can be imported"""
    print("🔍 Testing dependencies...")
    
    try:
        import flask
        import pandas
        from PIL import Image
        print("✅ All dependencies can be imported")
        return True
    except ImportError as e:
        print(f"❌ Missing dependency: {e}")
        return False

def test_config_files():
    """Test if ANPR system config files exist"""
    print("🔍 Testing ANPR system integration...")
    
    config_files = [
        '../config.json',
        '../allowed_plates.json',
        '../plate_detections.csv'
    ]
    
    missing_configs = []
    for config_file in config_files:
        if not os.path.exists(config_file):
            missing_configs.append(config_file)
    
    if missing_configs:
        print(f"⚠️  Missing ANPR config files: {missing_configs}")
        print("   Admin panel will work but may not have data to display")
    else:
        print("✅ ANPR system config files found")
    
    return True

def test_flask_app():
    """Test if Flask app can be imported and started"""
    print("🔍 Testing Flask application...")
    
    try:
        # Add current directory to path
        sys.path.insert(0, os.getcwd())
        
        # Import the app
        from app import app
        
        # Test app configuration
        assert app.secret_key is not None
        assert app.config['UPLOAD_FOLDER'] is not None
        
        print("✅ Flask application can be imported and configured")
        return True
        
    except Exception as e:
        print(f"❌ Flask application error: {e}")
        return False

def test_routes():
    """Test if all routes are properly registered"""
    print("🔍 Testing route registration...")
    
    try:
        from app import app
        
        # Get all routes
        routes = []
        for rule in app.url_map.iter_rules():
            routes.append(rule.rule)
        
        expected_routes = [
            '/',
            '/login',
            '/logout',
            '/plates',
            '/cameras',
            '/detections',
            '/api/stats'
        ]
        
        missing_routes = []
        for route in expected_routes:
            if not any(route in r for r in routes):
                missing_routes.append(route)
        
        if missing_routes:
            print(f"⚠️  Some routes may be missing: {missing_routes}")
        else:
            print("✅ All expected routes are registered")
        
        return True
        
    except Exception as e:
        print(f"❌ Route testing error: {e}")
        return False

def test_templates():
    """Test if templates can be rendered"""
    print("🔍 Testing template rendering...")
    
    try:
        from app import app
        
        with app.test_client() as client:
            # Test login page
            response = client.get('/login')
            assert response.status_code == 200
            assert b'ANPR Admin' in response.data
            
            print("✅ Templates can be rendered")
            return True
            
    except Exception as e:
        print(f"❌ Template testing error: {e}")
        return False

def create_test_data():
    """Create test data for demonstration"""
    print("🔍 Creating test data...")
    
    # Create verified plates directory
    os.makedirs('static/images/verified_plates', exist_ok=True)
    
    # Create a sample image
    try:
        from PIL import Image
        import numpy as np
        
        # Create a simple test image
        img_array = np.random.randint(0, 255, (480, 640, 3), dtype=np.uint8)
        img = Image.fromarray(img_array)
        img.save('static/images/verified_plates/test_plate.jpg')
        
        print("✅ Test data created")
        return True
        
    except Exception as e:
        print(f"⚠️  Could not create test data: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 ANPR Admin Panel Test Suite")
    print("=" * 50)
    
    tests = [
        test_file_structure,
        test_dependencies,
        test_config_files,
        test_flask_app,
        test_routes,
        test_templates,
        create_test_data
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
        print()
    
    print("=" * 50)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Admin panel is ready to use.")
        print("\n🚀 To start the admin panel:")
        print("   ./start_admin.sh")
        print("\n🌐 Then open: http://localhost:8084")
        print("🔑 Default credentials: admin/admin123")
    else:
        print("⚠️  Some tests failed. Please check the errors above.")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
