# src/core/database.py
import json
import logging
import sqlite3
import uuid
from datetime import datetime

logger = logging.getLogger('vibe_manager')  # Use the main logger


class DatabaseManager:
    def __init__(self, db_path = 'karaoke_library.db', config_manager = None):
        self.db_path = db_path
        self.config_manager = config_manager
        # Removed _connection and _lock
        self.initialize_database()

    # Removed get_connection and close_connection. Connections are handled locally.

    def initialize_database(self):
        """Initialize the database with the required tables."""
        logger.debug("Initializing database tables if they do not exist.")
        # Use 'with' statement for automatic resource management
        try:
            with sqlite3.connect(self.db_path, timeout=10) as conn:  # Increased timeout
                cursor = conn.cursor()

                # Songs table
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS purchased_songs (
                        song_id TEXT PRIMARY KEY,
                        artist TEXT,
                        artist_url TEXT,
                        title TEXT,
                        title_url TEXT,
                        order_date TEXT,
                        download_url TEXT,
                        file_path TEXT,
                        downloaded INTEGER DEFAULT 0,
                        extracted INTEGER DEFAULT 0
                    )
                ''')

                # New Operation logs table schema with UUID for ID
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS operation_logs (
                        id TEXT PRIMARY KEY,  -- Explicitly set ID column type to TEXT
                        operation TEXT,
                        start_time TEXT,
                        end_time TEXT,
                        status TEXT,
                        details TEXT
                    )
                ''')

                # Legacy operation logs table (keeping for old logs, can be removed later)
                # Renamed table to avoid conflict
                cursor.execute('''
                           CREATE TABLE IF NOT EXISTS legacy_operation_logs_old (
                               timestamp TEXT,
                               operation TEXT,
                               details TEXT,
                               status TEXT
                           )
                       ''')
                conn.commit()

        except Exception as e:
            logger.exception("Error initializing database")  # Log exception.
            
            raise  # Re-raise.  Critical error.  # No need for explicit close, the with statement handles it.

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def get_last_song_id(self):
        """Get the last song ID from the database by order_date."""
        try:
            with self._get_connection() as conn:  # Use context manager for connection and cursor
                cursor = conn.cursor()
                cursor.execute("SELECT song_id FROM purchased_songs ORDER BY order_date DESC LIMIT 1")
                result = cursor.fetchone()
            return result [0] if result else None
        except Exception as e:
            logger.exception("Failed to get the last song ID.")
            raise  # Always re-raise after capturing

    def save_song(self, song):
        """Save a new song to the database with validation."""
        if not song or not song.get("song_id"):
            raise ValueError("Song data is missing or invalid")
            
        logger.debug(f"Saving new song to database: {song['song_id']}")
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Validate required fields
                required_fields = ["song_id", "artist", "title"]
                for field in required_fields:
                    if not song.get(field):
                        logger.warning(f"Missing required field '{field}' for song {song.get('song_id')}")
                        song[field] = song.get(field, "Unknown")

                file_paths = song.get("file_path", "")
                if isinstance(file_paths, str):
                    file_paths = [file_paths] if file_paths else []

                cursor.execute('''
                    INSERT OR REPLACE INTO purchased_songs (
                        song_id, artist, artist_url, title, title_url,
                        order_date, download_url, file_path, downloaded, extracted
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    song["song_id"], 
                    song.get("artist", "Unknown"), 
                    song.get("artist_url", ""), 
                    song.get("title", "Unknown"), 
                    song.get("title_url", ""),
                    song.get("order_date"), 
                    song.get("download_url", ""), 
                    json.dumps(file_paths), 
                    song.get("downloaded", 0),
                    song.get("extracted", 0)
                ))
                conn.commit()
                logger.debug(f"Successfully saved song: {song['song_id']}")
                
        except Exception as e:
            logger.exception(f"Failed to save song {song.get('song_id', 'Unknown ID')}: {e}")
            raise

    def update_song(self, song):
        """Update an existing song in the database."""
        logger.debug(f"Updating song in database: {song}")
        try:
            with self._get_connection() as conn:  # Use context manager
                cursor = conn.cursor()

                file_paths = song.get("file_path", "")
                if isinstance(file_paths, str):
                    file_paths = [file_paths] if file_paths else []

                cursor.execute('''
                UPDATE purchased_songs SET
                    artist = ?, artist_url = ?, title = ?, title_url = ?,
                    order_date = ?, download_url = ?, file_path = ?, downloaded = ?, extracted = ?
                WHERE song_id = ?
            ''', (song ["artist"], song ["artist_url"], song ["title"], song ["title_url"], song ["order_date"],
                  song ["download_url"], json.dumps(file_paths), song.get("downloaded", 0), song.get("extracted", 0),
                  song ["song_id"]))
                conn.commit()
        except Exception as e:
            logger.exception(f"Error updating song: {song.get('song_id', 'Unknown ID')}")
            raise

    def get_all_songs(self):
        """Get all songs from the database."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM purchased_songs")
                return cursor.fetchall()

        except Exception as e:
            logger.exception("Failed to get all songs")
            raise

    def song_exists(self, song_id):
        """Check if a song exists in the database and return the downloaded flag if it does."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT downloaded FROM purchased_songs WHERE song_id = ?", (song_id,))
                result = cursor.fetchone()
            return {"downloaded": result [0]} if result is not None else None
        except Exception as e:
            logger.exception(f"Failed to check the song exists: {song_id}")
            raise

    def clear_database(self):
        """Clears the 'purchased_songs' table in the database."""
        logger.warning("Clearing entire purchased_songs table.")
        try:
            with self._get_connection() as conn:  # Use context manager
                cursor = conn.cursor()
                cursor.execute("DELETE FROM purchased_songs")
                conn.commit()
        except Exception as e:
            logger.exception("Error clearing database")
            raise

    def start_log_operation(self, operation_name, details = ""):
        """Starts logging a new operation, recording the start time and operation name."""
        start_time = datetime.now().isoformat()
        log_id_uuid = str(uuid.uuid4()) [:8].upper()  # Shortened UUID
        logger.debug(f"Starting operation log: {operation_name} with ID {log_id_uuid} at {start_time}")
        try:
            with self._get_connection() as conn:  # Use context manager
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO operation_logs (id, operation, start_time, status, details)
                    VALUES (?, ?, ?, ?, ?)
                ''', (log_id_uuid, operation_name, start_time, 'running', details))
                conn.commit()
            return log_id_uuid
        except Exception as e:
            logger.exception(f"Failed to start log operation {operation_name}")
            raise

    def update_log_operation(self, log_id, status, details = ""):
        """Updates the log entry."""
        end_time = datetime.now().isoformat()
        logger.debug(f"Updating operation log ID {log_id}, status: {status} at {end_time}")
        try:
            with self._get_connection() as conn:  # Use context manager
                cursor = conn.cursor()
                cursor.execute('''UPDATE operation_logs SET end_time = ?, status = ?, details = ? WHERE id = ?''',
                               (end_time, status, details, log_id))  # Corrected WHERE clause
                conn.commit()

                # Keep only the last 100 log entries
                cursor.execute('''
                    DELETE FROM operation_logs
                    WHERE id NOT IN (
                        SELECT id FROM operation_logs
                        ORDER BY start_time DESC
                        LIMIT 100
                    )
                ''')
                conn.commit()
        except Exception as e:
            logger.exception(f"Error updating log operation: {log_id}")
            raise

    def get_operation_logs(self, filters = None, search_term = None, page = 1, page_size = 10):
        """Retrieves operation logs from the database with optional filters, search, and pagination."""
        try:
            with self._get_connection() as conn:  # Use context manager
                cursor = conn.cursor()
                offset = (page - 1) * page_size
                query = "SELECT id, operation, start_time, end_time, status, details FROM operation_logs"  # Corrected SELECT
                where_clauses = []
                params = []

                if search_term:
                    where_clauses.append("(operation LIKE ? OR details LIKE ? OR status LIKE ?)")
                    search_pattern = f"%{search_term}%"
                    params.extend([search_pattern, search_pattern, search_pattern])

                if filters and filters.get('operation'):
                    where_clauses.append("operation = ?")
                    params.append(filters ['operation'])

                if where_clauses:
                    query += " WHERE " + " AND ".join(where_clauses)

                query += " ORDER BY start_time DESC LIMIT ? OFFSET ?"
                params.extend([page_size, offset])

                cursor.execute(query, params)
                return cursor.fetchall()
        except Exception as e:
            logger.exception("Failed to retrieve operation logs")
            raise  # Always re-raise

    def log_operation(self, timestamp, operation, details, status):  # Legacy logging for validate DB start
        """Logs an operation to the legacy operation_logs table."""
        logger.debug(f"Logging legacy operation: {operation}, status: {status}")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
              INSERT INTO legacy_operation_logs_old (timestamp, operation, details, status)
              VALUES (?, ?, ?, ?)
          ''', (timestamp, operation, details, status))
            conn.commit()

    def clear_operation_logs(self):
        """Clears all operation logs from the 'operation_logs' table."""
        logger.warning("Clearing all operation logs.")
        with self._get_connection() as conn:  # Use context manager
            cursor = conn.cursor()
            cursor.execute("DELETE FROM operation_logs")
            conn.commit()

    def set_newly_added_song_count(self, count):
        self._newly_added_song_count = count

    def get_newly_added_song_count(self):
        return getattr(self, '_newly_added_song_count', 0)  # Default to 0 if not set

    def set_newly_downloaded_song_count(self, count):
        self._newly_downloaded_song_count = count

    def get_newly_downloaded_song_count(self):
        return getattr(self, '_newly_downloaded_song_count', 0)  # Default to 0 if not set

    def get_total_song_count(self):
        """Gets the total count of songs in the purchased_songs table."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM purchased_songs")
            return cursor.fetchone()[0]

    def validate_database_integrity(self):
        """Validate database integrity and return a report."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Check for orphaned records
                cursor.execute("SELECT COUNT(*) FROM purchased_songs WHERE song_id IS NULL OR song_id = ''")
                invalid_ids = cursor.fetchone()[0]
                
                # Check for duplicate song IDs
                cursor.execute("""
                    SELECT song_id, COUNT(*) as count 
                    FROM purchased_songs 
                    GROUP BY song_id 
                    HAVING COUNT(*) > 1
                """)
                duplicates = cursor.fetchall()
                
                # Check for songs marked as downloaded but missing file paths
                cursor.execute("""
                    SELECT COUNT(*) FROM purchased_songs 
                    WHERE downloaded = 1 AND (file_path IS NULL OR file_path = '' OR file_path = '[]')
                """)
                missing_paths = cursor.fetchone()[0]
                
                total_songs = self.get_total_song_count()
                
                report = {
                    "total_songs": total_songs,
                    "invalid_ids": invalid_ids,
                    "duplicates": len(duplicates),
                    "missing_file_paths": missing_paths,
                    "is_healthy": invalid_ids == 0 and len(duplicates) == 0
                }
                
                logger.info(f"Database integrity check: {report}")
                return report
                
        except Exception as e:
            logger.exception("Failed to validate database integrity")
            return {"error": str(e), "is_healthy": False}

    def cleanup_database(self):
        """Clean up database inconsistencies."""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Remove records with invalid song IDs
                cursor.execute("DELETE FROM purchased_songs WHERE song_id IS NULL OR song_id = ''")
                removed_invalid = cursor.rowcount
                
                # Fix songs marked as downloaded but missing file paths
                cursor.execute("""
                    UPDATE purchased_songs 
                    SET downloaded = 0, file_path = '[]' 
                    WHERE downloaded = 1 AND (file_path IS NULL OR file_path = '' OR file_path = '[]')
                """)
                fixed_paths = cursor.rowcount
                
                conn.commit()
                
                logger.info(f"Database cleanup: removed {removed_invalid} invalid records, fixed {fixed_paths} path issues")
                return {"removed_invalid": removed_invalid, "fixed_paths": fixed_paths}
                
        except Exception as e:
            logger.exception("Failed to cleanup database")
            raise
