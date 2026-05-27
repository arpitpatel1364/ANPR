from flask import Blueprint, render_template, request, jsonify, send_file, flash, redirect, url_for
import os
import sys
import csv
from datetime import datetime, timedelta
import json
import tempfile

# Add parent directory to path for db_connection import
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db_connection import DatabaseConnection
from pdf_export import create_pdf_export

detection_bp = Blueprint('detection', __name__)

def load_detections():
    """Load detection data from MySQL database"""
    try:
        with DatabaseConnection() as db:
            query = """
                SELECT id, timestamp, license_plate, verification_status, access_granted,
                       detection_confidence, processing_time_ms, camera_source, frame_number,
                       detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM detections
                ORDER BY timestamp DESC
            """
            db.execute(query)
            rows = db.fetchall()
            
            # Convert to list of dicts compatible with pandas DataFrame format
            detections = []
            for row in rows:
                detections.append({
                    'id': row['id'],
                    'Timestamp': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if row['timestamp'] else '',
                    'License_Plate': row['license_plate'],
                    'Verification_Status': row['verification_status'],
                    'Access_Granted': row['access_granted'],
                    'Detection_Confidence': f"{row['detection_confidence']:.3f}",
                    'Processing_Time_MS': f"{row['processing_time_ms']:.2f}",
                    'Camera_Source': row['camera_source'],
                    'Frame_Number': row['frame_number'],
                    'Detection_Count': row['detection_count'],
                    'Log_Reason': row['log_reason'] or '',
                    'Image_Full_Annotated': row['image_full_annotated'] or '',
                    'bbox_x1': row['bbox_x1'],
                    'bbox_y1': row['bbox_y1'],
                    'bbox_x2': row['bbox_x2'],
                    'bbox_y2': row['bbox_y2']
                })
            
            return detections
    except Exception as e:
        flash(f'Error loading detections: {str(e)}', 'error')
        return []

@detection_bp.route('/detections')
def detections():
    """Detection history page"""
    # Get filter parameters
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'VERIFIED').strip()  # For dropdown display
    query_status = status_filter  # For database query
    # If user selects 'all', use empty string for query (show all)
    if query_status == 'all':
        query_status = ''
    camera_filter = request.args.get('camera', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    
    try:
        with DatabaseConnection() as db:
            # Build query with filters
            where_clauses = []
            params = []
            
            if search:
                where_clauses.append("license_plate LIKE %s")
                params.append(f"%{search}%")
            
            if query_status:  # Only add filter if query_status is not empty
                where_clauses.append("verification_status = %s")
                params.append(query_status)
            
            if camera_filter:
                where_clauses.append("camera_source LIKE %s")
                params.append(f"%{camera_filter}%")
            
            if date_from:
                where_clauses.append("DATE(timestamp) >= %s")
                params.append(date_from)
            
            if date_to:
                where_clauses.append("DATE(timestamp) <= %s")
                params.append(date_to)
            
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            
            # Get total count
            count_query = f"SELECT COUNT(*) as count FROM detections WHERE {where_sql}"
            db.execute(count_query, tuple(params) if params else None)
            result = db.fetchone()
            total_detections = result['count'] if result else 0
            
            # Get paginated results
            offset = (page - 1) * per_page
            query = f"""
                SELECT id, timestamp, license_plate, verification_status, access_granted,
                       detection_confidence, processing_time_ms, camera_source, frame_number,
                       detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM detections
                WHERE {where_sql}
                ORDER BY timestamp DESC
                LIMIT %s OFFSET %s
            """
            params.extend([per_page, offset])
            db.execute(query, tuple(params))
            rows = db.fetchall()
            
            # Convert to dict format
            detections = []
            for row in rows:
                detections.append({
                    'id': row['id'],
                    'Timestamp': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if row['timestamp'] else '',
                    'License_Plate': row['license_plate'],
                    'Verification_Status': row['verification_status'],
                    'Access_Granted': row['access_granted'],
                    'Detection_Confidence': f"{row['detection_confidence']:.3f}",
                    'Processing_Time_MS': f"{row['processing_time_ms']:.2f}",
                    'Camera_Source': row['camera_source'],
                    'Frame_Number': row['frame_number'],
                    'Detection_Count': row['detection_count'],
                    'Log_Reason': row['log_reason'] or '',
                    'Image_Full_Annotated': row['image_full_annotated'] or '',
                    'bbox_x1': row['bbox_x1'],
                    'bbox_y1': row['bbox_y1'],
                    'bbox_x2': row['bbox_x2'],
                    'bbox_y2': row['bbox_y2']
                })
            
            # Get statistics
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'VERIFIED'")
            result = db.fetchone()
            verified_detections = result['count'] if result else 0
            
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'NOT_VERIFIED'")
            result = db.fetchone()
            unverified_detections = result['count'] if result else 0
            
            # Get unique cameras
            db.execute("SELECT DISTINCT camera_source FROM detections ORDER BY camera_source")
            camera_rows = db.fetchall()
            cameras = [row['camera_source'] for row in camera_rows]
            
            verification_rate = (verified_detections / total_detections * 100) if total_detections > 0 else 0
            total_pages = (total_detections + per_page - 1) // per_page
            
    except Exception as e:
        flash(f'Error loading detections: {str(e)}', 'error')
        detections = []
        total_detections = 0
        verified_detections = 0
        unverified_detections = 0
        verification_rate = 0
        total_pages = 0
        cameras = []
    
    return render_template('detections.html', 
                         detections=detections,
                         total_detections=total_detections,
                         verified_detections=verified_detections,
                         unverified_detections=unverified_detections,
                         verification_rate=round(verification_rate, 1),
                         total_pages=total_pages,
                         current_page=page,
                         per_page=per_page,
                         search=search,
                         status_filter=status_filter,
                         camera_filter=camera_filter,
                         date_from=date_from,
                         date_to=date_to,
                         cameras=cameras)

@detection_bp.route('/detections/export')
def export_detections():
    """Export detections to CSV"""
    # Apply same filters as in detections page
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'VERIFIED').strip()  # For dropdown display
    query_status = status_filter  # For database query
    # If user selects 'all', use empty string for query (show all)
    if query_status == 'all':
        query_status = ''
    camera_filter = request.args.get('camera', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    
    try:
        with DatabaseConnection() as db:
            # Build query with filters
            where_clauses = []
            params = []
            
            if search:
                where_clauses.append("license_plate LIKE %s")
                params.append(f"%{search}%")
            
            if query_status:  # Only add filter if query_status is not empty
                where_clauses.append("verification_status = %s")
                params.append(query_status)
            
            if camera_filter:
                where_clauses.append("camera_source LIKE %s")
                params.append(f"%{camera_filter}%")
            
            if date_from:
                where_clauses.append("DATE(timestamp) >= %s")
                params.append(date_from)
            
            if date_to:
                where_clauses.append("DATE(timestamp) <= %s")
                params.append(date_to)
            
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            
            query = f"""
                SELECT timestamp, license_plate, verification_status, access_granted,
                       detection_confidence, processing_time_ms, camera_source, frame_number,
                       detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM detections
                WHERE {where_sql}
                ORDER BY timestamp DESC
            """
            db.execute(query, tuple(params) if params else None)
            rows = db.fetchall()
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'detections_export_{timestamp}.csv'
        
        # Save to temporary file
        import tempfile
        temp_fd, temp_path = tempfile.mkstemp(suffix='.csv', prefix='detections_')
        os.close(temp_fd)  # Close fd immediately to avoid leak; file will be opened by path below
        
        with open(temp_path, 'w', newline='', encoding='utf-8') as f:
            fieldnames = ['Timestamp', 'License_Plate', 'Verification_Status', 'Access_Granted',
                         'Detection_Confidence', 'Processing_Time_MS', 'Camera_Source', 'Frame_Number',
                         'Detection_Count', 'Log_Reason', 'Image_Full_Annotated', 'bbox_x1', 'bbox_y1', 'bbox_x2', 'bbox_y2']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in rows:
                writer.writerow({
                    'Timestamp': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if row['timestamp'] else '',
                    'License_Plate': row['license_plate'],
                    'Verification_Status': row['verification_status'],
                    'Access_Granted': row['access_granted'],
                    'Detection_Confidence': f"{row['detection_confidence']:.3f}",
                    'Processing_Time_MS': f"{row['processing_time_ms']:.2f}",
                    'Camera_Source': row['camera_source'],
                    'Frame_Number': str(row['frame_number']),
                    'Detection_Count': str(row['detection_count']),
                    'Log_Reason': row['log_reason'] or '',
                    'Image_Full_Annotated': row['image_full_annotated'] or '',
                    'bbox_x1': row['bbox_x1'] if row['bbox_x1'] is not None else '',
                    'bbox_y1': row['bbox_y1'] if row['bbox_y1'] is not None else '',
                    'bbox_x2': row['bbox_x2'] if row['bbox_x2'] is not None else '',
                    'bbox_y2': row['bbox_y2'] if row['bbox_y2'] is not None else ''
                })
        
        return send_file(temp_path, as_attachment=True, download_name=filename)
        
    except Exception as e:
        flash(f'Error exporting detections: {str(e)}', 'error')
        return redirect(url_for('detection.detections'))

@detection_bp.route('/detections/export/pdf')
def export_detections_pdf():
    """Export detections to PDF with images"""
    # Apply same filters as in detections page
    search = request.args.get('search', '').strip()
    status_filter = request.args.get('status', 'VERIFIED').strip()  # For dropdown display
    query_status = status_filter  # For database query
    # If user selects 'all', use empty string for query (show all)
    if query_status == 'all':
        query_status = ''
    camera_filter = request.args.get('camera', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    include_images = request.args.get('images', 'true').lower() == 'true'
    
    try:
        with DatabaseConnection() as db:
            # Build query with filters
            where_clauses = []
            params = []
            
            if search:
                where_clauses.append("license_plate LIKE %s")
                params.append(f"%{search}%")
            
            if query_status:  # Only add filter if query_status is not empty
                where_clauses.append("verification_status = %s")
                params.append(query_status)
            
            if camera_filter:
                where_clauses.append("camera_source LIKE %s")
                params.append(f"%{camera_filter}%")
            
            if date_from:
                where_clauses.append("DATE(timestamp) >= %s")
                params.append(date_from)
            
            if date_to:
                where_clauses.append("DATE(timestamp) <= %s")
                params.append(date_to)
            
            where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
            
            query = f"""
                SELECT timestamp, license_plate, verification_status, access_granted,
                       detection_confidence, processing_time_ms, camera_source, frame_number,
                       detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM detections
                WHERE {where_sql}
                ORDER BY timestamp DESC
            """
            db.execute(query, tuple(params) if params else None)
            rows = db.fetchall()
        
        # Convert to dict format
        detections = []
        for row in rows:
            detections.append({
                'Timestamp': row['timestamp'].strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if row['timestamp'] else '',
                'License_Plate': row['license_plate'],
                'Verification_Status': row['verification_status'],
                'Access_Granted': row['access_granted'],
                'Detection_Confidence': f"{row['detection_confidence']:.3f}",
                'Processing_Time_MS': f"{row['processing_time_ms']:.2f}",
                'Camera_Source': row['camera_source'],
                'Frame_Number': str(row['frame_number']),
                'Detection_Count': str(row['detection_count']),
                'Log_Reason': row['log_reason'] or '',
                'Image_Full_Annotated': row['image_full_annotated'] or '',
                'bbox_x1': row['bbox_x1'],
                'bbox_y1': row['bbox_y1'],
                'bbox_x2': row['bbox_x2'],
                'bbox_y2': row['bbox_y2']
            })
        
        # Generate filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'detections_export_{timestamp}.pdf'
        
        # Create temporary PDF file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf', prefix='detections_')
        os.close(temp_fd)
        
        # Generate PDF
        create_pdf_export(detections, temp_path, include_images=include_images)
        
        return send_file(temp_path, as_attachment=True, download_name=filename, mimetype='application/pdf')
        
    except Exception as e:
        flash(f'Error exporting PDF: {str(e)}', 'error')
        return redirect(url_for('detection.detections'))

@detection_bp.route('/detections/stats')
def detection_stats():
    """Get detection statistics"""
    try:
        with DatabaseConnection() as db:
            # Basic stats
            db.execute("SELECT COUNT(*) as count FROM detections")
            result = db.fetchone()
            total_detections = result['count'] if result else 0
            
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'VERIFIED'")
            result = db.fetchone()
            verified_detections = result['count'] if result else 0
            
            db.execute("SELECT COUNT(*) as count FROM detections WHERE verification_status = 'NOT_VERIFIED'")
            result = db.fetchone()
            unverified_detections = result['count'] if result else 0
            
            verification_rate = (verified_detections / total_detections * 100) if total_detections > 0 else 0
            
            # Today's detections
            today = datetime.now().date()
            db.execute("SELECT COUNT(*) as count FROM detections WHERE DATE(timestamp) = %s", (today,))
            result = db.fetchone()
            today_detections = result['count'] if result else 0
            
            # Unique plates
            db.execute("SELECT COUNT(DISTINCT license_plate) as count FROM detections")
            result = db.fetchone()
            unique_plates = result['count'] if result else 0
            
            # Detections by camera
            db.execute("SELECT camera_source, COUNT(*) as count FROM detections GROUP BY camera_source")
            camera_rows = db.fetchall()
            camera_stats = {row['camera_source']: row['count'] for row in camera_rows}
            
            # Detections by hour (last 24 hours)
            db.execute("""
                SELECT HOUR(timestamp) as hour, COUNT(*) as count 
                FROM detections 
                WHERE timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
                GROUP BY HOUR(timestamp)
                ORDER BY hour
            """)
            hourly_rows = db.fetchall()
            hourly_stats = {row['hour']: row['count'] for row in hourly_rows}
        
        return jsonify({
            'total_detections': total_detections,
            'verified_detections': verified_detections,
            'unverified_detections': unverified_detections,
            'verification_rate': round(verification_rate, 1),
            'today_detections': today_detections,
            'unique_plates': unique_plates,
            'camera_stats': camera_stats,
            'hourly_stats': hourly_stats
        })
    except Exception as e:
        return jsonify({
            'total_detections': 0,
            'verified_detections': 0,
            'unverified_detections': 0,
            'verification_rate': 0,
            'today_detections': 0,
            'unique_plates': 0,
            'camera_stats': {},
            'hourly_stats': {},
            'error': str(e)
        }), 500

@detection_bp.route('/detections/image/<path:filename>')
def get_detection_image(filename):
    """Serve detection image"""
    image_path = os.path.join('static/images/verified_plates', filename)
    
    if os.path.exists(image_path):
        return send_file(image_path)
    else:
        # Return a placeholder image or 404
        return jsonify({'error': 'Image not found'}), 404

@detection_bp.route('/detections/delete/<int:detection_id>', methods=['POST'])
def delete_detection(detection_id):
    """Delete a specific detection by ID"""
    try:
        with DatabaseConnection() as db:
            db.execute("DELETE FROM detections WHERE id = %s", (detection_id,))
            if db.cursor.rowcount > 0:
                flash('Detection deleted successfully!', 'success')
            else:
                flash('Detection not found!', 'error')
        
    except Exception as e:
        flash(f'Error deleting detection: {str(e)}', 'error')
    
    return redirect(url_for('detection.detections'))
