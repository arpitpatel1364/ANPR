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
from auth import admin_required

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
    """Save/merge allowed plates to MySQL database without wiping existing ones."""
    try:
        params_list = [(plate.strip().upper(),) for plate in plates_list if plate.strip()]
        if params_list:
            with DatabaseConnection() as db:
                db.cursor.executemany(
                    "INSERT INTO allowed_plates (license_plate) VALUES (%s) "
                    "ON DUPLICATE KEY UPDATE license_plate = license_plate",
                    params_list
                )
        return True
    except Exception as e:
        flash(f'Error saving allowed plates: {str(e)}', 'error')
        return False

@plate_bp.route('/plates')
def plates():
    """Plate management page with optional pagination (activates when > 25 records)"""
    page = request.args.get('page', 1, type=int)
    per_page = 25

    blacklisted_plates = []
    total_count = 0
    plates_list = []
    total_pages = 1

    try:
        with DatabaseConnection() as db:
            # Total count
            db.execute("SELECT COUNT(*) as cnt FROM allowed_plates")
            row = db.fetchone()
            total_count = row['cnt'] if row else 0

            if total_count > per_page:
                # Server-side pagination
                offset = (page - 1) * per_page
                db.execute(
                    "SELECT license_plate, description FROM allowed_plates "
                    "ORDER BY license_plate LIMIT %s OFFSET %s",
                    (per_page, offset)
                )
                total_pages = (total_count + per_page - 1) // per_page
            else:
                # Load all — no pagination needed
                db.execute("SELECT license_plate, description FROM allowed_plates ORDER BY license_plate")
                page = 1

            rows = db.fetchall()
            plates_list = [{'plate': r['license_plate'], 'description': r['description'] or ''} for r in rows]

            # Blacklisted plates
            db.execute("SELECT id, license_plate, description, added_by, created_at FROM blacklist_plates ORDER BY license_plate")
            for row in db.fetchall():
                blacklisted_plates.append({
                    'id': row['id'],
                    'license_plate': row['license_plate'],
                    'description': row['description'] or '',
                    'added_by': row['added_by'] or 'Admin',
                    'created_at': row['created_at'].strftime('%Y-%m-%d %H:%M:%S') if row['created_at'] else ''
                })
    except Exception as e:
        flash(f'Error loading plates: {str(e)}', 'error')

    paginated = total_count > per_page

    return render_template('plates.html',
                           plates=plates_list,
                           total_count=total_count,
                           blacklisted_plates=blacklisted_plates,
                           total_blacklisted=len(blacklisted_plates),
                           page=page,
                           total_pages=total_pages,
                           per_page=per_page,
                           paginated=paginated)

@plate_bp.route('/plates/add', methods=['POST'])
@admin_required
def add_plate():
    """Add new plate with optional description"""
    plate = request.form.get('plate', '').strip().upper()
    description = request.form.get('description', '').strip()

    if not plate:
        flash('Plate number is required!', 'error')
        return redirect(url_for('plate.plates'))

    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{2,3}[0-9]{4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{2}$')

    if not plate_pattern.match(plate):
        flash(
            'Invalid plate format! Expected 10 or 11 character format '
            '(e.g., GJ01AB1234 or 21BH1234AA)',
            'error'
        )
        return redirect(url_for('plate.plates'))

    try:
        with DatabaseConnection() as db:
            db.execute("SELECT id FROM blacklist_plates WHERE license_plate = %s", (plate,))
            if db.fetchone():
                flash(f'Plate {plate} is blacklisted! Cannot add to allowed list.', 'error')
                return redirect(url_for('plate.plates'))

            db.execute("SELECT id FROM allowed_plates WHERE license_plate = %s", (plate,))
            existing = db.fetchone()

            if existing:
                flash(f'Plate {plate} already exists!', 'warning')
            else:
                db.execute(
                    "INSERT INTO allowed_plates (license_plate, description) VALUES (%s, %s)",
                    (plate, description or None)
                )
                flash(f'Plate {plate} added successfully!', 'success')
                broadcast_reload_plates()
                flash('Plate list updated in ANPR system', 'info')
    except Exception as e:
        flash(f'Error adding plate: {str(e)}', 'error')

    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/delete', methods=['POST'])
@admin_required
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
@admin_required
def edit_plate():
    """Edit plate"""
    old_plate = request.form.get('old_plate', '').strip().upper()
    new_plate = request.form.get('new_plate', '').strip().upper()
    description = request.form.get('description', '').strip()
    
    if not old_plate or not new_plate:
        flash('Both old and new plate numbers are required!', 'error')
        return redirect(url_for('plate.plates'))
        
    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{2,3}[0-9]{4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{2}$')
    if not plate_pattern.match(new_plate):
        flash(
            'Invalid plate format! Expected 10 or 11 character format '
            '(e.g., GJ01AB1234 or 21BH1234AA)',
            'error'
        )
        return redirect(url_for('plate.plates'))
        
    try:
        with DatabaseConnection() as db:
            # Check if new plate is in blacklist
            db.execute("SELECT id FROM blacklist_plates WHERE license_plate = %s", (new_plate,))
            if db.fetchone():
                flash(f'Plate {new_plate} is blacklisted! Cannot update to this plate.', 'error')
                return redirect(url_for('plate.plates'))
                
            db.execute(
                "UPDATE allowed_plates SET license_plate = %s, description = %s WHERE license_plate = %s",
                (new_plate, description or None, old_plate)
            )
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
@admin_required
def bulk_add_plates():
    """Bulk add plates from text input"""
    plates_text = request.form.get('plates_text', '').strip()
    
    if not plates_text:
        flash('No plates provided!', 'error')
        return redirect(url_for('plate.plates'))
    
    # Split by commas, semicolons, newlines, or whitespace
    raw_plates = re.split(r'[\n,;\s]+', plates_text)
    raw_tokens = [p.strip().upper() for p in raw_plates if p.strip()]
    
    if not raw_tokens:
        flash('No valid plates found!', 'error')
        return redirect(url_for('plate.plates'))
    
    # Simple license plate format validation patterns
    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{2,3}[0-9]{4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{2}$')
    sub_pattern = re.compile(r'[A-Z]{2}[0-9]{2}[A-Z]{2,3}[0-9]{4}|[0-9]{2}BH[0-9]{4}[A-Z]{2}')
    
    plates = []
    invalid_plates = []
    
    for token in raw_tokens:
        if plate_pattern.match(token):
            plates.append(token)
        else:
            # Try to extract valid plates if they entered multiple without delimiters
            found_plates = sub_pattern.findall(token)
            if found_plates:
                plates.extend(found_plates)
                # If there was unmatched garbage alongside valid plates, track as invalid too
                reconstructed = "".join(found_plates)
                if len(reconstructed) < len(token):
                    invalid_plates.append(token)
            else:
                invalid_plates.append(token)
                
    if not plates and not invalid_plates:
        flash('No valid plates found!', 'error')
        return redirect(url_for('plate.plates'))
    
    try:
        with DatabaseConnection() as db:
            # Get existing plates
            db.execute("SELECT license_plate FROM allowed_plates")
            existing_rows = db.fetchall()
            existing_plates = set(row['license_plate'] for row in existing_rows)
            
            # Get blacklisted plates
            db.execute("SELECT license_plate FROM blacklist_plates")
            blacklist_rows = db.fetchall()
            blacklisted_plates = set(row['license_plate'] for row in blacklist_rows)
            
            new_plates = []
            duplicates = []
            blacklisted_skipped = []
            
            for plate in plates:
                if plate in blacklisted_plates:
                    blacklisted_skipped.append(plate)
                elif plate not in existing_plates:
                    new_plates.append(plate)
                    existing_plates.add(plate)
                else:
                    duplicates.append(plate)
            
            # Insert new plates
            if new_plates:
                params_list = []
                failed_plates = []
                for plate in new_plates:
                    if len(plate) > 20:
                        failed_plates.append((plate, "value too long"))
                    else:
                        params_list.append((plate,))
                
                success_count = 0
                if params_list:
                    try:
                        db.cursor.executemany(
                            "INSERT INTO allowed_plates (license_plate) VALUES (%s) ON DUPLICATE KEY UPDATE license_plate = license_plate",
                            params_list
                        )
                        success_count = len(params_list)
                    except Exception as db_err:
                        # Fallback to single-insert in case of database constraints/failures
                        for (plate,) in params_list:
                            try:
                                db.execute("INSERT INTO allowed_plates (license_plate) VALUES (%s) ON DUPLICATE KEY UPDATE license_plate = license_plate", (plate,))
                                success_count += 1
                            except Exception as single_err:
                                failed_plates.append((plate, str(single_err)))
                
                if success_count > 0:
                    flash(f'Added {success_count} new plates successfully!', 'success')
                    # Broadcast reload signal to ANPR service for live updates
                    broadcast_reload_plates()
                    flash(f'plate list updated in ANPR system', 'info')
                
                if failed_plates:
                    error_details = ", ".join([f"{p[:15]}... ({err})" if len(p) > 15 else f"{p} ({err})" for p, err in failed_plates[:3]])
                    if len(failed_plates) > 3:
                        error_details += f" and {len(failed_plates) - 3} more"
                    flash(f'Failed to add some plates due to database errors: {error_details}', 'error')
            
            if blacklisted_skipped:
                flash(f"Skipped {len(blacklisted_skipped)} plates because they are in the blacklist: {', '.join(blacklisted_skipped[:5])}" + ("..." if len(blacklisted_skipped) > 5 else ""), "error")
            
            if duplicates:
                flash(f'{len(duplicates)} plates were already in the list', 'warning')
                
            if invalid_plates:
                # Truncate long invalid plate strings to prevent UI layout breakage
                truncated_invalids = []
                for p in invalid_plates:
                    if len(p) > 20:
                        truncated_invalids.append(p[:20] + '...')
                    else:
                        truncated_invalids.append(p)
                invalid_show = truncated_invalids[:5]
                invalid_msg = ", ".join(invalid_show)
                if len(invalid_plates) > 5:
                    invalid_msg += f" and {len(invalid_plates) - 5} more"
                flash(f'Skipped {len(invalid_plates)} invalid/too long plates: {invalid_msg}', 'error')
                
    except Exception as e:
        flash(f'Error adding plates: {str(e)}', 'error')
    
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

@plate_bp.route('/plates/blacklist/add', methods=['POST'])
@admin_required
def add_blacklist_plate():
    """Add plate to blacklist"""
    plate = request.form.get('plate', '').strip().upper()
    description = request.form.get('description', '').strip()
    from flask import session
    added_by = session.get('username') or 'Admin'
    
    if not plate:
        flash('Plate number is required!', 'error')
        return redirect(url_for('plate.plates'))

    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{2,3}[0-9]{4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{2}$')

    if not plate_pattern.match(plate):
        flash(
            'Invalid plate format! Expected 10 or 11 character format '
            '(e.g., GJ01AB1234 or 21BH1234AA)',
            'error'
        )
        return redirect(url_for('plate.plates'))
    
    try:
        with DatabaseConnection() as db:
            # Check if it exists in allowed plates
            db.execute("SELECT id FROM allowed_plates WHERE license_plate = %s", (plate,))
            if db.fetchone():
                flash(f'Plate {plate} is in the allowed list! Cannot add to blacklist.', 'error')
                return redirect(url_for('plate.plates'))
                
            # Check if it already exists in blacklist
            db.execute("SELECT id FROM blacklist_plates WHERE license_plate = %s", (plate,))
            existing = db.fetchone()
            
            if existing:
                flash(f'Plate {plate} is already in the blacklist!', 'warning')
            else:
                db.execute("INSERT INTO blacklist_plates (license_plate, description, added_by) VALUES (%s, %s, %s)", (plate, description, added_by))
                flash(f'Plate {plate} blacklisted successfully!', 'success')
                
                # Broadcast reload signal
                broadcast_reload_plates()
    except Exception as e:
        flash(f'Error blacklisting plate: {str(e)}', 'error')
    
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/blacklist/delete', methods=['POST'])
@admin_required
def delete_blacklist_plate():
    """Delete plate from blacklist"""
    plate = request.form.get('plate', '').strip().upper()
    
    if not plate:
        flash('Plate number is required!', 'error')
        return redirect(url_for('plate.plates'))
    
    try:
        with DatabaseConnection() as db:
            db.execute("DELETE FROM blacklist_plates WHERE license_plate = %s", (plate,))
            if db.cursor.rowcount > 0:
                flash(f'Plate {plate} removed from blacklist successfully!', 'success')
                broadcast_reload_plates()
            else:
                flash(f'Plate {plate} not found in blacklist!', 'error')
    except Exception as e:
        flash(f'Error deleting blacklisted plate: {str(e)}', 'error')
    
    return redirect(url_for('plate.plates'))

@plate_bp.route('/plates/blacklist/edit', methods=['POST'])
@admin_required
def edit_blacklist_plate():
    """Edit blacklisted plate"""
    old_plate = request.form.get('old_plate', '').strip().upper()
    new_plate = request.form.get('new_plate', '').strip().upper()
    description = request.form.get('description', '').strip()
    
    if not old_plate or not new_plate:
        flash('Both old and new plate numbers are required!', 'error')
        return redirect(url_for('plate.plates'))
        
    plate_pattern = re.compile(r'^[A-Z]{2}[0-9]{2}[A-Z]{2,3}[0-9]{4}$|^[0-9]{2}BH[0-9]{4}[A-Z]{2}$')
    if not plate_pattern.match(new_plate):
        flash(
            'Invalid plate format! Expected 10 or 11 character format '
            '(e.g., GJ01AB1234 or 21BH1234AA)',
            'error'
        )
        return redirect(url_for('plate.plates'))
        
    try:
        with DatabaseConnection() as db:
            # Check if new plate is in allowed list
            db.execute("SELECT id FROM allowed_plates WHERE license_plate = %s", (new_plate,))
            if db.fetchone():
                flash(f'Plate {new_plate} is in the allowed list! Cannot update to this plate.', 'error')
                return redirect(url_for('plate.plates'))
                
            db.execute("UPDATE blacklist_plates SET license_plate = %s, description = %s WHERE license_plate = %s", (new_plate, description, old_plate))
            if db.cursor.rowcount > 0:
                flash(f'Blacklisted Plate {old_plate} updated successfully!', 'success')
                broadcast_reload_plates()
            else:
                flash(f'Plate {old_plate} not found in blacklist!', 'error')
    except Exception as e:
        if 'Duplicate entry' in str(e):
            flash(f'Plate {new_plate} already exists in blacklist!', 'error')
        else:
            flash(f'Error updating blacklisted plate: {str(e)}', 'error')
            
    return redirect(url_for('plate.plates'))


