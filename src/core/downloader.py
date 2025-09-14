# src/core/downloader.py
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import BadZipFile, ZipFile

import requests
from PyQt6.QtCore import QObject, pyqtSignal

from src.core.utils import sanitize_filename

logger = logging.getLogger('vibe_manager')  # Use the main logger


class SongDownloader(QObject):
    download_progress = pyqtSignal(str, int)  # (song_id, progress_in_percent)
    download_finished = pyqtSignal(str)  # (song_id)
    download_failed = pyqtSignal(str, str)  # (song_id, error_message)
    song_download_completed = pyqtSignal(str)  # Signal when individual song completes

    def __init__(self, config, session, max_concurrent_downloads = 5, parent = None):
        super().__init__(parent)
        self.download_dir = Path(config ["download_dir"]).resolve()  # Use pathlib, get from config
        self.session = session
        self.max_concurrent_downloads = max_concurrent_downloads
        self.executor = ThreadPoolExecutor(max_workers=self.max_concurrent_downloads)
        self.lock = threading.Lock()  # Kept the lock, just in case. Not harmful.

    def get_direct_download_url(self, download_url, max_retries = 3):
        """Retrieves the direct download URL for a song by analyzing 'X-File-Href' header."""
        retry_count = 0
        while retry_count < max_retries:
            try:
                response = self.session.get(download_url)
                if 'X-File-Href' in response.headers:
                    return response.headers ['X-File-Href']
                retry_count += 1
                time.sleep(2)
            except requests.RequestException as e:  # More specific exception
                logger.error(f"Error retrieving direct download URL (attempt {retry_count + 1}): {e}")
                retry_count += 1
                time.sleep(2)
            except Exception as e:  # Added to catch all
                logger.error(f"Error retrieving direct download URL. Attempt {retry_count + 1} failed: {e}")
                # Send the exception to Sentry
                retry_count += 1
                time.sleep(2)
        logger.error(f"Failed to retrieve direct download URL after {max_retries} attempts: {download_url}")
        return None

    def download_song(self, song, unzip_songs=False, delete_zip=False):
        """Downloads a single song with enhanced retry logic and progress tracking."""
        song_id = song['song_id']
        max_retries = 5
        song_file_paths = []

        file_name = sanitize_filename(song['artist'], song['title'], song['song_id'])
        file_path = self.download_dir / file_name  # Extension already included by sanitize_filename

        # Check if file already exists
        if file_path.exists() and self.verify_zip_file(file_path, song):
            logger.info(f"File already exists and is valid: {song['title']} ({song_id})")
            song["file_path"] = [file_path.name]
            song["downloaded"] = 1
            self.download_finished.emit(song_id)
            return

        # Clean up any corrupted partial downloads
        if file_path.exists():
            file_path.unlink()

        for attempt in range(1, max_retries + 1):
            try:
                # Get direct download URL with retry
                real_download_url = self.get_direct_download_url(
                    'https://www.karaoke-version.com' + song["download_url"], max_retries=3)
                
                if not real_download_url:
                    raise Exception("Failed to get direct download URL after retries")

                # Start download with proper headers
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Accept': '*/*',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate'
                }
                
                response = self.session.get(real_download_url, stream=True, headers=headers, timeout=30)
                response.raise_for_status()

                total_length = response.headers.get('content-length')
                total_length = int(total_length) if total_length else None
                downloaded_length = 0
                start_time = time.time()

                # Create temporary file for atomic operation
                temp_file = file_path.with_suffix('.tmp')
                
                with temp_file.open('wb') as file:
                    for chunk in response.iter_content(chunk_size=16384):  # Larger chunk size
                        if chunk:
                            file.write(chunk)
                            downloaded_length += len(chunk)
                            
                            if total_length:
                                progress_percent = min(int(downloaded_length / total_length * 100), 100)
                                
                                # Calculate ETA
                                elapsed_time = time.time() - start_time
                                if elapsed_time > 0 and downloaded_length > 0:
                                    speed = downloaded_length / elapsed_time
                                    remaining_bytes = total_length - downloaded_length
                                    eta_seconds = remaining_bytes / speed if speed > 0 else 0
                                    eta_text = f" (ETA: {int(eta_seconds)}s)" if eta_seconds > 1 else ""
                                else:
                                    eta_text = ""
                                    
                                self.download_progress.emit(song_id, progress_percent)

                # Atomic move to final location
                temp_file.rename(file_path)
                
                # Verify download integrity
                if not self.verify_zip_file(file_path, song):
                    raise Exception("Downloaded file failed integrity check")

                song_file_paths = [file_path.name]

                # Handle extraction if requested
                if unzip_songs:
                    try:
                        extracted_files = self.handle_zip_extraction(file_path, song_id, delete_zip)
                        song_file_paths = extracted_files
                        song["extracted"] = 1
                    except Exception as e:
                        logger.error(f"Extraction failed for {song['title']}: {e}")
                        song["extracted"] = 0
                else:
                    song["extracted"] = 0

                song["file_path"] = song_file_paths
                song["downloaded"] = 1
                song["download_size"] = downloaded_length
                song["download_time"] = time.time() - start_time

                logger.info(f"Successfully downloaded: {song['title']} ({song_id}) - {downloaded_length} bytes")
                self.download_finished.emit(song_id)
                self.song_download_completed.emit(song_id)  # Emit individual completion signal
                return

            except requests.exceptions.RequestException as e:
                logger.warning(f"Network error on attempt {attempt} for {song['title']}: {e}")
                
            except Exception as e:
                logger.warning(f"Download attempt {attempt} failed for {song['title']}: {e}")
                
                # Clean up partial download
                if file_path.exists():
                    file_path.unlink()
                temp_file = file_path.with_suffix('.tmp')
                if temp_file.exists():
                    temp_file.unlink()

            # Don't retry on final attempt
            if attempt < max_retries:
                sleep_time = min(2 ** (attempt - 1) + random.uniform(0, 1), 30)  # Cap at 30 seconds
                logger.info(f"Retrying download of {song['title']} in {sleep_time:.1f} seconds...")
                time.sleep(sleep_time)

        # All attempts failed
        logger.error(f"Failed to download {song['title']} after {max_retries} attempts")
        song["downloaded"] = 0
        self.download_failed.emit(song_id, f"Download failed after {max_retries} attempts")

    def handle_zip_extraction(self, zip_file_path, song_id, delete_zip = False):
        """Unzips the downloaded file, renames extracted MP3/CDG files, and optionally deletes the .zip."""
        extract_dir = zip_file_path.parent
        base_id_numeric = song_id [2:] if song_id.startswith("KV") else song_id

        extracted_files = []
        try:
            with ZipFile(zip_file_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
        except Exception as e:
            logger.error(f"Error extracting the zip file.: {e}")

        for f in extract_dir.iterdir():  # Use pathlib iterdir
            if base_id_numeric in f.name and f.suffix in [".mp3", ".cdg"]:
                new_file_name = f.name.replace(base_id_numeric, f"KV{base_id_numeric}")
                new_file_path = extract_dir / new_file_name  # Use pathlib
                try:
                    f.rename(new_file_path)  # Use pathlib rename
                    extracted_files.append(str(new_file_path.name))  # Store only filename
                except Exception as e:
                    logger.error(f"Error renaming extracted file: {e}")

        if delete_zip:
            try:
                zip_file_path.unlink()  # pathlib unlink
            except Exception as e:
                logger.error(f"Error deleting the zip file: {e}")

        else:
            bak_file = zip_file_path.with_suffix('.zip.bak')  # Use with_suffix
            try:
                zip_file_path.rename(bak_file)  # Use pathlib rename
                extracted_files.append(str(bak_file.name))  # Store only filename
            except Exception as e:
                logger.error(f"Error renaming zip to bak: {e}")

        return extracted_files

    def get_song_file_paths(self, song):
        """Returns the list of file paths for a song (zip or extracted files)."""
        return song.get("file_path", [])  # Retrieve file paths from the song dictionary

    def verify_zip_file(self, zip_file_path, song):
        """Verifies if a zip file is valid by attempting to open and test it."""
        try:
            with ZipFile(zip_file_path, 'r') as zip_ref:
                zip_ref.testzip()  # Performs basic zip integrity checks
            logger.debug(f"Zip file verified successfully: {song ['title']}")
            return True
        except BadZipFile as e:
            logger.error(f"Zip file verification failed (BadZipFile): {song ['title']} - {e}")

            zip_file_path.unlink()  # Optionally delete the corrupt zip file
            return False
        except Exception as e:  # Catch other potential exceptions during zip verification
            logger.error(f"Zip file verification failed (Other Error): {song ['title']} - {e}")

            zip_file_path.unlink()  # Optionally delete the corrupt zip file
            return False
