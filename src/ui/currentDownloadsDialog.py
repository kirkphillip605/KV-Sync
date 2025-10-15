# src/ui/currentDownloadsDialog.py
import logging
import os
from pathlib import Path

import requests
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTableWidget, QTableWidgetItem, 
                             QHeaderView, QProgressBar, QPushButton, QWidget, QHBoxLayout, QLabel)

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
        
        # Store active download threads
        self.active_downloads = {}  # song_id -> (thread, row_index)
        
        layout = QVBoxLayout(self)
        
        # Create table for downloads
        self.downloads_table = QTableWidget(0, 6)  # 6 columns
        self.downloads_table.setHorizontalHeaderLabels([
            "Song", "Artist", "Progress", "Speed", "Status", "Action"
        ])
        
        # Set column resize modes
        header = self.downloads_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Song
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Artist
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)     # Progress
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Speed
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Status
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # Action
        
        self.downloads_table.setColumnWidth(2, 150)  # Progress column width
        
        layout.addWidget(self.downloads_table)
        
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
        
        # Speed
        self.downloads_table.setItem(row, 3, QTableWidgetItem("-- KB/sec"))
        
        # Status
        self.downloads_table.setItem(row, 4, QTableWidgetItem("Downloading..."))
        
        # Action button (initially empty, will add Retry if fails)
        action_widget = QWidget()
        self.downloads_table.setCellWidget(row, 5, action_widget)
        
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
        
        # Update speed
        speed_item = self.downloads_table.item(row, 3)
        if speed_item:
            speed_item.setText(speed)
    
    def download_finished(self, song_id):
        """Handle successful download completion"""
        if song_id not in self.active_downloads:
            return
            
        row = self.active_downloads[song_id]['row']
        
        # Update status
        status_item = self.downloads_table.item(row, 4)
        if status_item:
            status_item.setText("Completed")
        
        # Remove from active downloads
        del self.active_downloads[song_id]
        
        # Remove the row after a short delay
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(2000, lambda: self.remove_completed_row(song_id, row))
        
        logger.debug(f"Download completed for song {song_id}")
    
    def download_failed(self, song_id, error_message):
        """Handle failed download"""
        if song_id not in self.active_downloads:
            return
            
        download_info = self.active_downloads[song_id]
        row = download_info['row']
        
        # Update status
        status_item = self.downloads_table.item(row, 4)
        if status_item:
            status_item.setText(f"Failed: {error_message[:30]}")
            status_item.setToolTip(error_message)
        
        # Add retry button
        action_widget = QWidget()
        action_layout = QHBoxLayout(action_widget)
        action_layout.setContentsMargins(2, 2, 2, 2)
        retry_button = QPushButton("Retry")
        retry_button.clicked.connect(lambda: self.retry_download(song_id))
        action_layout.addWidget(retry_button)
        self.downloads_table.setCellWidget(row, 5, action_widget)
        
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
        
        # Reset speed
        speed_item = self.downloads_table.item(row, 3)
        if speed_item:
            speed_item.setText("-- KB/sec")
        
        # Reset status
        status_item = self.downloads_table.item(row, 4)
        if status_item:
            status_item.setText("Downloading...")
        
        # Remove action button
        self.downloads_table.setCellWidget(row, 5, QWidget())
        
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
        # Stop all active downloads when dialog is closed
        for song_id, info in list(self.active_downloads.items()):
            thread = info['thread']
            if thread and thread.isRunning():
                thread.stop()
                thread.wait(1000)  # Wait up to 1 second
        event.accept()
