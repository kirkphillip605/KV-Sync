# src/ui/splashManager.py

from PyQt6.QtWidgets import QSplashScreen
from PyQt6.QtCore import QObject, pyqtSignal

class SplashManager(QObject):
    close_splash_pyqtSignal = pyqtSignal()

    def __init__(self, splash: QSplashScreen):
        super().__init__()
        self.splash = splash
        self.close_splash_pyqtSignal.connect(self.close_splash)

    def close_splash(self):
        self.splash.close()

# Initialize the manager (this creates a global instance)
splash_manager = None