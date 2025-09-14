# Overview

Vibe SongSync is a desktop karaoke track management application built with PyQt6. It provides a complete solution for purchasing, downloading, and organizing karaoke tracks from karaoke-version.com. The application features automated scraping of purchased songs, batch downloading capabilities, file extraction and organization, and integration with OpenKJ karaoke software.

The system is designed as a standalone desktop application that helps karaoke enthusiasts manage their digital music library with features like intelligent date parsing, concurrent downloads, operation logging, and secure credential management.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Desktop Application Framework
- **Frontend**: PyQt6-based GUI with tabbed interface, splash screens, and system tray integration
- **Architecture Pattern**: Model-View-Controller (MVC) with separate UI, core logic, and data layers
- **Threading**: Multi-threaded design using QThread for non-blocking operations (scraping, downloading)
- **Configuration**: INI-based configuration with encrypted credential storage using cryptography library

## Data Management
- **Database**: SQLite with custom DatabaseManager for purchased songs and operation logs
- **Models**: Custom table models for displaying song data and operation logs in UI tables
- **Storage**: Local file system for downloaded karaoke tracks with configurable download directories

## Core Components

### Scraping Engine
- **Web Scraping**: BeautifulSoup4 for HTML parsing of karaoke-version.com
- **Session Management**: Persistent HTTP sessions with authentication
- **Date Intelligence**: Smart date parsing supporting multiple international formats
- **Concurrent Processing**: ThreadPoolExecutor for parallel page processing

### Download System
- **Multi-threaded Downloads**: Concurrent file downloads with progress tracking
- **File Management**: Automatic ZIP extraction with configurable cleanup
- **Progress Monitoring**: Real-time download progress with Qt signals
- **Error Handling**: Retry mechanisms and comprehensive error reporting

### Security & Configuration
- **Credential Encryption**: PBKDF2-based key derivation with AES encryption for sensitive data
- **Environment Variables**: Secure key storage using system environment variables
- **Configuration Management**: Centralized config with validation and defaults

## External Dependencies

### Core Libraries
- **PyQt6**: Primary GUI framework for desktop interface
- **requests**: HTTP client for web scraping and file downloads
- **beautifulsoup4**: HTML parsing for website content extraction
- **cryptography**: Secure credential storage and encryption
- **sqlite3**: Built-in database for local data persistence

### Utility Libraries
- **appdirs**: Cross-platform application directory management
- **python-dateutil**: Enhanced date parsing capabilities
- **keyring**: System keyring integration for credential storage
- **lxml**: XML/HTML parsing backend for BeautifulSoup

### File Management
- **zipfile**: Built-in ZIP archive handling for karaoke track extraction
- **pathlib**: Modern path manipulation and file system operations

### Integration Points
- **karaoke-version.com**: Primary data source for purchased karaoke tracks
- **OpenKJ Software**: Optional integration for automatic library updates
- **System Tray**: Desktop integration for background operations
- **File System**: Local storage management for downloaded tracks and configuration