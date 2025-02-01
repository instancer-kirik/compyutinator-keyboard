#!/usr/bin/env python3
"""
Main entry point for the Compyutinator Keyboard application.
"""

import sys
import os
import signal
import argparse
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from .keyboard_manager import KeyboardManager
from compyutinator_common import setup_qt_app

def signal_handler(signum, frame):
    """Handle interrupt signals."""
    QApplication.quit()

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Compyutinator Keyboard Manager")
    parser.add_argument('--config', '-c', type=str, help='Path to KMonad config file')
    parser.add_argument('--auto-start', '-a', action='store_true', help='Automatically start KMonad')
    args = parser.parse_args()

    # Set up signal handling
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    app = setup_qt_app()
    
    # Create a timer to process signals
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # Let Python process signals
    timer.start(100)  # Check every 100ms
    
    manager = KeyboardManager()
    
    # Load config if specified
    if args.config:
        config_path = os.path.expanduser(args.config)
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                manager.keyboard_layout.config_edit.setText(f.read())
            if args.auto_start:
                manager.keyboard_layout.toggle_kmonad()
    
    manager.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main()) 