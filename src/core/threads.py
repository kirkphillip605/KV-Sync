# src/threads.py
import logging
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from zipfile import BadZipFile, ZipFile
from datetime import datetime

import requests
from PyQt6.QtCore import QObject, pyqtSignal, QThread

from src.core.utils import sanitize_filename
from src.core.date_utils import standardize_date

logger = logging.getLogger('vibe_manager') # Use the main logger

class ScrapeThread(QThread):
    progress = pyqtSignal(int, str)  # (progress, message)
    finished = pyqtSignal()
    error = pyqtSignal(str)

    def __init__(self, scraper, db_manager, last_song_id=None, validate=False):
        super().__init__()
        self.scraper = scraper
        self.db_manager = db_manager
        self.last_song_id = last_song_id
        self.validate = validate
        self.stop_scraping_flag = False # Add stop flag
        self.log_id = None # To store log operation ID

    def run(self):
        try:
            self.progress.emit(0, "Scraping started...")
            songs = self.scraper.scrape_all_pages(self.last_song_id, self.validate)
            added_song_count = 0
            total_songs = len(songs)
            logger.debug(f"Scraped {total_songs} songs.")
            self.progress.emit(10, f"Scraped {total_songs} songs.")


            for index, song in enumerate(songs):
                if self.stop_scraping_flag: # Check stop flag inside the loop
                    logger.info("Scraping stopped by user request.")
                    self.progress.emit(100, "Scraping stopped.") # Indicate stopped status
                    return # Exit run method

                song["order_date"] = standardize_date(song["order_date"]) if song["order_date"] else None
                existing_song = self.db_manager.song_exists(song["song_id"])
                if not existing_song:
                    self.db_manager.save_song(song)
                    added_song_count += 1
                else:
                    # If it's in the DB but not downloaded, we can update it
                    downloaded_status = existing_song["downloaded"]
                    if downloaded_status == 0:
                        self.db_manager.update_song(song)

                # Emit real-time status for each song
                progress_val = int(10 + (index / total_songs) * 90)
                self.progress.emit(progress_val, f"Fetching Song: {song['title']} by {song.get('artist', 'Unknown')}")
            
            self.progress.emit(100, "Scraping completed.")
            self.db_manager.set_newly_added_song_count(added_song_count) # Store count in DB for logging later
            self.finished.emit()

        except Exception as e:
            logger.error(f"Error in ScrapeThread: {e}")
            self.error.emit(str(e))
            if self.log_id:
                self.db_manager.update_log_operation(self.log_id, "failed", f"Scraping process encountered an error: {e}")

    def stop_scraping(self): # New method to set stop flag
        self.stop_scraping_flag = True


class DownloadThread(QThread):
    progress = pyqtSignal(int, str)  # (progress, message)
    finished = pyqtSignal()
    error = pyqtSignal(str)
    song_started = pyqtSignal(dict)  # (song) - emitted when a song starts downloading
    song_progress = pyqtSignal(str, int, str)  # (song_id, progress_percent, speed) - emitted during download
    song_finished = pyqtSignal(str)  # (song_id) - emitted when a song completes
    song_failed = pyqtSignal(str, str)  # (song_id, error_message) - emitted when a song fails

    def __init__(self, songs, downloader, db_manager, unzip_songs=False, delete_zip=False):
        super().__init__()
        self.songs = songs
        self.downloader = downloader
        self.db_manager = db_manager
        self.unzip_songs = unzip_songs
        self.delete_zip = delete_zip
        self.stop_downloading_flag = False # Add stop flag
        self.log_id = None # To store log operation ID
        self.downloaded_song_count = 0 # Initialize as instance attribute

    def run(self):
        try:
            self.downloaded_song_count = 0 # Initialize here at start of run
            total_songs = len(self.songs)
            logger.debug(f"Starting DownloadThread for {total_songs} songs.")

            start_time = time.time() # Record start time for ETA calculation

            def download_and_update(song):
                if self.stop_downloading_flag: # Check stop flag inside download_and_update
                    return # Stop processing this song if stop requested

                if song["downloaded"] == 0:
                    # Emit signal that this song is starting
                    self.song_started.emit(song)
                    
                    retries = 3 # Number of retries
                    for attempt in range(retries):
                        try:
                            self.downloader.download_song(song, self.unzip_songs, self.delete_zip)
                            # Mark as downloaded in DB
                            song["downloaded"] = 1
                            self.downloaded_song_count += 1 # Increment instance attribute
                            self.db_manager.update_song(song) # Update song in our DB
                            return # Exit retry loop on success
                        except (BadZipFile, requests.exceptions.RequestException, Exception) as e:
                            logger.warning(f"Attempt {attempt + 1}/{retries} failed for song {song['title']} with error: {e}")
                            if attempt < retries - 1:
                                time.sleep(random.uniform(1, 5)) # Wait before retrying
                            else:
                                logger.error(f"Download failed for song {song['title']} after {retries} attempts: {e}")
                                self.error.emit(f"Failed to download {song['title']}: {e}")
                                self.song_failed.emit(song['song_id'], str(e))
                                # Mark as failed in DB if needed, or leave as is to retry later

            with ThreadPoolExecutor(max_workers=self.downloader.max_concurrent_downloads) as executor:
                futures = []
                for idx, song in enumerate(self.songs):
                    if self.stop_downloading_flag: # Check stop flag before submitting each song
                        logger.info("Downloads stopped by user request.")
                        self.progress.emit(100, "Downloads stopped.") # Indicate stopped status
                        return # Exit run method

                    if song["downloaded"] == 0:
                        futures.append(executor.submit(download_and_update, song))

                    elapsed_time = time.time() - start_time
                    progress_percentage = int((idx + 1) / total_songs * 100) if total_songs > 0 else 0

                    # ETA Calculation
                    if elapsed_time > 0 and idx + 1 > 0:
                        speed = (idx + 1) / elapsed_time
                        remaining_songs = total_songs - (idx + 1)
                        eta_seconds = remaining_songs / speed if speed > 0 else 0
                        eta_time = datetime.fromtimestamp(time.time() + eta_seconds).strftime('%H:%M:%S')
                        eta_message = f"ETA: {eta_time}"
                    else:
                        eta_message = "ETA: --:--:--"

                    self.progress.emit(progress_percentage, f"Processing song {idx + 1}/{total_songs}: {song['title']} ({eta_message})")

                # Wait for all futures to complete
                for future in futures:
                    future.result() # This will re-raise exceptions if any occurred

            self.progress.emit(100, f"All downloads completed. Downloaded {self.downloaded_song_count} songs.") # Access instance attribute
            self.finished.emit()

        except Exception as e:
            logger.error(f"Error in DownloadThread: {e}")
            self.error.emit(str(e))
            if self.log_id:
                self.db_manager.update_log_operation(self.log_id, "failed", f"Download process encountered an error: {e}")
                logger.error(f"Logged download error to operation log ID: {self.log_id}")

    def stop_downloading(self): # New method to set stop flag
        self.stop_downloading_flag = True