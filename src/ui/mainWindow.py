# src/ui/mainWindow.py
import json
import logging
import os
import socket
import sqlite3
from datetime import datetime

import requests
from PyQt6.QtCore import QTimer, Qt, QDate
from PyQt6.QtGui import QAction, QFont, QIcon, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
                             QProgressBar, QSizePolicy, QStatusBar, QSystemTrayIcon, QTabWidget, QTableView, QToolBar,
                             QVBoxLayout, QWidget)

from src.core.downloader import SongDownloader
from src.core.scraper import SongScraper
from src.core.threads import DownloadThread, ScrapeThread
from src.core.date_utils import format_date_for_display
from src.ui.settingsDialog import SettingsDialog
from src.ui.currentDownloadsDialog import CurrentDownloadsDialog


logger = logging.getLogger('vibe_manager')  # Use the main logger


class DateStandardItem(QStandardItem):
    """Custom QStandardItem that stores QDate objects for proper chronological sorting."""
    
    def __init__(self, iso_date_str, display_text):
        super().__init__(display_text)
        self.setEditable(False)
        
        # Store the QDate object for sorting
        if iso_date_str and iso_date_str.strip():
            try:
                # Parse ISO date string (YYYY-MM-DD) to QDate
                year, month, day = map(int, iso_date_str.split('-'))
                self._date = QDate(year, month, day)
            except (ValueError, AttributeError):
                logger.warning(f"Failed to parse ISO date: {iso_date_str}")
                self._date = QDate()  # Invalid date for sorting purposes
        else:
            self._date = QDate()  # Invalid date for sorting purposes
    
    def __lt__(self, other):
        """Override less than comparison for proper sorting."""
        if isinstance(other, DateStandardItem):
            # Compare QDate objects for chronological sorting
            if not self._date.isValid() and not other._date.isValid():
                return False  # Both invalid, consider equal
            elif not self._date.isValid():
                return True   # Invalid dates sort before valid ones
            elif not other._date.isValid():
                return False  # Valid dates sort after invalid ones
            else:
                return self._date < other._date
        return super().__lt__(other)

class AlternateRowDelegate:
    """Minimal delegate to alternate background colors (optional)."""

    def initStyleOption(self, option, index):
        if index.row() % 2 == 0:
            option.backgroundBrush = option.palette.base()
        else:
            option.backgroundBrush = option.palette.alternateBase()


class MainWindow(QMainWindow):
    def __init__(self, config_manager, db_manager):  # Accept config_manager and db_manager
        logger.debug("MainWindow: Initializing...")
        super().__init__()
        self.setWindowTitle("Vibe SongSync - Purchased Karaoke Track Manager")
        
        # Use platform-appropriate icon with fallback
        import platform
        icon_path = "resources/main.ico" if platform.system() == "Windows" else "resources/main.png"
        main_icon = QIcon(icon_path)
        if main_icon.isNull():
            logger.warning(f"Failed to load window icon from {icon_path}, trying fallback...")
            main_icon = QIcon("resources/main.png")
            if main_icon.isNull():
                logger.error("Failed to load window icon")
        self.setWindowIcon(main_icon)
        self.resize(1000, 700)

        # Use the passed instances
        self.config_manager = config_manager
        self.db_manager = db_manager

        self.load_configurations()
        logger.debug("MainWindow: Configurations loaded.")

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.init_toolbar()
        logger.debug("MainWindow: Toolbar initialized.")
        self.init_bottom_toolbar()
        logger.debug("MainWindow: Bottom toolbar initialized.")
        self.init_status_bar()
        logger.debug("MainWindow: Status bar initialized.")
        self.init_views()
        logger.debug("MainWindow: Views initialized.")

        self.tray_icon = QSystemTrayIcon(self)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.create_tray_icon()
            logger.debug("MainWindow: Tray icon initialized.")
        else:
            logger.warning("MainWindow: System tray not available on this platform.")
            self.tray_icon = None  # Set to None if not available

        self.load_table_view_data()
        logger.debug("MainWindow: Table view data loaded.")
        self.update_record_count()
        logger.debug("MainWindow: Record count updated.")
        self.set_status_message("Idle")
        logger.debug("MainWindow: Status message set to Idle.")

        self.operation_in_progress = False  # Flag for operation status
        self.polling_enabled = False
        self.stop_requested = False
        self.is_online = False  # Initialize internet status

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self.poll_timer_triggered)

        self.poll_countdown_timer = QTimer(self)
        self.poll_countdown_timer.timeout.connect(self.update_polling_tooltip)

        self.prompt_on_minimize = True
        self.scrape_thread = None  # Initialize threads to None
        self.download_thread = None
        self.downloader = None
        
        # Initialize the Current Downloads dialog once (persists for the app session)
        self.current_downloads_dialog = None

        if not self.is_config_valid():
            self.open_settings()

        self.init_internet_status_check()  # Initialize internet status check
        self.check_internet_connection()  # Initial internet check on startup
        self.update_record_count()

        logger.debug("MainWindow: Initialization complete.")

    def init_internet_status_check(self):
        # Reuse the internet_status_label created in init_status_bar
        self.internet_check_timer = QTimer(self)
        self.internet_check_timer.timeout.connect(self.check_internet_connection)
        self.internet_check_timer.start(60000)  # Check every 60 seconds

    def check_internet_connection(self):
        is_online = self.is_internet_available()
        if is_online != self.is_online:
            self.is_online = is_online
            self.update_internet_status_icon()
        logger.debug(f"Internet connection status: {'Online' if self.is_online else 'Offline'}")

    def is_internet_available(self):
        try:
            # Try to resolve a well-known host (Google DNS)
            socket.gethostbyname("www.google.com")
            return True
        except socket.gaierror:
            return False

    def update_internet_status_icon(self):
        if self.is_online:
            self.internet_status_label.setPixmap(QIcon("resources/buttons/online.png").pixmap(20, 20))
            self.internet_status_label.setToolTip("Online")
        else:
            self.internet_status_label.setPixmap(QIcon("resources/buttons/offline.png").pixmap(20, 20))
            self.internet_status_label.setToolTip("Offline")

    def load_configurations(self):
        logger.debug("load_configurations: Loading configurations...")
        config = self.config_manager.get_config()
        self.username = config.get("Credentials", "username", fallback="")
        self.password = config.get("Credentials", "password", fallback="")
        self.download_dir = config.get("Settings", "download_dir", fallback="")
        self.unzip_songs = config.getboolean("Settings", "unzip_songs", fallback=False)
        self.delete_zip_after_extraction = config.getboolean("Settings", "delete_zip_after_extraction", fallback=False)
        self.polling_time = config.getint("Settings", "polling_time", fallback=300)
        self.setup_download_directory()
        logger.debug("load_configurations: Configurations loaded.")

    def setup_download_directory(self):
        logger.debug("setup_download_directory: Setting up download directory...")
        if not self.download_dir:
            self.download_dir = os.path.join(os.path.expanduser("~"), "VibeKaraokeDownloads")
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
        logger.debug(f"setup_download_directory: Download directory set to: {self.download_dir}")

    def init_toolbar(self):
        logger.debug("init_toolbar: Initializing toolbar...")
        toolbar = QToolBar("Main Toolbar")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        # Fetch New
        fetch_new_action = QAction(QIcon("resources/buttons/cloud_sync.png"), "Fetch New", self)
        fetch_new_action.triggered.connect(self.fetch_new)
        toolbar.addAction(fetch_new_action)

        # Full Sync
        full_sync_action = QAction(QIcon("resources/buttons/validate.png"), "Full Sync", self)
        full_sync_action.triggered.connect(self.full_sync)
        toolbar.addAction(full_sync_action)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        # Settings
        settings_action = QAction(QIcon("resources/buttons/settings.svg"), "Settings", self)
        settings_action.triggered.connect(self.open_settings)
        toolbar.addAction(settings_action)

        # Minimize to tray
        minimize_action = QAction(QIcon("resources/buttons/minimize.png"), "Minimize to Tray", self)
        minimize_action.triggered.connect(self.minimize_to_tray)
        toolbar.addAction(minimize_action)

    def init_bottom_toolbar(self):
        logger.debug("init_bottom_toolbar: Initializing bottom toolbar...")
        toolbar = QToolBar("Bottom Toolbar")
        toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        # Refresh table
        refresh_icon = QIcon(os.path.join("resources", "buttons", "refresh.png"))
        refresh_action = QAction(refresh_icon, "Refresh Table", self)
        refresh_action.triggered.connect(self.refresh_table)
        toolbar.addAction(refresh_action)

        # Stop operation (moved from top toolbar)
        self.stop_action = QAction(QIcon("resources/buttons/stop.png"), "Stop Operation", self)
        self.stop_action.triggered.connect(self.stop_current_operation)
        self.stop_action.setEnabled(False)  # Disabled by default
        self.stop_action.setVisible(False)  # Hidden by default
        toolbar.addAction(self.stop_action)

        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self.record_count_label = QLabel("Total Records: 0", alignment=Qt.AlignmentFlag.AlignCenter)
        toolbar.addWidget(self.record_count_label)

        # Spacer
        spacer2 = QWidget()
        spacer2.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer2)

        # Current Downloads (new button to the left of View Logs)
        current_downloads_icon = QIcon(os.path.join("resources", "buttons", "cloud_sync.png"))
        current_downloads_action = QAction(current_downloads_icon, "Current Downloads", self)
        current_downloads_action.triggered.connect(self.view_current_downloads)
        toolbar.addAction(current_downloads_action)

        # Operation Logs (Bottom Toolbar, Right-aligned)
        operation_logs_button = QIcon(os.path.join("resources", "buttons", "logs.png"))
        operation_logs_action = QAction(operation_logs_button, "View Logs", self)
        operation_logs_action.triggered.connect(self.view_logs)
        toolbar.addAction(operation_logs_action)
        logger.debug("init_bottom_toolbar: Bottom toolbar initialized.")

        # Quit (Bottom Toolbar)
        quit_icon_bottom = QIcon(
            os.path.join("resources", "buttons", "exit.png"))  # Use separate icon if needed
        quit_action_bottom = QAction(quit_icon_bottom, "Quit", self)
        quit_action_bottom.triggered.connect(self.quit_application)
        toolbar.addAction(quit_action_bottom)

    def init_status_bar(self):
        logger.debug("init_status_bar: Initializing status bar...")
        self.status_bar = QStatusBar(self)  # Initialize status bar
        self.setStatusBar(self.status_bar)

        self.status_progress = QProgressBar(self)
        self.status_progress.setMaximumWidth(300)
        self.status_progress.setVisible(False)
        self.status_bar.addPermanentWidget(self.status_progress, 1)

        self.status_label = QLabel("Idle", self)
        self.status_bar.addPermanentWidget(self.status_label, 1)
        logger.debug("init_status_bar: Status bar initialized.")

        self.internet_status_label = QLabel()  # Label for internet status icon
        self.status_bar.addPermanentWidget(self.internet_status_label, 0)  # Add to status bar (right side)

    def init_views(self):
        logger.debug("init_views: Initializing views...")
        table_tab = QWidget()  # Widget for table tab
        table_layout = QVBoxLayout(table_tab)

        self.table_view = QTableView()
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setShowGrid(False)
        self.table_view.verticalHeader().setVisible(False)
        self.table_view.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.table_view.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)

        if hasattr(QTableView.ScrollMode, 'ScrollPerPixel'):
            self.table_view.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerPixel)
        else:
            self.table_view.setHorizontalScrollMode(QTableView.ScrollMode.ScrollPerItem)
        self.table_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        header = self.table_view.horizontalHeader()
        header.setStretchLastSection(True)  # Keep this line for now

        table_layout.addWidget(self.table_view)

        self.tabs.addTab(table_tab, "Purchased Karaoke Tracks")

        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        search_layout.addWidget(search_label)
        self.table_search_bar = QLineEdit(self)
        self.table_search_bar.setPlaceholderText("Search by Artist or Title...")
        self.table_search_bar.textChanged.connect(self.filter_table_view)
        search_layout.addWidget(self.table_search_bar)
        table_layout.insertLayout(0, search_layout)
        logger.debug("init_views: Views initialized.")

    def create_tray_icon(self):
        logger.debug("create_tray_icon: Creating tray icon...")
        
        # Use .ico for Windows, .png as fallback for other platforms
        import platform
        icon_path = "resources/main.ico" if platform.system() == "Windows" else "resources/main.png"
        
        # Fallback to .png if .ico doesn't exist or fails to load
        icon = QIcon(icon_path)
        if icon.isNull():
            logger.warning(f"Failed to load icon from {icon_path}, trying fallback...")
            icon = QIcon("resources/main.png")
            if icon.isNull():
                logger.error("Failed to load tray icon from both .ico and .png files")
        
        self.tray_icon.setIcon(icon)
        
        # Create tray menu
        self.tray_menu = QMenu(self)
        
        # View App action (shown when app is hidden)
        self.view_app_action = QAction("View App", self.tray_menu)
        self.view_app_action.triggered.connect(self.show)
        self.tray_menu.addAction(self.view_app_action)
        
        self.tray_menu.addSeparator()
        
        # Toggle Polling action (dynamic text)
        self.toggle_poll_action = QAction("Start Polling", self.tray_menu)
        self.toggle_poll_action.triggered.connect(self.toggle_polling)
        self.tray_menu.addAction(self.toggle_poll_action)
        
        # Stop Operation action (only shown during operations)
        self.tray_stop_action = QAction("Stop Operation", self.tray_menu)
        self.tray_stop_action.triggered.connect(self.stop_current_operation)
        self.tray_stop_action.setVisible(False)
        self.tray_menu.addAction(self.tray_stop_action)
        
        self.tray_menu.addSeparator()
        
        # Config/Settings action
        settings_action = QAction("Config", self.tray_menu)
        settings_action.triggered.connect(self.open_settings)
        self.tray_menu.addAction(settings_action)
        
        self.tray_menu.addSeparator()
        
        # Exit action
        quit_action = QAction("Exit", self.tray_menu)
        quit_action.triggered.connect(self.quit_application)
        self.tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        
        # Connect activated signal for left-click
        self.tray_icon.activated.connect(self.on_tray_icon_activated)
        
        self.tray_icon.show()
        self.update_tray_tooltip()
        logger.debug("create_tray_icon: Tray icon created and shown.")

    def set_status_message(self, message):
        self.status_label.setText(message)
        self.update_tray_tooltip()  # Update tray tooltip to mirror status bar
        logger.info(message)

    def update_polling_tooltip(self):
        if self.operation_in_progress or not self.polling_enabled:
            self.poll_countdown_timer.stop()
            self.update_tray_tooltip()
            return

        remaining_ms = self.poll_timer.remainingTime()
        if remaining_ms > 0:
            remaining_s = int(remaining_ms / 1000)
            tooltip_text = f"Status: Polling in {remaining_s} seconds..."
            if self.tray_icon:
                self.tray_icon.setToolTip(tooltip_text)
        logger.debug("update_polling_tooltip: Tooltip updated.")

    def update_tray_tooltip(self):
        """Update tray tooltip to mirror the status bar text"""
        if not self.tray_icon:
            return
        status_text = self.status_label.text()
        self.tray_icon.setToolTip(f"Status: {status_text}")
        logger.debug(f"update_tray_tooltip: Tray tooltip updated to: {status_text}")
    
    def on_tray_icon_activated(self, reason):
        """Handle tray icon clicks (left and right click)"""
        # Show context menu on both left and right click for consistency
        if reason == QSystemTrayIcon.ActivationReason.Trigger:  # Left click
            # Show the main window on left click
            self.show()
            self.raise_()
            self.activateWindow()
        elif reason == QSystemTrayIcon.ActivationReason.Context:  # Right click
            # Context menu is shown automatically by Qt
            pass
        logger.debug(f"on_tray_icon_activated: Tray icon activated with reason: {reason}")

    def update_tray_menu(self):
        """Update tray menu items based on current application state"""
        if not self.tray_icon or not hasattr(self, 'toggle_poll_action'):
            return
            
        # Update polling action text
        if self.polling_enabled:
            self.toggle_poll_action.setText("Stop Polling")
        else:
            self.toggle_poll_action.setText("Start Polling")
        
        # Update stop operation visibility
        if self.operation_in_progress:
            self.tray_stop_action.setVisible(True)
            self.tray_stop_action.setEnabled(not self.stop_requested)
        else:
            self.tray_stop_action.setVisible(False)
        
        logger.debug(f"update_tray_menu: Menu updated - Polling: {self.polling_enabled}, Operation: {self.operation_in_progress}")
    
    def is_config_valid(self):
        valid_config = self.username and self.password and os.path.exists(self.download_dir)
        logger.debug(f"is_config_valid: Config valid: {valid_config}")
        return valid_config

    def load_table_view_data(self):
        logger.debug("load_table_view_data: Loading table view data...")
        songs = self.db_manager.get_all_songs()  # Fetch songs from DB
        self.table_model = QStandardItemModel(0, 5)
        self.table_model.setHorizontalHeaderLabels(['Artist', 'Title', 'Song ID', 'Purchased', 'DL'])

        bold_font = QFont()
        bold_font.setBold(True)

        linked_icon = QIcon("resources/buttons/linked.png")
        missing_icon = QIcon("resources/buttons/missing.png")

        for song in songs:
            artist = QStandardItem(song[1])
            artist.setEditable(False)
            artist.setFont(bold_font)

            title = QStandardItem(song[3])
            title.setEditable(False)
            title.setFont(bold_font)

            song_id = QStandardItem(song[0])
            song_id.setEditable(False)

            # Format the purchase date according to user preference and create DateStandardItem
            raw_date = song[5]  # ISO format from database
            config = self.config_manager.get_config()
            if not config.has_section("Display"):
                config.add_section("Display")
            date_format = config.get("Display", "date_format", fallback="yyyy-MM-dd")
            formatted_date = format_date_for_display(raw_date, date_format) if raw_date else ""
            
            # Use DateStandardItem for proper chronological sorting
            purchase_date = DateStandardItem(raw_date, formatted_date)

            downloaded_item = QStandardItem()
            downloaded_item.setEditable(False)
            if song[8]:
                downloaded_item.setIcon(linked_icon)
                downloaded_item.setText("Yes")  # Optional text, can remove if only want icon
            else:
                downloaded_item.setIcon(missing_icon)
                downloaded_item.setText("No")  # Optional text

            self.table_model.appendRow([artist, title, song_id, purchase_date, downloaded_item])

        self.table_view.setModel(self.table_model)
        self.table_view.setSortingEnabled(True)
        # Set default sort to reverse chronological (most recent purchases first)
        self.table_view.sortByColumn(3, Qt.SortOrder.DescendingOrder)
        
        # Store current sort state
        self.current_sort_column = 3
        self.current_sort_order = Qt.SortOrder.DescendingOrder
        
        # Get header reference before using it
        header = self.table_view.horizontalHeader()
        
        # Connect to header click to track sort changes
        header.sectionClicked.connect(self.on_header_clicked)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # Artist
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Title
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)  # Song ID
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # Purchase Date
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # Downloaded
        header.setStretchLastSection(False)

        logger.debug("load_table_view_data: Table view data loaded.")

    def update_record_count(self):
        total_records = self.table_model.rowCount()
        self.record_count_label.setText(f"Total Records: {total_records}")
        logger.debug(f"update_record_count: Record count updated to: {total_records}")

    def filter_table_view(self, text):
        logger.debug(f"filter_table_view: Filtering table with text: {text}")
        text = text.lower()
        row_count = self.table_model.rowCount()
        for row in range(row_count):
            artist_item = self.table_model.item(row, 0)
            title_item = self.table_model.item(row, 1)
            match = any(text in item.text().lower() for item in [artist_item, title_item])
            self.table_view.setRowHidden(row, not match)  # Hide rows that don't match
        self.update_record_count()
        logger.debug("filter_table_view: Table filtering complete.")

    def open_settings(self):
        print("open_settings: Opening settings dialog...")  # Debugging log
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            print("open_settings: Settings dialog accepted.")  # Debugging log
            self.load_configurations()  # Reload configurations
            self.load_table_view_data()
            self.update_record_count()
        else:
            logger.debug("open_settings: Settings dialog rejected or closed.")

    def poll_timer_triggered(self):
        if not self.operation_in_progress:
            self.fetch_new()
        logger.debug("poll_timer_triggered: Timer triggered, checked operation status.")

    def restart_poll_timers(self):
        self.poll_timer.stop()  # Stop existing timers
        self.poll_countdown_timer.stop()
        self.poll_timer.start(self.polling_time * 1000)
        self.poll_countdown_timer.start(1000)
        self.update_polling_tooltip()
        logger.debug("restart_poll_timers: Poll timers restarted.")

    def stop_poll_timers(self):
        self.poll_timer.stop()  # Stop timers
        self.poll_countdown_timer.stop()
        logger.debug("stop_poll_timers: Poll timers stopped.")

    def toggle_polling(self):
        log_id = self.db_manager.start_log_operation("Toggle Polling", "Polling status change requested by user.")
        self.polling_enabled = not self.polling_enabled
        if self.polling_enabled:
            self.restart_poll_timers()
        else:
            self.stop_poll_timers()
        self.update_tray_tooltip()
        self.update_tray_menu()  # Update tray menu text
        logger.debug(f"toggle_polling: Polling toggled, enabled: {self.polling_enabled}")
        self.db_manager.update_log_operation(log_id, "success",
                                             f"Polling toggled to: {'Enabled' if self.polling_enabled else 'Disabled'}.")

    def fetch_new(self):
        if not self.check_internet_before_operation():  # Check internet at start of operation
            return

        logger.debug("fetch_new: Starting fetch new operation...")
        self.start_operation("Fetching new tracks...")
        log_id = self.db_manager.start_log_operation("Fetch New",
                                                     "Initiating process to retrieve new karaoke tracks.")

        # Initialize scraper and session
        self.session = requests.Session()
        self.scraper = SongScraper("https://www.karaoke-version.com", self.username, self.password, self.session)
        try:
            self.scraper.login()
            logger.debug("fetch_new: Scraper logged in successfully.")
        except Exception as e:
            logger.error(f"fetch_new: Scraper login failed: {e}")
            self.db_manager.update_log_operation(log_id, "failed", f"Scraper login failed: {e}")
            self.end_operation(str(e))
            return

        try:
            self.scraper.change_file_format(dl_id="51289285")
            logger.debug("set_file_format: Set all files to correct format.")
        except Exception as e:
            logger.error(f"set_file_format: Failed setting file format: {e}")
            return

        last_song_id = self.db_manager.get_last_song_id()
        self.scrape_thread = ScrapeThread(self.scraper, self.db_manager, last_song_id)
        self.scrape_thread.log_id = log_id  # Attach log_id to thread
        self.scrape_thread.progress.connect(self.update_operation_progress)
        self.scrape_thread.finished.connect(lambda: self.scrape_finished(log_id=log_id))  # Pass log_id
        self.scrape_thread.error.connect(self.handle_error)
        self.scrape_thread.start()
        logger.debug("fetch_new: Scrape thread started.")

    def scrape_finished(self, log_id):
        logger.debug("scrape_finished: Scrape thread finished.")
        if self.scrape_thread and getattr(self.scrape_thread, 'stop_scraping_flag', False):
            self.db_manager.update_log_operation(log_id, "cancelled", "Scraping process was cancelled by the user.")
            self.end_operation("Scraping cancelled by user.")
            return

        scraped_count = self.db_manager.get_newly_added_song_count()  # Get count of newly added songs
        self.db_manager.update_log_operation(log_id, "success", f"Scraping completed. {scraped_count} new songs found.")
        self.refresh_table_with_sort()
        self.update_record_count()
        if not self.stop_requested:
            self.set_status_message("Song Download in Progress")
            self.download_new_tracks()
        else:
            self.end_operation("Operation stopped by user.")
        logger.debug("scrape_finished: Completed.")

    def download_new_tracks(self):
        if not self.check_internet_before_operation():  # Check internet at start of operation
            return

        logger.debug("download_new_tracks: Starting download new tracks operation...")
        log_id = self.db_manager.start_log_operation("Download New Tracks",
                                                     "Initiating download process for new karaoke tracks.")
        connection = sqlite3.connect(self.db_manager.db_path)
        cursor = connection.cursor()  # Get DB cursor
        cursor.execute("SELECT * FROM purchased_songs WHERE downloaded = 0")
        songs = cursor.fetchall()  # songs is a list of *tuples*, not dictionaries
        connection.close()

        if not songs:
            logger.debug("download_new_tracks: No new songs to download.")
            self.db_manager.update_log_operation(log_id, "info", "No new songs to download.")
            self.end_operation("No new songs to download.")  # End operation and inform user
            return

        song_dicts = []
        for song in songs:
            file_paths = json.loads(song[7]) if song[7] else []  # File paths is at index 7
            # Check existence within the configured download directory
            exists_flag = any(os.path.exists(os.path.join(self.download_dir, fp)) for fp in file_paths)

            # Access elements of the 'song' tuple by *integer index*, not string key
            if exists_flag:
                song_dict = {
                    "song_id": song[0],  # song_id is at index 0
                    "artist": song[1],  # artist is at index 1
                    "artist_url": song[2],  # artist_url is at index 2
                    "title": song[3],  # title is at index 3
                    "title_url": song[4],
                    "order_date": song[5],
                    "download_url": song[6],
                    "file_path": file_paths,  # Corrected, file_paths is already a list.
                    "downloaded": 1,  # Mark as downloaded
                    "extracted": song[9]  # extracted is at index 9
                }
                self.db_manager.update_song(song_dict)
                logger.debug(f"download_new_tracks: Song ID {song[0]} already exists, marked as downloaded.")

            else:
                song_dict = {
                    "song_id": song[0],
                    "artist": song[1],
                    "artist_url": song[2],
                    "title": song[3],
                    "title_url": song[4],
                    "order_date": song[5],
                    "download_url": song[6],
                    "file_path": file_paths,
                    "downloaded": song[8],  # downloaded flag is at index 8
                    "extracted": song[9]
                }
                song_dicts.append(song_dict)

        if not song_dicts:
            logger.debug("download_new_tracks: No songs to download after checking existing files.")
            self.db_manager.update_log_operation(log_id, "info",
                                                 "No songs to download after checking for existing files.")
            self.end_operation("No songs to download.")
            return

        self.downloader = SongDownloader(self.config_manager.get_config()["Settings"], self.session, parent=self)
        
        # Connect individual download completion to table refresh
        self.downloader.song_download_completed.connect(self.on_song_download_completed)
        
        # Create or show the Current Downloads dialog (persists for the session)
        if self.current_downloads_dialog is None:
            self.current_downloads_dialog = CurrentDownloadsDialog(self)
        self.current_downloads_dialog.show()
        self.current_downloads_dialog.raise_()
        self.current_downloads_dialog.activateWindow()
        
        self.download_thread = DownloadThread(
            song_dicts,  # Pass the list of dictionaries
            self.downloader,
            self.db_manager,
            unzip_songs=self.unzip_songs,
            delete_zip=self.delete_zip_after_extraction
        )
        self.download_thread.log_id = log_id  # Attach log_id to thread
        self.download_thread.progress.connect(self.update_operation_progress)
        self.download_thread.finished.connect(lambda: self.download_finished(log_id=log_id))  # Pass log_id
        self.download_thread.error.connect(self.handle_error)
        
        # Connect download thread signals to the Current Downloads dialog
        self.download_thread.song_started.connect(self.current_downloads_dialog.add_download_from_thread)
        self.download_thread.song_progress.connect(self.current_downloads_dialog.update_progress)
        self.download_thread.song_finished.connect(self.current_downloads_dialog.download_finished)
        self.download_thread.song_failed.connect(self.current_downloads_dialog.download_failed)
        
        # Also connect the downloader's signals for progress updates
        self.downloader.download_progress.connect(
            lambda sid, prog: self.current_downloads_dialog.update_progress(sid, prog, "-- KB/sec")
        )
        self.downloader.download_finished.connect(self.current_downloads_dialog.download_finished)
        self.downloader.download_failed.connect(self.current_downloads_dialog.download_failed)
        
        self.download_thread.start()
        logger.debug("download_new_tracks: Download thread started.")

    def download_finished(self, log_id):
        logger.debug("download_finished: Download thread finished.")
        if self.download_thread and getattr(self.download_thread, 'stop_downloading_flag', False):
            self.db_manager.update_log_operation(log_id, "cancelled", "Download process was cancelled by the user.")
            self.end_operation("Downloads cancelled by user.")
            return

        downloaded_count = self.db_manager.get_newly_downloaded_song_count()  # Get count of newly downloaded songs
        self.db_manager.update_log_operation(log_id, "success",
                                             f"Downloads completed. {downloaded_count} songs downloaded.")
        self.refresh_table_with_sort()
        self.update_record_count()
        self.end_operation()
        logger.debug("download_finished: Completed.")

    def full_sync(self):
        if not self.check_internet_before_operation():  # Check internet at start of operation
            return

        logger.debug("full_sync: Starting full sync operation...")
        log_id = self.db_manager.start_log_operation("Full Sync",
                                                     "Initiating full sync process.")
        reply = QMessageBox.question(self, "Full Sync",
                                     "This will clear all existing records from the database and re-sync all songs. Song files are not affected. Continue?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            logger.debug("full_sync: User confirmed full sync.")
            self.start_operation("Performing full sync...")
            self.db_manager.log_operation(datetime.now().isoformat(), "Full Sync",
                                          "Full sync started.", "info")  # Log to old table
            self.db_manager.clear_database()
            self.update_record_count()
            self.setup_download_directory()

            # Re-initialize scraper for full sync
            self.session = requests.Session()
            self.scraper = SongScraper("https://www.karaoke-version.com", self.username, self.password, self.session)
            try:
                self.scraper.login()
                logger.debug("full_sync: Scraper logged in for full sync.")
                self.db_manager.update_log_operation(log_id, "running",
                                                     "Scraper logged in successfully for full sync.")
            except Exception as e:
                logger.error(f"full_sync: Scraper login failed during full sync: {e}")
                self.db_manager.update_log_operation(log_id, "failed", f"Scraper login failed during full sync: {e}")
                self.end_operation(str(e))
                return

            self.scrape_thread = ScrapeThread(self.scraper, self.db_manager, validate=True)
            self.scrape_thread.log_id = log_id  # Attach log_id to thread
            self.scrape_thread.progress.connect(self.update_operation_progress)
            self.scrape_thread.finished.connect(lambda: self.full_sync_finished(log_id=log_id))  # Pass log_id
            self.update_record_count()
            self.scrape_thread.error.connect(self.handle_error)
            self.scrape_thread.start()
            logger.debug("full_sync: Full sync scrape thread started.")
        else:
            logger.debug("full_sync: User cancelled full sync.")
            self.db_manager.update_log_operation(log_id, "cancelled", "Full sync cancelled by user.")
            self.end_operation("Full sync cancelled.")

    def full_sync_finished(self, log_id):
        logger.debug("full_sync_finished: Full sync scraping finished.")
        synced_count = self.db_manager.get_total_song_count()  # Get total songs after sync
        
        # Now check which songs are already downloaded by checking file paths
        connection = sqlite3.connect(self.db_manager.db_path)
        cursor = connection.cursor()
        cursor.execute("SELECT song_id, file_path FROM purchased_songs")
        songs = cursor.fetchall()
        
        # Update downloaded status for songs that have existing files
        for song_id, file_path_json in songs:
            if file_path_json:
                file_paths = json.loads(file_path_json) if file_path_json else []
                # Check if any of the file paths exist in the download directory
                exists_flag = any(os.path.exists(os.path.join(self.download_dir, fp)) for fp in file_paths if file_paths)
                if exists_flag:
                    # Mark as downloaded in the database
                    cursor.execute("UPDATE purchased_songs SET downloaded = 1 WHERE song_id = ?", (song_id,))
                    logger.debug(f"full_sync_finished: Marked song {song_id} as downloaded (file exists)")
        
        connection.commit()
        connection.close()
        
        self.db_manager.update_log_operation(log_id, "success",
                                             f"Full sync completed. {synced_count} songs synced.")
        self.refresh_table_with_sort()
        self.update_record_count()
        
        # Now download any songs where downloaded is false
        if not self.stop_requested:
            self.set_status_message("Song Download in Progress")
            self.download_new_tracks()
        else:
            self.end_operation("Operation stopped by user.")
        logger.debug("full_sync_finished: Completed.")

    def start_operation(self, message = "Starting operation..."):
        self.operation_in_progress = True
        self.stop_requested = False
        self.stop_action.setEnabled(True)
        self.stop_action.setVisible(True)  # Make visible during operations
        self.stop_poll_timers()
        self.status_progress.setVisible(False)  # Hide progress bar from status bar
        self.set_status_message(message)  # Set status bar message
        self.update_tray_tooltip()
        self.update_tray_menu()  # Update tray menu to show Stop Operation
        logger.debug(f"start_operation: Operation started: {message}")

    def end_operation(self, message = "Operation completed."):
        logger.debug(f"end_operation: Operation ending with message: {message}")
        self.operation_in_progress = False
        self.stop_requested = False
        self.stop_action.setEnabled(False)
        self.stop_action.setVisible(False)  # Hide when no operations running
        self.set_status_message(message)
        self.status_progress.setVisible(False)
        self.update_tray_tooltip()
        self.update_tray_menu()  # Update tray menu to hide Stop Operation
        if self.polling_enabled:
            self.restart_poll_timers()

    def update_operation_progress(self, progress, message):
        # No longer updating progress bar - just update status message
        self.set_status_message(message)  # Use set_status_message to also update tray tooltip
        logger.debug(f"update_operation_progress: Message: {message}")

    def handle_error(self, message):
        logger.error(message)
        QMessageBox.critical(self, "Error", message)
        self.end_operation("Error occurred.")
        logger.debug(f"handle_error: Error handled: {message}")

    def closeEvent(self, event):
        self.quit_application()
        event.accept()
        logger.debug("closeEvent: Close event accepted, application quitting.")

    def quit_application(self):
        logger.debug("quit_application: Quitting application...")
        self.end_operation("Closing application...")
        self.stop_poll_timers()
        
        # Signal threads to stop but don't wait (non-blocking)
        if self.scrape_thread and self.scrape_thread.isRunning():
            self.scrape_thread.stop_scraping()
            logger.debug("Signaled scrape thread to stop")
        if self.download_thread and self.download_thread.isRunning():
            self.download_thread.stop_downloading()
            logger.debug("Signaled download thread to stop")
            
        if self.tray_icon:
            self.tray_icon.hide()
        self.close()

    def minimize_to_tray(self):
        self.hide()
        if self.tray_icon:
            self.tray_icon.show()
        self.set_status_message("Minimized")
        logger.debug("minimize_to_tray: Minimized to tray.")

    def refresh_table(self):
        self.refresh_table_with_sort()
        self.update_record_count()
        self.set_status_message("Table refreshed")
        logger.debug("refresh_table: Table refreshed.")

    def view_logs(self):
        from .operationLogsDialog import LogsDialog  # Import here to avoid circular import
        logger.debug("view_logs: Opening log window...")
        logs_dialog = LogsDialog(self.db_manager, self)
        logs_dialog.resize(1000, 700)  # Set default size here
        logs_dialog.exec()
        logger.debug("view_logs: Log window closed.")

    def view_current_downloads(self):
        logger.debug("view_current_downloads: Opening current downloads window...")
        
        # Create dialog if it doesn't exist (persists for the session)
        if self.current_downloads_dialog is None:
            self.current_downloads_dialog = CurrentDownloadsDialog(self)
        
        self.current_downloads_dialog.show()
        self.current_downloads_dialog.raise_()
        self.current_downloads_dialog.activateWindow()
        logger.debug("view_current_downloads: Current downloads window opened.")

    def on_header_clicked(self, logical_index):
        """Track table sort changes"""
        self.current_sort_column = logical_index
        self.current_sort_order = self.table_view.horizontalHeader().sortIndicatorOrder()
        logger.debug(f"Table sorted by column {logical_index}, order: {self.current_sort_order}")

    def stop_current_operation(self):
        """Stop the current operation gracefully"""
        logger.debug("stop_current_operation: User requested to stop operation")
        self.stop_requested = True
        self.stop_action.setEnabled(False)
        # Keep it visible but disabled to show operation is stopping
        self.update_tray_menu()  # Update tray menu to reflect disabled state
        
        if self.scrape_thread and self.scrape_thread.isRunning():
            logger.debug("Stopping scrape thread...")
            self.scrape_thread.stop_scraping()
            self.set_status_message("Stopping scraping operation...")
            
        if self.download_thread and self.download_thread.isRunning():
            logger.debug("Stopping download thread...")
            self.download_thread.stop_downloading()
            self.set_status_message("Stopping downloads (waiting for active downloads to complete)...")

    def refresh_table_with_sort(self):
        """Refresh table while maintaining current sort order"""
        logger.debug("refresh_table_with_sort: Refreshing table with current sort state")
        
        # Store current selection if any
        selected_rows = []
        selection_model = self.table_view.selectionModel()
        if selection_model:
            for index in selection_model.selectedRows():
                song_id_item = self.table_model.item(index.row(), 2)  # Song ID column
                if song_id_item:
                    selected_rows.append(song_id_item.text())
        
        # Reload data
        self.load_table_view_data()
        
        # Restore sort order
        self.table_view.sortByColumn(self.current_sort_column, self.current_sort_order)
        
        # Try to restore selection
        if selected_rows:
            selection_model = self.table_view.selectionModel()
            for row in range(self.table_model.rowCount()):
                song_id_item = self.table_model.item(row, 2)
                if song_id_item and song_id_item.text() in selected_rows:
                    selection_model.select(song_id_item.index(), selection_model.SelectionFlag.Select | selection_model.SelectionFlag.Rows)

    def on_song_download_completed(self, song_id):
        """Handle individual song download completion"""
        logger.debug(f"Song download completed: {song_id}")
        # Refresh table to show updated download status
        QTimer.singleShot(100, self.refresh_table_with_sort)  # Small delay to ensure DB is updated

    def check_internet_before_operation(self):
        if not self.is_internet_available():
            QMessageBox.warning(self, "No Internet Connection",
                                "Internet connection is not available. Please check your connection and try again.")
            logger.debug("internet_connectivity: An internet connection was not detected.")
            return False  # Indicate no internet, do not proceed
        logger.debug("internet_connectivity: An internet connection was detected.")
        return True  # Internet is available, proceed
