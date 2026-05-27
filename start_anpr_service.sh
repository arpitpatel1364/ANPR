#!/bin/bash

# This script starts the ANPR multi-camera system

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set the working directory
cd "$SCRIPT_DIR"

# Initialize conda with correct path
source "$SCRIPT_DIR/anpr_env/bin/activate"

# Log the current directory and user
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current directory: $(pwd)" >> "$SCRIPT_DIR/anpr_service.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Current user: $(whoami)" >> "$SCRIPT_DIR/anpr_service.log"

# Set environment variables
export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"
export CUDA_VISIBLE_DEVICES=0
export OPENCV_VIDEOIO_PRIORITY_MSMF=0

# Log file for service output
LOG_FILE="$SCRIPT_DIR/anpr_service.log"

# Function to log with timestamp
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting ANPR Multi-Camera Service..."

# Check if config.json exists
if [ ! -f "config.json" ]; then
    log "ERROR: config.json not found!"
    exit 1
fi

# Check if model file exists
if [ ! -f "ANPR_ver15.pt" ]; then
    log "ERROR: ANPR_ver15.pt model file not found!"
    exit 1
fi

# Check if plate_logger.py exists
if [ ! -f "plate_logger.py" ]; then
    log "ERROR: plate_logger.py not found!"
    exit 1
fi

# Start the application
log "Launching app_multi_camera_lprnet.py..."
"$SCRIPT_DIR/anpr_env/bin/python" "$SCRIPT_DIR/app_multi_camera_lprnet.py" 2>&1 | tee -a "$LOG_FILE"

# Log when service stops
log "ANPR Multi-Camera Service stopped."
