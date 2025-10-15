# src/ui/currentDownloadsDialog.py
import logging
import os
from pathlib import Path

import requests
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QEvent
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QProgressBar, QPushButton, QWidget, QHBoxLayout, QLabel, QApplication)

from src.core.scraper import SongScraper

logger = logging.getLogger('vibe_manager')


class SingleDownloadThread(QThread):
    """Thread for downloading a single song"""
    progress = pyqtSignal(str, int, str)  # (song_id, progress_percent, speed)
    finished = pyqtSignal(str)  # (song_id)
    failed = pyqtSignal(str, str)  # (song_id, error_message)
    
    def __init__(self, song, session, download_dir, username, password, parent=None):
        super().__init__(parent)
        self.song = song
        self.session = session
        self.download_dir = Path(download_dir)
        self.username = username
        self.password = password
        self.stop_flag = False
        
    def run(self):
        try:
            # Create authenticated session if needed
            scraper = SongScraper("https://www.karaoke-version.com", self.username, self.password, self.session)
            try:
                scraper.login()
                logger.debug(f"SingleDownloadThread: Logged in for song {self.song['song_id']}")
            except Exception as e:
                logger.error(f"SingleDownloadThread: Login failed: {e}")
                self.failed.emit(self.song['song_id'], f"Login failed: {e}")
                return
            
            # Build full download URL
            base_url = "https://www.karaoke-version.com"
            download_url = base_url + self.song['download_url']
            
            # Get direct download URL
            response = self.session.get(download_url)
            if 'X-File-Href' not in response.headers:
                self.failed.emit(self.song['song_id'], "Failed to get direct download URL")
                return
                
            real_download_url = response.headers['X-File-Href']
            
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
            
            # Create file path
            file_name = f"{self.song.get('artist', 'Unknown')} - {self.song.get('title', 'Unknown')} - {self.song['song_id']}.zip"
            # Sanitize filename
            file_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '-', '_', '.')).rstrip()
            file_path = self.download_dir / file_name
            
            import time
            start_time = time.time()
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if self.stop_flag:
                        logger.info(f"Download stopped for {self.song['song_id']}")
                        return
                        
                    if chunk:
                        f.write(chunk)
                        downloaded_length += len(chunk)
                        
                        if total_length:
                            progress_percent = int((downloaded_length / total_length) * 100)
                            elapsed = time.time() - start_time
                            if elapsed > 0:
                                speed_bps = downloaded_length / elapsed
                                # Convert to KB/sec or MB/sec
                                if speed_bps > 1024 * 1024:
                                    speed_str = f"{speed_bps / (1024 * 1024):.1f} MB/sec"
                                else:
                                    speed_str = f"{speed_bps / 1024:.0f} KB/sec"
                            else:
                                speed_str = "-- KB/sec"
                                
                            self.progress.emit(self.song['song_id'], progress_percent, speed_str)
            
            logger.info(f"Download completed for {self.song['song_id']}")
            self.finished.emit(self.song['song_id'])
            
        except Exception as e:
            logger.error(f"Download failed for {self.song['song_id']}: {e}")
            self.failed.emit(self.song['song_id'], str(e))
    
    def stop(self):
        self.stop_flag = True


class CurrentDownloadsDialog(QDialog):
    """Dialog to show current download progress"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Current Downloads")
        self.setMinimumSize(800, 400)
        self.setModal(False)  # Allow interaction with main window
        
        # Make window frameless and add window hint to close on focus loss
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Popup)
        
        # Store active download threads and completed downloads
        self.active_downloads = {}  # song_id -> (thread, row_index)
        self.completed_downloads = set()  # Set of song_ids that are completed
        
        layout = QVBoxLayout(self)
        
        # Create table for downloads
        self.downloads_table = QTableWidget(0, 4)  # 4 columns
        self.downloads_table.setHorizontalHeaderLabels([
            "Song", "Artist", "Progress", "Status"
        ])
        
        # Make table read-only - disable editing
        self.downloads_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        # Set column resize modes
        header = self.downloads_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Song
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Artist
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)     # Progress
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Status
        
        self.downloads_table.setColumnWidth(2, 150)  # Progress column width
        
        # Hide table borders and row numbers
        self.downloads_table.setShowGrid(False)
        self.downloads_table.verticalHeader().setVisible(False)
        
        layout.addWidget(self.downloads_table)
        
        # Add button container at the bottom
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Clear Completed button
        self.clear_completed_button = QPushButton("Clear Completed")
        self.clear_completed_button.clicked.connect(self.clear_completed_downloads)
        self.clear_completed_button.setEnabled(False)  # Disabled until there are completed downloads
        button_layout.addWidget(self.clear_completed_button)
        
        layout.addLayout(button_layout)
        
        logger.debug("CurrentDownloadsDialog: Initialized")
    
    def add_download(self, song, session, download_dir, username, password):
        """Add a song to the download queue and start downloading"""
        song_id = song['song_id']
        
        # Check if already downloading
        if song_id in self.active_downloads:
            logger.debug(f"Song {song_id} is already being downloaded")
            return
        
        # Add row to table
        row = self.downloads_table.rowCount()
        self.downloads_table.insertRow(row)
        
        # Song title
        self.downloads_table.setItem(row, 0, QTableWidgetItem(song.get('title', 'Unknown')))
        
        # Artist
        self.downloads_table.setItem(row, 1, QTableWidgetItem(song.get('artist', 'Unknown')))
        
        # Progress bar
        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(2, 2, 2, 2)
        progress_bar = QProgressBar()
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_layout.addWidget(progress_bar)
        self.downloads_table.setCellWidget(row, 2, progress_widget)
        
        # Status
        self.downloads_table.setItem(row, 3, QTableWidgetItem("Downloading..."))
        
        # Create and start download thread
        thread = SingleDownloadThread(song, session, download_dir, username, password, self)
        thread.progress.connect(lambda sid, prog, speed: self.update_progress(sid, prog, speed))
        thread.finished.connect(lambda sid: self.download_finished(sid))
        thread.failed.connect(lambda sid, err: self.download_failed(sid, err))
        
        self.active_downloads[song_id] = {
            'thread': thread,
            'row': row,
            'song': song,
            'session': session,
            'download_dir': download_dir,
            'username': username,
            'password': password
        }
        
        thread.start()
        logger.debug(f"Started download for song {song_id} at row {row}")
    
    def add_download_from_thread(self, song):
        """Add a song to the display (for bulk downloads from DownloadThread)"""
        song_id = song['song_id']
        
        # Check if already in the table
        if song_id in self.active_downloads or song_id in self.completed_downloads:
            logger.debug(f"Song {song_id} is already in the downloads table")
            return
        
        # Add row to table
        row = self.downloads_table.rowCount()
        self.downloads_table.insertRow(row)
        
        # Song title
        self.downloads_table.setItem(row, 0, QTableWidgetItem(song.get('title', 'Unknown')))
        
        # Artist
        self.downloads_table.setItem(row, 1, QTableWidgetItem(song.get('artist', 'Unknown')))
        
        # Progress bar
        progress_widget = QWidget()
        progress_layout = QVBoxLayout(progress_widget)
        progress_layout.setContentsMargins(2, 2, 2, 2)
        progress_bar = QProgressBar()
        progress_bar.setMaximum(100)
        progress_bar.setValue(0)
        progress_layout.addWidget(progress_bar)
        self.downloads_table.setCellWidget(row, 2, progress_widget)
        
        # Status
        self.downloads_table.setItem(row, 3, QTableWidgetItem("Downloading..."))
        
        # Store download info (without thread since it's handled by DownloadThread)
        self.active_downloads[song_id] = {
            'thread': None,
            'row': row,
            'song': song
        }
        
        logger.debug(f"Added song {song_id} to downloads display at row {row}")
    
    def update_progress(self, song_id, progress_percent, speed):
        """Update progress for a specific download"""
        if song_id not in self.active_downloads:
            return
            
        row = self.active_downloads[song_id]['row']
        
        # Update progress bar
        progress_widget = self.downloads_table.cellWidget(row, 2)
        if progress_widget:
            progress_bar = progress_widget.findChild(QProgressBar)
            if progress_bar:
                progress_bar.setValue(progress_percent)
                progress_bar.setFormat(f"{progress_percent}%")
    
    def download_finished(self, song_id):
        """Handle successful download completion"""
        if song_id not in self.active_downloads:
            return
            
        row = self.active_downloads[song_id]['row']
        
        # Update progress bar to 100%
        progress_widget = self.downloads_table.cellWidget(row, 2)
        if progress_widget:
            progress_bar = progress_widget.findChild(QProgressBar)
            if progress_bar:
                progress_bar.setValue(100)
                progress_bar.setFormat("100%")
        
        # Update status
        status_item = self.downloads_table.item(row, 3)
        if status_item:
            status_item.setText("Completed")
        
        # Mark as completed (keep the row visible)
        self.completed_downloads.add(song_id)
        
        # Remove from active downloads
        del self.active_downloads[song_id]
        
        # Enable the Clear Completed button
        self.clear_completed_button.setEnabled(True)
        
        logger.debug(f"Download completed for song {song_id}")
    
    def download_failed(self, song_id, error_message):
        """Handle failed download"""
        if song_id not in self.active_downloads:
            return
            
        download_info = self.active_downloads[song_id]
        row = download_info['row']
        
        # Update status
        status_item = self.downloads_table.item(row, 3)
        if status_item:
            status_item.setText(f"Failed: {error_message[:30]}")
            status_item.setToolTip(error_message)
        
        logger.debug(f"Download failed for song {song_id}: {error_message}")
    
    def retry_download(self, song_id):
        """Retry a failed download"""
        if song_id not in self.active_downloads:
            return
            
        download_info = self.active_downloads[song_id]
        
        # Reset progress and status
        row = download_info['row']
        
        # Reset progress bar
        progress_widget = self.downloads_table.cellWidget(row, 2)
        if progress_widget:
            progress_bar = progress_widget.findChild(QProgressBar)
            if progress_bar:
                progress_bar.setValue(0)
        
        # Reset status
        status_item = self.downloads_table.item(row, 3)
        if status_item:
            status_item.setText("Downloading...")
        
        # Start new download thread
        thread = SingleDownloadThread(
            download_info['song'],
            download_info['session'],
            download_info['download_dir'],
            download_info['username'],
            download_info['password'],
            self
        )
        thread.progress.connect(lambda sid, prog, speed: self.update_progress(sid, prog, speed))
        thread.finished.connect(lambda sid: self.download_finished(sid))
        thread.failed.connect(lambda sid, err: self.download_failed(sid, err))
        
        self.active_downloads[song_id]['thread'] = thread
        thread.start()
        
        logger.debug(f"Retrying download for song {song_id}")
    
    def clear_completed_downloads(self):
        """Remove all completed downloads from the table"""
        # Find all rows with "Completed" status and remove them
        rows_to_remove = []
        for row in range(self.downloads_table.rowCount()):
            status_item = self.downloads_table.item(row, 3)
            if status_item and status_item.text() == "Completed":
                rows_to_remove.append(row)
        
        # Remove rows in reverse order to maintain correct indices
        for row in sorted(rows_to_remove, reverse=True):
            self.downloads_table.removeRow(row)
        
        # Update row indices for remaining active downloads
        for song_id, info in self.active_downloads.items():
            # Count how many completed rows were before this one
            removed_before = sum(1 for r in rows_to_remove if r < info['row'])
            info['row'] -= removed_before
        
        # Clear the completed downloads set
        self.completed_downloads.clear()
        
        # Disable the button
        self.clear_completed_button.setEnabled(False)
        
        logger.debug(f"Cleared {len(rows_to_remove)} completed downloads")
    
    def remove_completed_row(self, song_id, row):
        """Remove a completed download row"""
        # Only remove if still at the same row (table might have changed)
        if row < self.downloads_table.rowCount():
            self.downloads_table.removeRow(row)
            # Update row indices for remaining downloads
            for sid, info in self.active_downloads.items():
                if info['row'] > row:
                    info['row'] -= 1
    
    def closeEvent(self, event):
        """Handle dialog close event"""
        # Don't stop downloads when dialog is closed - just hide it
        # Downloads persist for the session
        event.accept()
