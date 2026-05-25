#!/bin/bash

# Test script to verify service configuration

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🔍 Testing ANPR Service Configuration..."

# Test 1: Check if script is executable
echo "1. Checking script permissions..."
if [ -x "$SCRIPT_DIR/start_anpr_service.sh" ]; then
    echo "   ✅ Script is executable"
else
    echo "   ❌ Script is not executable"
    chmod +x "$SCRIPT_DIR/start_anpr_service.sh"
    echo "   🔧 Made script executable"
fi

# Test 2: Check if virtual environment exists
echo "2. Checking virtual environment..."
if [ -f "$SCRIPT_DIR/anpr_env/bin/python" ]; then
    echo "   ✅ Virtual environment found"
else
    echo "   ❌ Virtual environment not found"
    exit 1
fi

# Test 3: Check if Python can import required modules
echo "3. Testing Python imports..."
cd "$SCRIPT_DIR"
source anpr_env/bin/activate
python -c "import cv2, torch, ultralytics, paddleocr; print('   ✅ All imports successful')" 2>/dev/null || echo "   ❌ Import failed"

# Test 4: Check if config file exists
echo "4. Checking configuration files..."
if [ -f "$SCRIPT_DIR/config.json" ]; then
    echo "   ✅ config.json found"
else
    echo "   ❌ config.json not found"
fi

if [ -f "$SCRIPT_DIR/ANPR_ver15.pt" ]; then
    echo "   ✅ Model file found"
else
    echo "   ❌ Model file not found"
fi

# Test 5: Test script execution (short test)
echo "5. Testing script execution..."
timeout 5s "$SCRIPT_DIR/start_anpr_service.sh" > /dev/null 2>&1
if [ $? -eq 124 ]; then
    echo "   ✅ Script runs (timed out after 5s as expected)"
elif [ $? -eq 0 ]; then
    echo "   ✅ Script runs successfully"
else
    echo "   ❌ Script failed with exit code $?"
fi

echo "🎯 Service configuration test complete!"
