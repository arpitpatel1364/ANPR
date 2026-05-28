from flask import Blueprint, render_template, request, flash, redirect, url_for, session
from functools import wraps
import sys
import os

# Add parent directory to path for config_db import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts.config_db import load_config_from_db, save_settings_to_db

settings_bp = Blueprint('settings', __name__)

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('user_role') not in ['admin', 'superadmin']:
            flash('Access denied. Administrator privileges required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

@settings_bp.route('/settings', methods=['GET', 'POST'])
@require_admin
def settings():
    if request.method == 'POST':
        global_settings = {
            'fps_limit': int(request.form.get('global_fps_limit', 30)),
            'frame_skip': int(request.form.get('global_frame_skip', 2)),
        }
        
        display_settings = {
            'headless_mode': request.form.get('display_headless_mode') == 'on',
            'show_fps': request.form.get('display_show_fps') == 'on',
            'show_plate_count': request.form.get('display_show_plate_count') == 'on',
            'show_verification_stats': request.form.get('display_show_verification_stats') == 'on',
            'window_title': request.form.get('display_window_title', 'Multi-Camera ANPR System'),
            'grid_layout': request.form.get('display_grid_layout', '2x2'),
            'show_camera_names': request.form.get('display_show_camera_names') == 'on'
        }
        
        headless_settings = {
            'enabled': request.form.get('headless_enabled') == 'on',
            'log_level': request.form.get('headless_log_level', 'INFO'),
            'save_frames': request.form.get('headless_save_frames') == 'on',
            'frame_save_interval': int(request.form.get('headless_frame_save_interval', 30)),
            'status_update_interval': int(request.form.get('headless_status_update_interval', 10))
        }
        
        settings_to_save = {
            'global_settings': global_settings,
            'display_settings': display_settings,
            'headless_settings': headless_settings
        }
        
        if save_settings_to_db(settings_to_save):
            flash('Settings saved successfully! System hot reload triggered.', 'success')
        else:
            flash('Error saving settings to database.', 'error')
            
        return redirect(url_for('settings.settings'))
        
    # GET request
    config = load_config_from_db()
    if not config:
        config = {
            'global_settings': {},
            'display_settings': {},
            'headless_settings': {}
        }
        
    return render_template('settings.html', config=config)
