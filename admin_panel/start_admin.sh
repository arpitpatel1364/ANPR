#!/bin/bash

# ANPR Admin Panel Startup Script
# This script starts the admin panel web interface

echo "🚀 Starting ANPR Admin Panel..."

# Get the script directory and parent directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

# Set the working directory to the root ANPR Production directory
cd "$PARENT_DIR"

# Initialize Python venv
echo "🔧 Activating Python environment..."
source "$PARENT_DIR/anpr_env/bin/activate"

# Install requirements
echo "📥 Installing requirements..."
pip install -r "$SCRIPT_DIR/requirements.txt"

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p "$SCRIPT_DIR/static/images/verified_plates"
mkdir -p "$SCRIPT_DIR/static/css"
mkdir -p "$SCRIPT_DIR/static/js"
mkdir -p "$SCRIPT_DIR/templates"

# Set permissions
chmod +x "$SCRIPT_DIR/start_admin.sh"

# Start the admin panel
echo "🌐 Starting admin panel on http://localhost:8084"
echo "📝 Default credentials: admin/admin123 or anpr/anpr2024"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

cd "$SCRIPT_DIR"
python app.py
