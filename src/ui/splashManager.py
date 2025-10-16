# src/ui/splashManager.py

from PySide6.QtWidgets import QSplashScreen
from PySide6.QtCore import QObject, Signal

class SplashManager(QObject):
    close_splash_signal = Signal()

    def __init__(self, splash: QSplashScreen):
        super().__init__()
        self.splash = splash
        self.close_splash_signal.connect(self.close_splash)

    def close_splash(self):
        self.splash.close()

# Initialize the manager (this creates a global instance)
splash_manager = None