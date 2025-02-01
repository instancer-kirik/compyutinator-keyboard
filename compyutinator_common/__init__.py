"""Common utilities for Compyutinator applications."""

__version__ = "0.1.0"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

def get_app():
    """Get or create QApplication instance."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

def setup_qt_app():
    """Set up and return a QApplication instance with proper settings."""
    app = QApplication([])
    app.setStyle('Fusion')  # Use Fusion style for consistent look
    
    # Set dark theme palette
    palette = app.palette()
    palette.setColor(palette.ColorRole.Window, Qt.GlobalColor.black)
    palette.setColor(palette.ColorRole.WindowText, Qt.GlobalColor.white)
    palette.setColor(palette.ColorRole.Base, Qt.GlobalColor.darkGray)
    palette.setColor(palette.ColorRole.AlternateBase, Qt.GlobalColor.darkGray)
    palette.setColor(palette.ColorRole.ToolTipBase, Qt.GlobalColor.black)
    palette.setColor(palette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    palette.setColor(palette.ColorRole.Text, Qt.GlobalColor.white)
    palette.setColor(palette.ColorRole.Button, Qt.GlobalColor.darkGray)
    palette.setColor(palette.ColorRole.ButtonText, Qt.GlobalColor.white)
    palette.setColor(palette.ColorRole.BrightText, Qt.GlobalColor.red)
    palette.setColor(palette.ColorRole.Link, Qt.GlobalColor.cyan)
    palette.setColor(palette.ColorRole.Highlight, Qt.GlobalColor.darkCyan)
    palette.setColor(palette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(palette)
    
    return app 