# main.py
import logging
import os
import sys
import time
import appdirs
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QSplashScreen
from PyQt6.QtCore import QTimer, Qt

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.ui.mainWindow import MainWindow


def setup_logging(log_dir = "logs", log_level = logging.INFO):
    """Sets up logging with file rotation and console output."""
    logger = logging.getLogger('vibe_manager')
    logger.setLevel(log_level)

    os.makedirs(log_dir, exist_ok=True)
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")
    log_file = os.path.join(log_dir, f"vibe_manager_{timestamp}.log")

    fh = logging.FileHandler(log_file)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    fh.setFormatter(formatter)
    fh.setLevel(log_level)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    ch.setLevel(log_level)
    logger.addHandler(ch)
    return logger


def rotate_logs(log_dir, logger, max_logs = 5):
    """Rotates log files, keeping only the 'max_logs' most recent."""
    log_files = sorted(
        [os.path.join(log_dir, f) for f in os.listdir(log_dir) if f.startswith("vibe_manager_") and f.endswith(".log")])

    while len(log_files) > max_logs:
        oldest_log = log_files.pop(0)
        try:
            os.remove(oldest_log)
            logger.info(f"Deleted old log file: {oldest_log}")
        except OSError as e:
            logger.error(f"Error deleting log file {oldest_log}: {e}")


def main():
    appname = "Vibe SongSync"
    appauthor = "Vibe Entertainment"
    user_data_dir = appdirs.user_data_dir(appname, appauthor)
    os.makedirs(user_data_dir, exist_ok=True)

    log_dir = os.path.join(user_data_dir, "logs")
    logger = setup_logging(log_dir=log_dir)
    logger.debug(f"Using user data directory: {user_data_dir}")

    config_path = os.path.join(user_data_dir, "config.ini")
    config_manager = ConfigManager(config_path)
    config = config_manager.get_config()

    log_level_str = config.get("Settings", "log_level", fallback="DEBUG").upper()
    try:
        log_level = getattr(logging, log_level_str)
        if not isinstance(log_level, int):
            raise ValueError()
    except (AttributeError, ValueError):
        logger.warning(f"Invalid log level '{log_level_str}' in config. Using INFO.")
        log_level = logging.INFO

    logger.setLevel(log_level)
    logger.info(f"Logging initialized. Log level: {logging.getLevelName(log_level)}")
    rotate_logs(log_dir, logger)

    db_path = os.path.join(user_data_dir, "karaoke_library.db")
    db_manager = DatabaseManager(db_path=db_path, config_manager=config_manager)

    try:
        app = QApplication(sys.argv)
        
        # Use platform-appropriate icon with fallback
        import platform
        icon_path = "resources/main.ico" if platform.system() == "Windows" else "resources/main.png"
        app_icon = QIcon(icon_path)
        if app_icon.isNull():
            logger.warning(f"Failed to load icon from {icon_path}, trying fallback...")
            app_icon = QIcon("resources/main.png")
            if app_icon.isNull():
                logger.error("Failed to load application icon")
        app.setWindowIcon(app_icon)

        with open("resources/styles/styles.qss", "r") as stylesheet:
            app.setStyleSheet(stylesheet.read())

        window = MainWindow(config_manager, db_manager)
        window.show()
        sys.exit(app.exec())

    except Exception as e:
        logger.exception("An unhandled exception occurred:")


if __name__ == '__main__':
    main()