# src/core/config.py
import base64
import configparser
import logging
import os
import sys
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {"Credentials": {"username": "", "password": ""},
    "Settings": {"download_dir": "", "unzip_songs": "False", "delete_zip_after_extraction": "False",
                 "polling_time": "300", "openkj_db": "", "auto_add_openkj": "False", "log_level": "INFO",
                 "max_logs": "10"}}

ENCRYPTION_KEY_ENV_VAR = "VIBE_SONGSYNC_ENCRYPTION_KEY"  # The environment variable storing the encryption key
SECRET_KEY = "vibe_song_sync_secret_key"  # Use a secret passphrase to derive the encryption key


class ConfigManager:
    def __init__(self, config_path):
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.key = None
        self.cipher = None
        self.load_or_create_config()

    def _get_encryption_key(self):
        # Load the encryption key from an environment variable
        key = os.getenv(ENCRYPTION_KEY_ENV_VAR)
        if key:
            logger.debug("Loaded encryption key from environment variable.")
            return base64.urlsafe_b64decode(key.encode('utf-8'))
        else:
            # Generate and securely store a new key
            key = self._generate_encryption_key_from_passphrase()
            self._store_encryption_key_in_env(key)
            return key

    def _generate_encryption_key_from_passphrase(self):
        # Derive a key using PBKDF2 with a salt (to prevent rainbow table attacks)
        kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32,  # 256-bit key for AES-256
            salt=SECRET_KEY.encode(), iterations=100000, backend=default_backend())
        key = kdf.derive(SECRET_KEY.encode())  # Derive the encryption key from the passphrase
        logger.info("Derived new encryption key from passphrase.")
        return key

    def _store_encryption_key_in_env(self, key):
        # Store the generated key in an environment variable for future use (or secure vault)
        os.environ [ENCRYPTION_KEY_ENV_VAR] = base64.urlsafe_b64encode(key).decode('utf-8')
        logger.info("Stored encryption key in environment variable for future use.")

    def _initialize_cipher(self):
        # Initialize AES cipher in CBC mode with the encryption key
        self.key = self._get_encryption_key()
        self.cipher = Cipher(algorithms.AES(self.key), modes.CBC(self.key [:16]), backend=default_backend())

    def load_or_create_config(self):
        self._initialize_cipher()
        if not os.path.exists(self.config_path):
            logger.info(f"Config file not found. Creating default config at: {self.config_path}")
            self._create_default_config()
        else:
            try:
                self.load_config()
            except (ValueError, OSError):
                logger.exception("Failed to load config — possibly corrupted or wrong key. Regenerating config.")
                self.handle_config_error()

    def _create_default_config(self):
        for section, values in DEFAULT_CONFIG.items():
            self.config [section] = values
        self.save_config()

    def load_config(self):
        with open(self.config_path, "rb") as configfile:
            encrypted_data = configfile.read()

        # Decrypt data
        decryptor = self.cipher.decryptor()
        padded_data = decryptor.update(encrypted_data) + decryptor.finalize()

        # Remove padding
        unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
        decrypted_data = unpadder.update(padded_data) + unpadder.finalize()

        self.config.read_string(decrypted_data.decode('utf-8'))
        logger.debug("Loaded and decrypted config file.")

    def save_config(self):
        # Save the plain config to a temporary file
        config_string = ""
        with open(self.config_path, "w", encoding="utf-8") as configfile:
            self.config.write(configfile)

        # Encrypt the plain config
        with open(self.config_path, "rb") as configfile:
            plain_data = configfile.read()

        # Pad the data to make it a multiple of the block size
        padder = padding.PKCS7(algorithms.AES.block_size).padder()
        padded_data = padder.update(plain_data) + padder.finalize()

        # Encrypt the data
        encryptor = self.cipher.encryptor()
        encrypted_data = encryptor.update(padded_data) + encryptor.finalize()

        with open(self.config_path, "wb") as configfile:
            configfile.write(encrypted_data)
            logger.debug("Saved encrypted config file.")

    def handle_config_error(self):
        try:
            if os.path.exists(self.config_path):
                os.remove(self.config_path)
                logger.warning(f"Deleted corrupted config file: {self.config_path}")
        except Exception as e:
            logger.exception(f"Failed to delete corrupted config file: {e}")

        self._create_default_config()
        logger.info("Created fresh configuration. Restarting application.")

        # Restart the app
        python = sys.executable
        os.execl(python, python, *sys.argv)

    def get_config(self):
        return self.config

    def get(self, section, option, fallback = None):
        return self.config.get(section, option, fallback=fallback)

    def getboolean(self, section, option, fallback = False):
        return self.config.getboolean(section, option, fallback=fallback)

    def getint(self, section, option, fallback = 0):
        return self.config.getint(section, option, fallback=fallback)

    def set(self, section, option, value):
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, option, value)

    def has_option(self, section, option):
        return self.config.has_option(section, option)