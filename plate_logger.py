import os
import json
import time
from datetime import datetime
from typing import List, Dict, Optional
import threading
import queue
from db_connection import get_connection, DatabaseConnection, execute_query, initialize_database
from rapidfuzz import process, fuzz

class PlateMatcher:
    def __init__(self, allowed_plates):
        self.allowed_set = set(allowed_plates)  # O(1) lookup
        self.allowed_list = list(allowed_plates)

        # Prefix index
        self.prefix_map = {}
        for plate in allowed_plates:
            prefix = plate[:4]  # e.g. HR26
            self.prefix_map.setdefault(prefix, []).append(plate)

        self.fuzzy_cache = {}
        self.last_checked = {}
        self.COOLDOWN_SEC = 2
        self.THRESHOLD = 80

    def match_plate(self, detected_plate, confidence=1.0):
        now = time.time()
        
        # 1. Exact match
        if detected_plate in self.allowed_set:
            return detected_plate, "EXACT"

        # (Skipping confidence > 0.9 check because LPRNet currently hardcodes confidence to 1.0)
        
        # 2. Cooldown
        if detected_plate in self.last_checked:
            if now - self.last_checked[detected_plate] < self.COOLDOWN_SEC:
                return None, "SKIPPED_COOLDOWN"

        self.last_checked[detected_plate] = now

        # 3. Cache hit
        if detected_plate in self.fuzzy_cache:
            return self.fuzzy_cache[detected_plate], "CACHED"

        # 4. Prefix filtering
        prefix = detected_plate[:4]
        candidates = self.prefix_map.get(prefix, [])

        if not candidates:
            return None, "NO_CANDIDATES"

        # 5. Fast fuzzy match
        match, score, _ = process.extractOne(
            detected_plate,
            candidates,
            scorer=fuzz.ratio
        )

        if score >= self.THRESHOLD:
            self.fuzzy_cache[detected_plate] = match
            return match, f"FUZZY_{score}"

        return None, "NO_MATCH"

global_matcher = PlateMatcher([])


_PLATE_CACHE = {}         # { plate: (is_allowed, timestamp) }
_CACHE_TTL = 30           # seconds
_cache_lock = threading.Lock()

def is_plate_allowed(plate: str) -> bool:
    """
    Check if a license plate is in the allowed list using Hybrid Cache.
    """
    try:
        clean_plate = plate.replace(" ", "").upper()
        current_time = time.time()
        
        # Check cache
        with _cache_lock:
            if clean_plate in _PLATE_CACHE:
                is_allowed, timestamp = _PLATE_CACHE[clean_plate]
                if current_time - timestamp < _CACHE_TTL:
                    return is_allowed
        
        # Query database directly if not in cache
        with DatabaseConnection() as db:
            db.execute("SELECT id FROM allowed_plates WHERE license_plate = %s LIMIT 1", (clean_plate,))
            result = db.fetchone()
            is_allowed = result is not None
            
        # Update cache
        with _cache_lock:
            _PLATE_CACHE[clean_plate] = (is_allowed, current_time)
            
        return is_allowed
    except Exception as e:
        print(f"⚠️ Error checking plate {plate}: {e}")
        return False

class PlateLogger:
    """
    MySQL Logger for ANPR detections with verification against allowed plates
    Optimized to prevent duplicate logging and improve performance
    """
    
    def __init__(self, csv_file: str = None, allowed_plates_file: str = "allowed_plates.json", 
                 dedup_window: int = 30, max_confidence_threshold: float = 0.8):
        # Keep csv_file parameter for backward compatibility but don't use it
        self.allowed_plates_file = allowed_plates_file
        self.allowed_plates = set()
        self.lock = threading.Lock()
        
        # Deduplication settings
        self.dedup_window = dedup_window  # Seconds between logging same plate
        self.max_confidence_threshold = max_confidence_threshold  # Only log high-confidence detections
        
        # Track recent detections to prevent duplicates
        self.recent_detections = {}  # plate -> (timestamp, confidence, count)
        
        # Async Database worker
        self.db_queue = queue.Queue()
        self.db_worker_thread = threading.Thread(target=self._database_worker, daemon=True)
        self.db_worker_thread.start()
        
        # Active detection counter
        self.active_detections_count = 0
        
        # Initialize database connection
        self.init_database()
        
        # Load allowed plates from database (fallback to JSON if needed)
        self.load_allowed_plates()
        
        # Start background refresh thread for cache
        self.refresh_thread = threading.Thread(target=self._refresh_plates_worker, daemon=True)
        self.refresh_thread.start()
        
    def _refresh_plates_worker(self):
        """Background thread to refresh the allowed plates cache every 60s"""
        while True:
            try:
                time.sleep(60)
                with DatabaseConnection() as db:
                    db.execute("SELECT license_plate FROM allowed_plates")
                    rows = db.fetchall()
                    
                new_cache = {}
                curr_time = time.time()
                for r in rows:
                    new_cache[r['license_plate']] = (True, curr_time)
                    
                with _cache_lock:
                    global _PLATE_CACHE, global_matcher
                    _PLATE_CACHE.clear()
                    _PLATE_CACHE.update(new_cache)
                    global_matcher = PlateMatcher(new_cache.keys())
            except Exception as e:
                print(f"⚠️ Error refreshing plate cache: {e}")
    
    def _database_worker(self):
        """Dedicated background thread to handle database writes asynchronously"""
        while True:
            try:
                task = self.db_queue.get()
                if task is None:
                    break
                
                query, params, clean_plate, status_icon, verification_status, access_granted, reason = task
                
                try:
                    with DatabaseConnection() as db:
                        db.execute(query, params)
                    print(f"{status_icon} Plate {clean_plate}: {verification_status} - Access: {access_granted} - LOGGED ({reason})")
                except Exception as e:
                    print(f"❌ Error logging detection to database (async): {e}")
                    print(f"{status_icon} Plate {clean_plate}: {verification_status} - Access: {access_granted} - LOGGED (but DB error)")
                
                self.db_queue.task_done()
            except Exception as e:
                print(f"❌ Error in database worker thread: {e}")
    
    def init_database(self):
        """Initialize database connection and tables"""
        try:
            # Try to initialize database (creates tables if they don't exist)
            initialize_database()
        except Exception as e:
            print(f"Warning: Database initialization issue: {e}")
    
    def load_allowed_plates(self):
        """
        Get count of allowed plates from database (for informational purposes).
        Verification is now done via direct database queries, so no need to maintain in-memory copy.
        """
        try:
            # Just get a count for the startup message
            query = "SELECT COUNT(*) as count FROM allowed_plates"
            result = execute_query(query, fetch=True)
            
            if result:
                plates_count = result[0].get('count', 0) if result else 0
                print(f"✅ Database ready: {plates_count} allowed license plates available for verification")
            else:
                print(f"⚠️ No plates found in database")
                    
        except Exception as e:
            print(f"⚠️ Could not count plates in database: {e}")
    
    def _import_plates_to_db(self, plates: List[str]):
        """Import plates from list to database"""
        try:
            with DatabaseConnection() as db:
                for plate in plates:
                    clean_plate = plate.replace(" ", "").upper()
                    query = "INSERT IGNORE INTO allowed_plates (license_plate) VALUES (%s)"
                    db.execute(query, (clean_plate,))
        except Exception as e:
            print(f"Warning: Error importing plates to database: {e}")
    
    def reload_allowed_plates(self):
        """
        Reload allowed plates information (for compatibility).
        Since verification now queries the database directly, this is mainly for informational updates.
        """
        self.load_allowed_plates()
    
    def verify_plate(self, plate: str) -> Dict[str, any]:
        """
        Verify if a license plate is in the allowed list
        
        Args:
            plate (str): License plate to verify
            
        Returns:
            Dict containing verification results
        """
        # Clean the plate (remove spaces, convert to uppercase)
        clean_plate = plate.replace(" ", "").upper()
        
        # Check if plate is allowed by querying database directly (always current)
        is_allowed = is_plate_allowed(clean_plate)
        
        # Determine verification status
        if is_allowed:
            verification_status = "VERIFIED"
            access_granted = "YES"
        else:
            verification_status = "NOT_VERIFIED"
            access_granted = "NO"
        
        return {
            'is_allowed': is_allowed,
            'verification_status': verification_status,
            'access_granted': access_granted,
            'clean_plate': clean_plate
        }
    
    def should_log_detection(self, plate: str, confidence: float) -> tuple[bool, str]:
        """
        Determine if a detection should be logged based on deduplication rules
        
        Args:
            plate (str): License plate to check
            confidence (float): Detection confidence score
            
        Returns:
            tuple: (should_log, reason)
        """
        current_time = time.time()
        clean_plate = plate.replace(" ", "").upper()
        
        # Check if we have a recent detection of this plate
        if clean_plate in self.recent_detections:
            last_time, last_confidence, count = self.recent_detections[clean_plate]
            time_diff = current_time - last_time
            
            # If within dedup window, don't log unless confidence is significantly higher
            if time_diff < self.dedup_window:
                # Only log if confidence is much higher (indicating better detection)
                if confidence > last_confidence + 0.1:  # 10% improvement threshold
                    # Update with new higher confidence detection
                    self.recent_detections[clean_plate] = (current_time, confidence, count + 1)
                    return True, f"Higher confidence detection ({confidence:.2f} vs {last_confidence:.2f})"
                else:
                    # Update count but don't log
                    self.recent_detections[clean_plate] = (last_time, last_confidence, count + 1)
                    return False, f"Duplicate within {self.dedup_window}s window (count: {count + 1})"
        
        # Check confidence threshold
        if confidence < self.max_confidence_threshold:
            return False, f"Low confidence ({confidence:.2f} < {self.max_confidence_threshold})"
        
        # New detection or outside dedup window - log it
        self.recent_detections[clean_plate] = (current_time, confidence, 1)
        self.active_detections_count += 1
        return True, "New detection or outside dedup window"
    
    def cleanup_old_detections(self):
        """Remove old detections from memory to prevent memory bloat"""
        current_time = time.time()
        old_plates = []
        
        for plate, (timestamp, confidence, count) in self.recent_detections.items():
            if current_time - timestamp > self.dedup_window * 2:  # Keep 2x dedup window
                old_plates.append(plate)
        
        for plate in old_plates:
            del self.recent_detections[plate]
            self.active_detections_count = max(0, self.active_detections_count - 1)
    
    def log_detection(self, 
                     plate: str, 
                     detection_confidence: float = 0.0,
                     processing_time_ms: float = 0.0,
                     camera_source: str = "unknown",
                     frame_number: int = 0,
                     image_full_annotated: str | None = None,
                     bbox_x1: int | None = None,
                     bbox_y1: int | None = None,
                     bbox_x2: int | None = None,
                     bbox_y2: int | None = None):
        """
        Log a license plate detection to CSV with intelligent deduplication
        
        Args:
            plate (str): Detected license plate
            detection_confidence (float): Confidence score from detection
            processing_time_ms (float): Time taken to process frame
            camera_source (str): Source of the video (webcam, RTSP, etc.)
            frame_number (int): Frame number when detection occurred
        """
        try:
            # Check if we should log this detection
            should_log, reason = self.should_log_detection(plate, detection_confidence)
            
            # Verify the plate
            verification = self.verify_plate(plate)
            
            # Always print detection info (for monitoring)
            status_icon = "✅" if verification['is_allowed'] else "❌"
            clean_plate = verification['clean_plate']
            
            if should_log:
                # Get current timestamp
                timestamp = datetime.now()
                
                # Get detection count for this plate
                detection_count = self.recent_detections.get(clean_plate, (0, 0, 0))[2]
                
                # Insert into MySQL database via Async Queue
                try:
                    query = """
                        INSERT INTO detections 
                        (timestamp, license_plate, verification_status, access_granted, 
                         detection_confidence, processing_time_ms, camera_source, frame_number, 
                         detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    params = (
                        timestamp,
                        clean_plate,
                        verification['verification_status'],
                        verification['access_granted'],
                        detection_confidence,
                        processing_time_ms,
                        camera_source,
                        frame_number,
                        detection_count,
                        reason,
                        image_full_annotated or None,
                        bbox_x1,
                        bbox_y1,
                        bbox_x2,
                        bbox_y2
                    )
                    
                    self.db_queue.put((
                        query, params, clean_plate, status_icon, 
                        verification['verification_status'], 
                        verification['access_granted'], reason
                    ))
                except Exception as e:
                    print(f"❌ Error queuing detection to database: {e}")
            else:
                # Just print detection info without logging
                detection_count = self.recent_detections.get(clean_plate, (0, 0, 0))[2]
                print(f"{status_icon} Plate {clean_plate}: {verification['verification_status']} - Access: {verification['access_granted']} - SKIPPED ({reason}) - Count: {detection_count}")
            
            # Periodic cleanup of old detections
            if frame_number % 100 == 0:  # Cleanup every 100 frames
                self.cleanup_old_detections()
                
            return should_log
            
        except Exception as e:
            print(f"Error logging detection: {e}")
            return False
    
    def get_statistics(self) -> Dict[str, any]:
        """Get statistics from the database and memory"""
        try:
            # Get in-memory statistics (current session)
            total_detection_count = sum(count for _, _, count in self.recent_detections.values())
            
            # Get database statistics
            db_stats = {"total_detections": 0, "verified_plates": 0, "unverified_plates": 0, "unique_plates": 0}
            
            try:
                with DatabaseConnection() as db:
                    # Execute single aggregation query instead of sequential queries
                    db.execute("""
                        SELECT 
                            COUNT(*) as total,
                            SUM(verification_status = 'VERIFIED') as verified,
                            SUM(verification_status = 'NOT_VERIFIED') as unverified,
                            COUNT(DISTINCT license_plate) as unique_plates
                        FROM detections
                    """)
                    result = db.fetchone()
                    if result:
                        db_stats['total_detections'] = result['total'] or 0
                        db_stats['verified_plates'] = result['verified'] or 0
                        db_stats['unverified_plates'] = result['unverified'] or 0
                        db_stats['unique_plates'] = result['unique_plates'] or 0
            except Exception as db_e:
                print(f"Warning: Error getting database statistics: {db_e}")
            
            # Calculate verification rate
            total_db = db_stats['total_detections']
            verification_rate = f"{(db_stats['verified_plates']/total_db*100):.1f}%" if total_db > 0 else "0%"
            
            return {
                'csv_detections': db_stats['total_detections'],  # Keep key name for compatibility
                'verified_plates': db_stats['verified_plates'],
                'unverified_plates': db_stats['unverified_plates'],
                'unique_plates': db_stats['unique_plates'],
                'verification_rate': verification_rate,
                'active_detections': self.active_detections_count,
                'total_detection_count': total_detection_count,
                'dedup_window': self.dedup_window,
                'confidence_threshold': self.max_confidence_threshold
            }
            
        except Exception as e:
            return {"error": f"Error reading statistics: {e}"}
    
    def get_realtime_summary(self) -> Dict[str, any]:
        """Get real-time summary of current detections (without CSV access)"""
        try:
            current_time = time.time()
            active_detections = 0
            total_detection_count = 0
            verified_count = 0
            unverified_count = 0
            
            for plate, (timestamp, confidence, count) in self.recent_detections.items():
                if current_time - timestamp < self.dedup_window * 2:
                    active_detections += 1
                    total_detection_count += count
                    
                    # Check if this plate is verified
                    if plate in self.allowed_plates:
                        verified_count += 1
                    else:
                        unverified_count += 1
            
            return {
                'active_detections': active_detections,
                'total_detection_count': total_detection_count,
                'verified_count': verified_count,
                'unverified_count': unverified_count,
                'dedup_window': self.dedup_window,
                'confidence_threshold': self.max_confidence_threshold
            }
            
        except Exception as e:
            return {"error": f"Error getting real-time summary: {e}"}
    
    def search_plate(self, plate: str) -> List[Dict[str, str]]:
        """Search for a specific license plate in the database"""
        try:
            clean_plate = plate.replace(" ", "").upper()
            
            with DatabaseConnection() as db:
                query = """
                    SELECT timestamp, license_plate, verification_status, access_granted,
                           detection_confidence, processing_time_ms, camera_source, frame_number,
                           detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                    FROM detections
                    WHERE license_plate = %s
                    ORDER BY timestamp DESC
                    LIMIT 100
                """
                db.execute(query, (clean_plate,))
                rows = db.fetchall()
                
                # Convert to dict format compatible with old CSV format
                results = []
                for row in rows:
                    results.append({
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
                        'Bbox_X1': row['bbox_x1'],
                        'Bbox_Y1': row['bbox_y1'],
                        'Bbox_X2': row['bbox_x2'],
                        'Bbox_Y2': row['bbox_y2']
                    })
                
                return results
            
        except Exception as e:
            print(f"Error searching for plate: {e}")
            return []
    
    def export_filtered_log(self, output_file: str, verification_status: Optional[str] = None, date_filter: Optional[str] = None):
        """
        Export filtered log data to a CSV file (from database)
        
        Args:
            output_file (str): Output CSV filename
            verification_status (str): Filter by verification status ('VERIFIED', 'NOT_VERIFIED')
            date_filter (str): Filter by date (YYYY-MM-DD format)
        """
        try:
            import csv
            
            # Build query with filters
            query = """
                SELECT timestamp, license_plate, verification_status, access_granted,
                       detection_confidence, processing_time_ms, camera_source, frame_number,
                       detection_count, log_reason, image_full_annotated, bbox_x1, bbox_y1, bbox_x2, bbox_y2
                FROM detections
                WHERE 1=1
            """
            params = []
            
            if verification_status:
                query += " AND verification_status = %s"
                params.append(verification_status)
            
            if date_filter:
                query += " AND DATE(timestamp) = %s"
                params.append(date_filter)
            
            query += " ORDER BY timestamp DESC"
            
            # Fetch data from database
            with DatabaseConnection() as db:
                db.execute(query, tuple(params) if params else None)
                rows = db.fetchall()
            
            # Write to CSV
            if rows:
                fieldnames = ['Timestamp', 'License_Plate', 'Verification_Status', 'Access_Granted',
                            'Detection_Confidence', 'Processing_Time_MS', 'Camera_Source', 'Frame_Number',
                            'Detection_Count', 'Log_Reason', 'Image_Full_Annotated', 'Bbox_X1', 'Bbox_Y1', 'Bbox_X2', 'Bbox_Y2']
                
                with open(output_file, 'w', newline='', encoding='utf-8') as f:
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
                            'Image_Full_Annotated': row['image_full_annotated'] or '',
                            'Bbox_X1': row['bbox_x1'],
                            'Bbox_Y1': row['bbox_y1'],
                            'Bbox_X2': row['bbox_x2'],
                            'Bbox_Y2': row['bbox_y2']
                        })
                
                print(f"✅ Exported {len(rows)} rows to {output_file}")
            else:
                print(f"⚠️ No rows found matching filters")
            
        except Exception as e:
            print(f"❌ Error exporting filtered log: {e}")

# Example usage and testing
if __name__ == "__main__":
    # Test the logger
    logger = PlateLogger()
    
    # Test logging some detections
    logger.log_detection("AB12CD3456", 0.95, 150.5, "webcam", 100)
    logger.log_detection("UNKNOWN123", 0.87, 120.3, "rtsp", 101)
    logger.log_detection("XY98ZW7890", 0.92, 180.7, "webcam", 102)
    
    # Get statistics
    stats = logger.get_statistics()
    print("\nStatistics:", stats)
    
    # Search for a specific plate
    results = logger.search_plate("AB12CD3456")
    print(f"\nSearch results for AB12CD3456: {len(results)} entries")
    
    # Export verified plates only
    logger.export_filtered_log("verified_plates.csv", verification_status="VERIFIED")
