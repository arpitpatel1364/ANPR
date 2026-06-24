from flask import Blueprint, render_template, request, jsonify, flash, redirect, url_for
import json
import os
import re
import sys
from datetime import datetime
import requests

# Add parent directory to path for db_connection import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection
from websocket_server import broadcast_reload_plates

plate_bp = Blueprint('plate', __name__)

def load_allowed_plates():
    """Load allowed plates from MySQL database"""
    try:
        with DatabaseConnection() as db:
            db.execute("SELECT license_plate FROM allowed_plates ORDER BY license_plate")
            rows = db.fetchall()
            plates = [row['license_plate'] for row in rows]
            
            return {
                "allowed_plates": plates,
                "description": "List of authorized vehicles allowed access",
                "last_updated": datetime.now().strftime('%Y-%m-%d'),
                "total_plates": len(plates)
            }
    except Exception as e:
        flash(f'Error loading allowed plates: {str(e)}', 'error')
        return {"allowed_plates": [], "description": "List of authorized vehicles allowed access", "last_updated": "", "total_plates": 0}

def reload_plates_in_anpr():
    """Reload plates from database and return updated count
    
    Since both admin panel and ANPR service read from the same MySQL database,
    the plates are automatically available to the ANPR service without an API call.
    This function confirms the reload succeeded by querying the database.
    """
    try:
        data = load_allowed_plates()
        plates_count = data.get('total_plates', 0)
        return True, plates_count
    except Exception as e:
        return False, str(e)

def save_allowed_plates(plates_list):
    """Save allowed plates to MySQL database"""
    try:
        with DatabaseConnection() as db:
            # Clear existing plates
            db.execute("DELETE FROM allowed_plates")
            
            # Insert new plates
            for plate in plates_list:
                clean_plate = plate.strip().upper()
                if clean_plate:
                    db.execute("INSERT INTO allowed_plates (license_plate) VALUES (%s) ON DUPLICATE KEY UPDATE license_plate = license_plate", (clean_plate,))
        
        return True
    except Exception as e:
        flash(f'Error saving allowed plates: {str(e)}', 'error')
        return False

@plate_bp.route('/plates')
def plates():
    """Plate management page"""
    data = load_allowed_plates()
    plates = data.get('allowed_plates', [])
    
    # Remove duplicates while preserving order
    unique_plates = []
    seen = set()
    for plate in plates:
        if plate not in seen:
            unique_plates.append(plate)
            seen.add(plate)
    
    return render_template('plates.html', plates=unique_plates, total_count=len(unique_plates))

@plate_bp.route('/plates/add', methods=['POST'])
def add_plate():
    """Add new plate"""
    plate = request.form.get('plate', '').strip().upper()
    
    if not plate:
        flash('Plate number is required!', 'error')
        return redirect(url_for('plate.plates'))

    # Simple license plate format validation
    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{1,4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$')

    if not plate_pattern.match(plate):
        flash(
            'Invalid plate format! Expected format: GJ01AB1234 '
            '(2 letters, 2 digits, 2 letters, 4 digits)',
            'error'
        )
        return redirect(url_for('plate.plates'))
    
    try:
        with DatabaseConnection() as db:
            # Check if plate already exists
            db.execute("SELECT id FROM allowed_plates WHERE license_plate = %s", (plate,))
            existing = db.fetchone()
            
            if existing:
                flash(f'Plate {plate} already exists!', 'warning')
            else:
                db.execute("INSERT INTO allowed_plates (license_plate) VALUES (%s)", (plate,))
                flash(f'Plate {plate} added successfully!', 'success')
                
                # Broadcast reload signal to ANPR service for live updates
                broadcast_reload_plates()
                flash(f'plate list updated in ANPR system', 'info')
    except Exception as e:
        flash(f'Error adding plate: {str(e)}', 'error')
    
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/delete', methods=['POST'])
def delete_plate():
    """Delete plate"""
    plate = request.form.get('plate', '').strip().upper()
    
    if not plate:
        flash('Plate number is required!', 'error')
        return redirect(url_for('plate.plates'))
    
    try:
        with DatabaseConnection() as db:
            db.execute("DELETE FROM allowed_plates WHERE license_plate = %s", (plate,))
            if db.cursor.rowcount > 0:
                flash(f'Plate {plate} deleted successfully!', 'success')
                
                # Broadcast reload signal to ANPR service for live updates
                broadcast_reload_plates()
                flash(f'plate list updated in ANPR system', 'info')
            else:
                flash(f'Plate {plate} not found!', 'error')
    except Exception as e:
        flash(f'Error deleting plate: {str(e)}', 'error')
    
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/edit', methods=['POST'])
def edit_plate():
    """Edit plate"""
    old_plate = request.form.get('old_plate', '').strip().upper()
    new_plate = request.form.get('new_plate', '').strip().upper()
    
    if not old_plate or not new_plate:
        flash('Both old and new plate numbers are required!', 'error')
        return redirect(url_for('plate.plates'))
        
    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{1,4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$')
    if not plate_pattern.match(new_plate):
        flash('Invalid plate format!', 'error')
        return redirect(url_for('plate.plates'))
        
    try:
        with DatabaseConnection() as db:
            db.execute("UPDATE allowed_plates SET license_plate = %s WHERE license_plate = %s", (new_plate, old_plate))
            if db.cursor.rowcount > 0:
                flash(f'Plate {old_plate} updated to {new_plate} successfully!', 'success')
                broadcast_reload_plates()
            else:
                flash(f'Plate {old_plate} not found!', 'error')
    except Exception as e:
        if 'Duplicate entry' in str(e):
            flash(f'Plate {new_plate} already exists!', 'error')
        else:
            flash(f'Error updating plate: {str(e)}', 'error')
            
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/bulk_add', methods=['POST'])
def bulk_add_plates():
    """Bulk add plates from text input"""
    plates_text = request.form.get('plates_text', '').strip()
    
    if not plates_text:
        flash('No plates provided!', 'error')
        return redirect(url_for('plate.plates'))
    
    # Split by commas, semicolons, newlines, or whitespace
    raw_plates = re.split(r'[\n,;\s]+', plates_text)
    plates = [p.strip().upper() for p in raw_plates if p.strip()]
    
    if not plates:
        flash('No valid plates found!', 'error')
        return redirect(url_for('plate.plates'))
    
    try:
        with DatabaseConnection() as db:
            # Get existing plates
            db.execute("SELECT license_plate FROM allowed_plates")
            existing_rows = db.fetchall()
            existing_plates = set(row['license_plate'] for row in existing_rows)
            
            new_plates = []
            duplicates = []
            invalid_plates = []
            
            # Simple license plate format validation pattern
            plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{1,3}[0-9]{1,4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{1,2}$')
            
            for plate in plates:
                # First check length and format to prevent DB truncate/length errors
                if len(plate) > 20 or not plate_pattern.match(plate):
                    invalid_plates.append(plate)
                    continue
                    
                if plate not in existing_plates:
                    new_plates.append(plate)
                    existing_plates.add(plate)
                else:
                    duplicates.append(plate)
            
            # Insert new plates
            if new_plates:
                success_count = 0
                failed_plates = []
                for plate in new_plates:
                    try:
                        db.execute("INSERT INTO allowed_plates (license_plate) VALUES (%s) ON DUPLICATE KEY UPDATE license_plate = license_plate", (plate,))
                        success_count += 1
                    except Exception as db_err:
                        failed_plates.append((plate, str(db_err)))
                
                if success_count > 0:
                    flash(f'Added {success_count} new plates successfully!', 'success')
                    # Broadcast reload signal to ANPR service for live updates
                    broadcast_reload_plates()
                    flash(f'plate list updated in ANPR system', 'info')
                
                if failed_plates:
                    error_details = ", ".join([f"{p} ({err})" for p, err in failed_plates[:3]])
                    if len(failed_plates) > 3:
                        error_details += f" and {len(failed_plates) - 3} more"
                    flash(f'Failed to add some plates due to database errors: {error_details}', 'error')
            
            if duplicates:
                flash(f'{len(duplicates)} plates were already in the list', 'warning')
                
            if invalid_plates:
                invalid_show = invalid_plates[:5]
                invalid_msg = ", ".join(invalid_show)
                if len(invalid_plates) > 5:
                    invalid_msg += f" and {len(invalid_plates) - 5} more"
                flash(f'Skipped {len(invalid_plates)} invalid/too long plates: {invalid_msg}', 'error')
                
    except Exception as e:
        flash(f'Error adding plates: {str(e)}', 'error')
    
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/remove_duplicates', methods=['POST'])
def remove_duplicates():
    """Remove duplicate plates from the database"""
    try:
        with DatabaseConnection() as db:
            # Delete duplicate rows keeping the one with the smallest ID
            query = """
                DELETE p1 FROM allowed_plates p1
                INNER JOIN allowed_plates p2 
                ON p1.license_plate = p2.license_plate 
                WHERE p1.id > p2.id
            """
            db.execute(query)
            removed_count = db.cursor.rowcount
            
            if removed_count > 0:
                flash(f'Successfully removed {removed_count} duplicate plate(s)!', 'success')
                # Broadcast reload signal to ANPR service for live updates
                broadcast_reload_plates()
            else:
                flash('No duplicate plates found in the database.', 'info')
    except Exception as e:
        flash(f'Error removing duplicates: {str(e)}', 'error')
        
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/search')
def search_plates():
    """Search plates API"""
    query = request.args.get('q', '').strip().upper()
    
    if not query:
        return jsonify([])
    
    try:
        with DatabaseConnection() as db:
            db.execute("SELECT license_plate FROM allowed_plates WHERE license_plate LIKE %s ORDER BY license_plate LIMIT 10", (f"%{query}%",))
            rows = db.fetchall()
            matching_plates = [row['license_plate'] for row in rows]
        
        return jsonify(matching_plates)
    except Exception as e:
        return jsonify([])
