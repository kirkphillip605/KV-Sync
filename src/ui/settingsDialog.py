# src/ui/settingsDialog.py
import logging
import sqlite3

import requests  # Import requests
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                             QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget,
                             QVBoxLayout, QWidget)
from src.ui.splashManager import splash_manager
from src.core.date_utils import get_available_display_formats


logger = logging.getLogger(__name__)


def create_horizontal_line():
    """Create a horizontal line separator."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFrameShadow(QFrame.Shadow.Raised)
    return line


class SettingsDialog(QDialog):
    credentials_validated = pyqtSignal(bool)  # pyqtpyqtSignal for credential validation status

    def __init__(self, parent = None):
        super().__init__(parent)
        if splash_manager:
            splash_manager.close_splash_pyqtSignal.emit()
        self.setWindowTitle("Vibe SongSync - Configuration")
        self.setMinimumWidth(500)  # Make the dialog wider
        self.setModal(True)

        self.parent_window = parent
        self.config_manager = parent.config_manager
        self.main_layout = QVBoxLayout(self)  # Use a main layout for the entire dialog

        # Create a frame to wrap the tabs for separation
        tabs_frame = QFrame(self)
        tabs_layout = QVBoxLayout(tabs_frame)

        # Create tabs for organizing settings
        self.tabs = QTabWidget(self)
        self.tabs.setStyleSheet("QTabWidget::tab-bar { alignment: center; }")  # Center the tabs
        tabs_layout.addWidget(self.tabs)

        # Create sections using QGroupBoxes for the "sunken" panel effect
        self.credentials_tab = self.create_tab("Please enter your username and password for Karaoke-Version below.",
                                               self.create_credentials_layout())
        self.storage_tab = self.create_tab(
            "Select the location where downloaded song files should be saved. The pattern to use is: 'Artist - Title - SongID'",
            self.create_storage_layout())
        self.log_level_tab = self.create_tab(
            "Choose the desired log level and maximum number of logfiles to save. If you are unsure what to choose, set Log Level to 'INFO' and max logs to '10'",
            self.create_log_level_layout())
        self.display_tab = self.create_tab(
            "Choose how dates should be displayed throughout the application. This affects how purchase dates are shown in the song list.",
            self.create_display_layout())

        # Add tabs to the tab widget
        self.tabs.addTab(self.credentials_tab, "Karaoke-Version")
        self.tabs.addTab(self.storage_tab, "File Handling")
        self.tabs.addTab(self.log_level_tab, "Logging")
        self.tabs.addTab(self.display_tab, "Display")

        self.main_layout.addWidget(tabs_frame)  # Add the tabs wrapped in a frame

        # buttons_layout = QVBoxLayout(buttons_frame)

        # Dialog buttons (moved to the bottom)
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_button = self.button_box.button(QDialogButtonBox.StandardButton.Save)
        self.save_button.setEnabled(False)  # Start with Save button disabled
        self.button_box.accepted.connect(self.save_settings)
        self.button_box.rejected.connect(self.reject)

        # self.main_layout.addWidget(self.button_box)
        self.main_layout.addWidget(self.button_box)  # Add the button frame to the layout

        self.load_settings()
        self.check_required_fields()  # Check on init.
        self.credentials_validated.connect(self.handle_credentials_validated)  # Connect the pyqtSignal

    def create_tab(self, inst, layout):
        """Creates a tab with a section title and layout."""
        tab = QWidget()  # Create a new QWidget for the tab content
        tab_layout = QVBoxLayout(tab)
        instruction_label = QLabel(f"{inst}")
        instruction_label.setWordWrap(True)
        instruction_label.setStyleSheet("font-style: italic; color: gray;")
        tab_layout.addWidget(instruction_label)
        tab_layout.addLayout(layout)  # Add the section layout
        return tab

    def create_credentials_layout(self):
        """Creates a QFormLayout for the credentials section."""
        form_layout = QFormLayout()

        self.username_input = QLineEdit(self)
        self.username_input.setMinimumWidth(400)  # Wider input fields
        self.username_input.textChanged.connect(self.check_required_fields)
        self.password_input = QLineEdit(self)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_input.setMinimumWidth(400)  # Wider input fields
        self.password_input.textChanged.connect(self.check_required_fields)
        self.validation_status_label = QLabel("")  # Label to show validation status
        self.reset_password_label = QLabel("")

        self.validate_button = QPushButton("Authenticate", self)
        self.validate_button.clicked.connect(self.validate_credentials)
        self.reset_button = QPushButton("Change Credentials", self)  # New reset button
        self.reset_button.clicked.connect(self.reset_credentials)
        self.reset_button.hide()  # Initially hidden

        form_layout.addRow("Username: ", self.username_input)
        form_layout.addRow("Password: ", self.password_input)
        form_layout.addRow("", self.reset_password_label)

        hbox = QHBoxLayout()  # Put validate/reset buttons in a hbox
        hbox.addWidget(self.validate_button)
        hbox.addWidget(self.reset_button)
        hbox.addWidget(self.validation_status_label)  # Add status label
        # hbox.addWidget(self.reset_password_label)  # Add status label
        hbox.addStretch()  # Push buttons to the left

        form_layout.addRow(hbox)  # Add the hbox to the form layout

        return form_layout

    def create_storage_layout(self):
        """Creates a QVBoxLayout for the storage section."""
        vbox_layout = QVBoxLayout()

        # Download directory
        hbox_download_dir = QHBoxLayout()
        self.download_dir_label = QLabel("Download Directory:")
        self.download_dir_input = QLineEdit(self)
        self.download_dir_input.setReadOnly(True)
        self.browse_button = QPushButton("Browse...", self)
        self.browse_button.clicked.connect(self.browse_download_dir)
        hbox_download_dir.addWidget(self.download_dir_input)
        hbox_download_dir.addWidget(self.browse_button)
        vbox_layout.addWidget(self.download_dir_label)  # Add label
        vbox_layout.addLayout(hbox_download_dir)

        # Unzip and Delete options (using QHBoxLayout for side-by-side)
        hbox_options = QHBoxLayout()
        self.unzip_songs_checkbox = QCheckBox("Unzip Songs", self)
        self.delete_zip_checkbox = QCheckBox("Delete Zip After Extraction", self)
        hbox_options.addWidget(self.unzip_songs_checkbox)
        hbox_options.addWidget(self.delete_zip_checkbox)
        vbox_layout.addLayout(hbox_options)

        # Polling time (using QHBoxLayout for label and spinbox)
        hbox_polling = QHBoxLayout()
        self.polling_time_label = QLabel("Polling Time (seconds):")
        self.polling_time_input = QSpinBox(self)
        self.polling_time_input.setRange(1, 3600)  # Set a reasonable range (1 second to 1 hour)
        self.polling_time_input.setSingleStep(10)  # Set a reasonable increment
        self.polling_time_input.setFixedWidth(100)  # Wider spinbox
        self.polling_time_display = QLabel()  # Label to display minutes/seconds
        self.polling_time_input.valueChanged.connect(self.update_polling_time_display)

        hbox_polling.addWidget(self.polling_time_label)
        hbox_polling.addWidget(self.polling_time_input)
        hbox_polling.addWidget(self.polling_time_display)  # add display label to layout
        hbox_polling.addStretch()  # Push label/input to the left
        vbox_layout.addLayout(hbox_polling)

        return vbox_layout

    def create_log_level_layout(self):
        layout = QHBoxLayout()
        self.log_level_label = QLabel("Log Level:")
        self.log_level_combo = QComboBox(self)
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
        self.log_level_combo.setMinimumWidth(150)

        # Polling time (using QHBoxLayout for label and spinbox)
        self.max_logs_label = QLabel("Maximum Number of Logfiles:")
        self.max_logs_input = QSpinBox(self)
        self.max_logs_input.setRange(1, 50)  # Set a reasonable range (1 second to 1 hour)
        self.max_logs_input.setSingleStep(1)  # Set a reasonable increment
        self.max_logs_input.setFixedWidth(100)  # Wider spinbox

        layout.addWidget(self.log_level_label)
        layout.addWidget(self.log_level_combo)
        layout.addWidget(self.max_logs_label)
        layout.addWidget(self.max_logs_input)
        layout.addStretch()  # Push to the left
        return layout

    def create_display_layout(self):
        """Create layout for display settings including date format preference."""
        layout = QHBoxLayout()
        self.date_format_label = QLabel("Date Format:")
        self.date_format_combo = QComboBox(self)
        
        # Populate with available formats
        available_formats = get_available_display_formats()
        for format_key, format_description in available_formats:
            self.date_format_combo.addItem(format_description, format_key)
        
        self.date_format_combo.setMinimumWidth(200)
        
        layout.addWidget(self.date_format_label)
        layout.addWidget(self.date_format_combo)
        layout.addStretch()  # Push to the left
        return layout

    def update_polling_time_display(self):
        seconds = self.polling_time_input.value()
        minutes = seconds // 60
        seconds_remainder = seconds % 60
        self.polling_time_display.setText(f"Check for updates every {minutes} Minutes ({seconds} Seconds)")

    def load_settings(self):
        config = self.config_manager.get_config()

        # Load the username and password from config
        username = config.get("Credentials", "username", fallback="")
        password = config.get("Credentials", "password", fallback="")

        # Set the input fields with the loaded values
        self.username_input.setText(username)
        self.password_input.setText(password)

        # If both username and password exist, make inputs read-only and hide validate, show reset
        if username and password:
            self.username_input.setReadOnly(True)
            self.password_input.setReadOnly(True)
            self.validate_button.hide()
            self.reset_button.show()
            self.validation_status_label.setText("Authenticated")
            self.validation_status_label.setStyleSheet("color: green;")
        else:
            self.username_input.setReadOnly(False)
            self.password_input.setReadOnly(False)
            self.validate_button.show()
            self.reset_button.hide()
            self.validation_status_label.clear()

        # Load other settings
        self.download_dir_input.setText(config.get("Settings", "download_dir", fallback=""))
        self.unzip_songs_checkbox.setChecked(config.getboolean("Settings", "unzip_songs", fallback=False))
        self.delete_zip_checkbox.setChecked(
            config.getboolean("Settings", "delete_zip_after_extraction", fallback=False))
        self.polling_time_input.setValue(config.getint("Settings", "polling_time", fallback=300))  # Use setValue
        self.log_level_combo.setCurrentText(config.get("Logging", "log_level", fallback="INFO"))
        self.max_logs_input.setValue(config.getint("Logging", "max_logs", fallback=10))
        
        # Load date format preference
        if not config.has_section("Display"):
            config.add_section("Display")
        date_format = config.get("Display", "date_format", fallback="yyyy-MM-dd")
        index = self.date_format_combo.findData(date_format)
        if index >= 0:
            self.date_format_combo.setCurrentIndex(index)
        else:
            self.date_format_combo.setCurrentIndex(0)  # Default to first option

    def check_required_fields(self):
        """Check if all required fields are filled in and highlight tabs if any are missing."""
        missing_fields = False
        exception_icon = QIcon("resources/icons/buttons/exception.png")  # Load the icon

        # Check credentials
        if not self.username_input.text() or not self.password_input.text():
            self.tabs.setTabText(0, "Karaoke-Version")  # Highlight tab
            self.tabs.setTabIcon(0, exception_icon)  # Add the icon to the tab
            missing_fields = True
        else:
            self.tabs.setTabText(0, "Karaoke-Version")
            self.tabs.setTabIcon(0, QIcon())  # Clear the icon if no field is missing

        # Check storage settings
        if not self.download_dir_input.text():
            self.tabs.setTabText(1, "File Handling")  # Highlight tab
            self.tabs.setTabIcon(1, exception_icon)  # Add the icon to the tab
            missing_fields = True
        else:
            self.tabs.setTabText(1, "File Handling")
            self.tabs.setTabIcon(1, QIcon())  # Clear the icon if no field is missing

        # If any required fields are missing, disable the Save button
        if missing_fields:
            self.save_button.setEnabled(False)
        else:
            self.save_button.setEnabled(True)

    def browse_download_dir(self):
        """Browse for the download directory."""
        directory = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if directory:
            self.download_dir_input.setText(directory)
            self.check_required_fields()  # Re-check after browsing.

    def validate_credentials(self):
        """Validates the entered username and password against the Karaoke Version website."""
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Credentials Missing",
                                "Valid credentials are required. Please re-enter your username and password.")
            return
        else:
            self.validation_status_label.setText("Authenticated")
            self.validation_status_label.setStyleSheet("color: green;")
            self.username_input.setReadOnly(True)
            self.password_input.setReadOnly(True)
            self.validate_button.hide()  # hide validate and show reset
            self.reset_button.show()
            self.credentials_validated.emit(True)  # emit pyqtSignal if validation is successful

        try:
            # Use a session for efficiency (keeps connection alive)
            with requests.Session() as session:
                login_url = "https://www.karaoke-version.com/my/login.html"
                response = session.post(login_url, data={"frm_login": username, "frm_password": password})

                # Check for successful login (presence of "logout" link is a good indicator)
                if response.status_code == 200 and "logout" in response.text.lower():
                    QMessageBox.information(self, "Authentication Successful",
                                            "SUCCESS! <p>Authentication was sufccessful using the credentials provided.")
                    self.validation_status_label.setText("Authenticated")
                    self.validation_status_label.setStyleSheet("color: green;")
                    self.username_input.setReadOnly(True)
                    self.password_input.setReadOnly(True)
                    self.validate_button.hide()  # hide validate and show reset
                    self.reset_button.show()
                    self.credentials_validated.emit(True)  # emit pyqtSignal if validation is successful

        except requests.RequestException as e:
            logger.error(f"Validation request failed: {e}")
            QMessageBox.critical(self, "Authentication Exception",
                                 f"An error occurred while attempting to validate your credentials. Please try again later:<p>{e}")
            self.credentials_validated.emit(False)  # Emit pyqtSignal

    def save_settings(self):
        """Save settings to the config manager."""
        if not self.save_button.isEnabled():
            return  # Should not happen, but good practice

        config = self.config_manager.get_config()
        config.set("Credentials", "username", self.username_input.text())
        config.set("Credentials", "password", self.password_input.text())
        config.set("Settings", "download_dir", self.download_dir_input.text())
        config.set("Settings", "unzip_songs", str(self.unzip_songs_checkbox.isChecked()))
        config.set("Settings", "delete_zip_after_extraction", str(self.delete_zip_checkbox.isChecked()))
        config.set("Settings", "polling_time", str(self.polling_time_input.value()))  # Use .value()
        config.set("Settings", "log_level", self.log_level_combo.currentText().lower())  # save log level
        config.set("Settings", "max_logs", str(self.max_logs_input.value()))
        
        # Save date format preference
        if not config.has_section("Display"):
            config.add_section("Display")
        config.set("Display", "date_format", self.date_format_combo.currentData())

        self.config_manager.save_config()
        self.accept()

    def reset_credentials(self):
        """Reset the credentials input fields and enable editing."""
        # Clear the input fields
        self.username_input.clear()
        self.password_input.clear()

        # Set input fields to editable mode
        self.username_input.setReadOnly(False)
        self.password_input.setReadOnly(False)

        # Clear the validation status label
        self.validation_status_label.clear()

        # Show the "Authenticate" button and hide the "Reset" button
        self.validate_button.show()
        self.reset_button.hide()

    def handle_credentials_validated(self, valid):
        # This method could be expanded if we wanted. For now, we don't need any special behaviour.
        pass
