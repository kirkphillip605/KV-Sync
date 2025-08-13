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

    def __init__(self, config, session, max_concurrent_downloads = 10, parent = None):
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

    def download_song(self, song, unzip_songs = False, delete_zip = False):
        """Downloads a single song, potentially unzips, and removes the .zip if required."""
        song_id = song ['song_id']
        max_retries = 5
        backoff_factor = 1
        song_file_paths = []

        file_name = sanitize_filename(song ['artist'], song ['title'], song ['song_id'])
        file_path = self.download_dir / file_name  # No zip extension here

        if file_path.exists():  # Check if file already exists.  Use pathlib
            logger.info(f"Zip file already exists, skipping download: {song ['title']} ({song_id})")
            song ["file_path"] = [file_name]  # Store just the filename
            song ["downloaded"] = 1  # Mark as downloaded
            self.download_finished.emit(song_id)
            return  # Exit download_song early

        for attempt in range(1, max_retries + 1):
            try:
                real_download_url = self.get_direct_download_url(
                    'https://www.karaoke-version.com' + song ["download_url"])
                if not real_download_url:
                    raise Exception("Failed to get real download URL")  # More specific exception

                response = self.session.get(real_download_url, stream=True)
                if response.status_code != 200:
                    raise Exception(f"HTTP Error: {response.status_code}")

                total_length = response.headers.get('content-length')
                total_length = int(total_length) if total_length else None
                downloaded_length = 0

                with file_path.open('wb') as file:  # Use pathlib's .open() method.
                    for chunk in response.iter_content(chunk_size=8192):  # Increased chunk size
                        if chunk:
                            file.write(chunk)
                            downloaded_length += len(chunk)
                            if total_length:
                                progress_percent = int(downloaded_length / total_length * 100)
                                self.download_progress.emit(song_id, progress_percent)

                song_file_paths = [file_name]  # store only the filename

                if unzip_songs and file_path.suffix == ".zip":
                    extracted_files = self.handle_zip_extraction(file_path, song_id, delete_zip)
                    song_file_paths = extracted_files  # Update to extracted file paths
                    song ["extracted"] = 1
                else:
                    song ["extracted"] = 0  # Ensure extracted is set to 0 if not unzipped

                song ["file_path"] = song_file_paths  # Just the filenames
                song ["downloaded"] = 1

                if not self.verify_zip_file(file_path, song):  # Verify zip integrity after download
                    logger.error(f"Zip file verification failed for: {song ['title']} ({song_id})")
                    song ["downloaded"] = 0  # Mark as not downloaded if verification fails
                    self.download_failed.emit(song_id, "Zip file verification failed.")
                    return  # Stop processing if zip is corrupt

                self.download_finished.emit(song_id)
                return

            except requests.RequestException as e:
                logger.error(f"Download attempt {attempt} failed for {song ['title']}: {e}")

                if attempt == max_retries:
                    self.download_failed.emit(song_id, str(e))

            except Exception as e:  # Catch all exceptions
                logger.error(f"Attempt {attempt} failed for {song ['title']}: {e}")
                # Send the exception to Sentry
                if attempt == max_retries:
                    logger.error(f"Max retries reached for song: {song ['title']}")
                    self.download_failed.emit(song_id, str(e))
                else:
                    sleep_time = backoff_factor * (2 ** (attempt - 1)) + random.uniform(0, 1)
                    time.sleep(sleep_time)

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
