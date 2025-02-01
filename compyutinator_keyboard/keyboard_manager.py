"""
Keyboard Manager - A GUI tool for managing keyboard layouts and KMonad configurations.

This module provides a Qt-based interface for:
- Managing KMonad configurations
- Configuring keyboard layouts
- Setting up system permissions
- Managing keyboard device selection
- MIDI keyboard emulation
"""

import os
import re
import subprocess
import sys
import tempfile
from typing import Optional, Dict, List

# Qt imports
from PyQt6.QtCore import (
    QProcess, 
    QSettings, 
    QPropertyAnimation, 
    QEasingCurve, 
    QTimer, 
    Qt, 
    QPoint, 
    QMimeData
)
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QTextCursor
from PyQt6.QtNetwork import QLocalSocket, QLocalServer
from PyQt6.QtWidgets import (
    QApplication, 
    QMainWindow, 
    QVBoxLayout, 
    QHBoxLayout,
    QWidget, 
    QPushButton, 
    QComboBox, 
    QTextEdit, 
    QLabel,
    QFileDialog, 
    QMessageBox, 
    QGroupBox, 
    QCheckBox,
    QWizard, 
    QWizardPage, 
    QProgressBar, 
    QSizePolicy,
    QTabWidget
)

# Fix imports to work both as module and directly
try:
    from .keyboard_layout import KeyboardLayout
    from .midi_keyboard import MIDIKeyboard
    from compyutinator_common import setup_qt_app
except ImportError:
    from keyboard_layout import KeyboardLayout
    from midi_keyboard import MIDIKeyboard
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from compyutinator_common import setup_qt_app

class KeyboardManager(QMainWindow):
    def __init__(self):
        super().__init__()
        
        # Initialize settings
        self.settings = QSettings("Compyutinator", "KeyboardManager")
        
        # Add rerun setup option
        self.setup_action = QPushButton("Run Setup")
        self.setup_action.clicked.connect(self.rerun_setup)
        
        # Initialize components
        self.midi_keyboard = None
        
        # Initialize UI
        self.init_ui()
        
        # Check if setup is needed
        if not self.check_setup():
            self.run_setup()

    def check_setup(self) -> bool:
        """Check if setup is needed and run setup wizard if necessary."""
        if self.settings.value("setup_complete", False, type=bool):
            return True
        
        wizard = SetupWizard(self)
        if wizard.exec() == QWizard.DialogCode.Accepted:
            self.settings.setValue("setup_complete", True)
            return True
        return False

    def rerun_setup(self):
        """Rerun the setup wizard."""
        wizard = SetupWizard(self)
        if wizard.exec() == QWizard.DialogCode.Accepted:
            self.settings.setValue("setup_complete", True)
            QMessageBox.information(
                self,
                "Setup Complete",
                "Setup completed successfully. Please restart the application."
            )
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("Keyboard Manager")
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Create tab widget
        tab_widget = QTabWidget()
        main_layout.addWidget(tab_widget)
        
        # Layout tab
        layout_tab = QWidget()
        layout_tab_layout = QVBoxLayout(layout_tab)
        self.keyboard_layout = KeyboardLayout(self)
        layout_tab_layout.addWidget(self.keyboard_layout)
        tab_widget.addTab(layout_tab, "Keyboard Layout")
        
        # MIDI tab
        midi_tab = QWidget()
        midi_tab_layout = QVBoxLayout(midi_tab)
        
        # MIDI controls
        midi_controls = QGroupBox("MIDI Controls")
        midi_controls_layout = QVBoxLayout()
        
        # MIDI enable/disable
        midi_enable_layout = QHBoxLayout()
        self.midi_enable = QCheckBox("Enable MIDI Mode")
        self.midi_enable.toggled.connect(self.toggle_midi)
        midi_enable_layout.addWidget(self.midi_enable)
        midi_controls_layout.addLayout(midi_enable_layout)
        
        # MIDI status
        self.midi_status = QLabel("MIDI: Disabled")
        midi_controls_layout.addWidget(self.midi_status)
        
        # MIDI instructions
        midi_instructions = QLabel(
            "Use keyboard keys A-K for notes (C4-C5)\n"
            "F1/F2: Decrease/Increase Octave\n"
            "F3/F4: Decrease/Increase Velocity\n"
            "Left Control: Sustain"
        )
        midi_controls_layout.addWidget(midi_instructions)
        
        midi_controls.setLayout(midi_controls_layout)
        midi_tab_layout.addWidget(midi_controls)
        
        # Piano keyboard visualization
        self.piano_group = QGroupBox("Piano Keyboard")
        piano_layout = QVBoxLayout()
        self.piano_widget = None  # Will be created when MIDI is enabled
        self.piano_group.setLayout(piano_layout)
        midi_tab_layout.addWidget(self.piano_group)
        
        # Add stretcher
        midi_tab_layout.addStretch()
        
        tab_widget.addTab(midi_tab, "MIDI Keyboard")
        
        # Create controls
        controls_group = QGroupBox("Controls")
        controls_layout = QHBoxLayout()
        
        # Add buttons
        load_button = QPushButton("Load Config")
        save_button = QPushButton("Save Config")
        apply_button = QPushButton("Apply")
        
        controls_layout.addWidget(load_button)
        controls_layout.addWidget(save_button)
        controls_layout.addWidget(apply_button)
        
        # Add setup button to controls
        controls_layout.addWidget(self.setup_action)
        
        controls_group.setLayout(controls_layout)
        main_layout.addWidget(controls_group)
        
        # Set window size
        self.setMinimumSize(800, 600)
        
        # Restore MIDI state
        if self.settings.value("midi_enabled", False, type=bool):
            self.midi_enable.setChecked(True)
    
    def load_default_config(self):
        """Load default KMonad config or restore saved config."""
        saved_config = self.settings.value("last_config")
        if saved_config:
            self.keyboard_layout.config_edit.setText(saved_config)
        else:
            # Default KMonad config
            default_config = """
(defcfg
  input  (device-file "/dev/input/by-id/DEVICE_ID")
  output (uinput-sink "My KMonad output")
  fallthrough true
  allow-cmd true
)

(defsrc
  esc  f1   f2   f3   f4   f5   f6   f7   f8   f9   f10  f11  f12
  grv  1    2    3    4    5    6    7    8    9    0    -    =    bspc
  tab  q    w    e    r    t    y    u    i    o    p    [    ]    \\
  caps a    s    d    f    g    h    j    k    l    ;    '    ret
  lsft z    x    c    v    b    n    m    ,    .    /    rsft
  lctl lmet lalt           spc            ralt rmet menu rctl
)

(defalias
  cap (tap-hold 200 esc lctl)
)

(deflayer colemak
  esc  f1   f2   f3   f4   f5   f6   f7   f8   f9   f10  f11  f12
  grv  1    2    3    4    5    6    7    8    9    0    -    =    bspc
  tab  q    w    f    p    g    j    l    u    y    ;    [    ]    \\
  @cap a    r    s    t    d    h    n    e    i    o    '    ret
  lsft z    x    c    v    b    k    m    ,    .    /    rsft
  lctl lmet lalt           spc            ralt rmet menu rctl
)
"""
            # Try to find a keyboard device
            try:
                result = subprocess.run(['ls', '-l', '/dev/input/by-id'], capture_output=True, text=True)
                for line in result.stdout.splitlines():
                    if 'kbd' in line.lower():
                        device = line.split(' -> ')[0].strip()
                        default_config = default_config.replace("DEVICE_ID", device)
                        break
            except:
                pass
            
            self.keyboard_layout.config_edit.setText(default_config)
            self.keyboard_layout.parse_config(default_config)

    def toggle_midi(self, enabled: bool):
        """Toggle MIDI keyboard functionality."""
        if enabled:
            if not self.midi_keyboard:
                self.midi_keyboard = MIDIKeyboard()
                
                # Get the current KMonad config
                config_text = self.keyboard_layout.config_edit.toPlainText()
                
                # Parse the Colemak layer to get key mappings
                colemak_match = re.search(r'\(deflayer\s+colemak\s+([\s\S]+?)\)', config_text)
                if colemak_match:
                    colemak_layout = colemak_match.group(1).strip().split()
                    
                    # Extract the home row keys (where our MIDI keys will be)
                    home_row_start = 26  # Index where 'a' starts in the layout
                    home_row = colemak_layout[home_row_start:home_row_start+10]  # Get 'arstdhneio'
                    top_row_start = 14   # Index where 'q' starts in the layout
                    top_row = colemak_layout[top_row_start:top_row_start+10]     # Get 'qwfpgjluy'
                    
                    # Map keys to notes in piano order
                    key_map = {}
                    
                    # White keys: C D E F G A B C
                    white_keys = []
                    for key in home_row:
                        if key not in ['@cap', ';', "'", 'ret']:  # Skip modifiers and punctuation
                            white_keys.append(key)
                    white_keys.extend([key for key in top_row if key not in ['tab', '[', ']', '\\']])
                    white_notes = [60, 62, 64, 65, 67, 69, 71, 72]  # C4 to C5
                    
                    # Black keys: C# D# F# G# A#
                    black_keys = []
                    for key in top_row:
                        if key not in ['tab', '[', ']', '\\']:  # Skip modifiers
                            black_keys.append(key)
                    black_notes = [61, 63, 66, 68, 70]  # C#4 to A#4
                    
                    # Map white keys first
                    for key, note in zip(white_keys[:8], white_notes):  # Limit to 8 white keys
                        key_map[key.lower()] = note
                    
                    # Then map black keys
                    for key, note in zip(black_keys[:5], black_notes):  # Limit to 5 black keys
                        key_map[key.lower()] = note
                    
                    self.midi_keyboard.update_key_map(key_map)
                
                self.midi_keyboard.midi_error.connect(self.handle_midi_error)
                self.midi_keyboard.note_on.connect(self.handle_note_on)
                self.midi_keyboard.note_off.connect(self.handle_note_off)
                # Add piano widget to the UI
                piano_layout = self.piano_group.layout()
                piano_layout.addWidget(self.midi_keyboard.piano_widget)
            self.midi_status.setText("MIDI: Enabled")
        else:
            if self.midi_keyboard:
                # Remove piano widget from UI
                piano_layout = self.piano_group.layout()
                if self.midi_keyboard.piano_widget:
                    piano_layout.removeWidget(self.midi_keyboard.piano_widget)
                    self.midi_keyboard.piano_widget.setParent(None)
                self.midi_keyboard.cleanup()
                self.midi_keyboard = None
            self.midi_status.setText("MIDI: Disabled")
        
        self.settings.setValue("midi_enabled", enabled)
    
    def handle_midi_error(self, error: str):
        """Handle MIDI errors."""
        QMessageBox.warning(self, "MIDI Error", error)
        self.midi_enable.setChecked(False)
    
    def handle_note_on(self, note: int, velocity: int):
        """Handle MIDI note on event."""
        self.midi_status.setText(f"MIDI: Note {note} On (velocity: {velocity})")
    
    def handle_note_off(self, note: int):
        """Handle MIDI note off event."""
        self.midi_status.setText(f"MIDI: Note {note} Off")
    
    def keyPressEvent(self, event):
        """Handle key press events."""
        if self.midi_keyboard and not event.isAutoRepeat():
            if self.midi_keyboard.key_press(event.text() or event.key()):
                event.accept()
                return
        super().keyPressEvent(event)
    
    def keyReleaseEvent(self, event):
        """Handle key release events."""
        if self.midi_keyboard and not event.isAutoRepeat():
            if self.midi_keyboard.key_release(event.text() or event.key()):
                event.accept()
                return
        super().keyReleaseEvent(event)
    
    def closeEvent(self, event):
        """Handle application close."""
        if self.midi_keyboard:
            self.midi_keyboard.cleanup()
        super().closeEvent(event)

class SetupWizard(QWizard):
    """Setup wizard for first-time configuration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Manager Setup")
        
        # Add pages
        self.addPage(self.create_intro_page())
        self.addPage(self.create_udev_page())
        self.addPage(self.create_permissions_page())
        self.addPage(self.create_finish_page())
        
        # Set minimum size
        self.setMinimumSize(600, 400)
    
    def create_intro_page(self):
        page = QWizardPage()
        page.setTitle("Welcome to Keyboard Manager")
        layout = QVBoxLayout()
        
        label = QLabel(
            "This wizard will help you set up the required permissions and configurations "
            "for KMonad and MIDI keyboard functionality.\n\n"
            "The following will be configured:\n"
            "• udev rules for keyboard access\n"
            "• User group permissions\n"
            "• uinput module loading"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        
        page.setLayout(layout)
        return page
    
    def create_udev_page(self):
        page = QWizardPage()
        page.setTitle("udev Rules Setup")
        layout = QVBoxLayout()
        
        # Status label
        self.udev_status = QLabel("Status: Not configured")
        layout.addWidget(self.udev_status)
        
        # Setup button
        self.udev_button = QPushButton("Setup udev Rules")
        self.udev_button.clicked.connect(self.setup_udev_rules)
        layout.addWidget(self.udev_button)
        
        # Progress
        self.udev_progress = QProgressBar()
        self.udev_progress.hide()
        layout.addWidget(self.udev_progress)
        
        page.setLayout(layout)
        return page
    
    def create_permissions_page(self):
        page = QWizardPage()
        page.setTitle("User Permissions Setup")
        layout = QVBoxLayout()
        
        # Status label
        self.perm_status = QLabel("Status: Not configured")
        layout.addWidget(self.perm_status)
        
        # Setup button
        self.perm_button = QPushButton("Setup Permissions")
        self.perm_button.clicked.connect(self.setup_permissions)
        layout.addWidget(self.perm_button)
        
        # Progress
        self.perm_progress = QProgressBar()
        self.perm_progress.hide()
        layout.addWidget(self.perm_progress)
        
        page.setLayout(layout)
        return page
    
    def create_finish_page(self):
        page = QWizardPage()
        page.setTitle("Setup Complete")
        layout = QVBoxLayout()
        
        label = QLabel(
            "Setup is complete! For the changes to take effect, you need to:\n\n"
            "1. Log out and log back in\n"
            "2. Restart the Keyboard Manager application\n\n"
            "Would you like to exit now?"
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        
        page.setLayout(layout)
        return page
    
    def setup_udev_rules(self):
        """Set up udev rules for keyboard and uinput access."""
        self.udev_button.setEnabled(False)
        self.udev_progress.show()
        self.udev_progress.setRange(0, 0)  # Indeterminate progress
        
        try:
            # Create udev rules
            rules_content = """
# KMonad keyboard access
KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
KERNEL=="event*", NAME="input/%k", MODE="0660", GROUP="input"
"""
            # Use pkexec to write rules with elevated privileges
            with tempfile.NamedTemporaryFile(mode='w', suffix='.rules', delete=False) as temp:
                temp.write(rules_content)
                rules_path = temp.name
            
            # Copy rules file to /etc/udev/rules.d/
            subprocess.run([
                'pkexec', 'sh', '-c',
                f'cp {rules_path} /etc/udev/rules.d/99-kmonad-keyboards.rules && '
                'udevadm control --reload-rules && '
                'udevadm trigger'
            ], check=True)
            
            os.unlink(rules_path)
            
            self.udev_status.setText("Status: ✓ udev rules configured successfully")
            self.udev_progress.hide()
            return True
            
        except Exception as e:
            self.udev_status.setText(f"Status: ✗ Error configuring udev rules: {str(e)}")
            self.udev_progress.hide()
            self.udev_button.setEnabled(True)
            return False
    
    def setup_permissions(self):
        """Set up user permissions and groups."""
        self.perm_button.setEnabled(False)
        self.perm_progress.show()
        self.perm_progress.setRange(0, 0)
        
        try:
            # Add user to required groups
            username = os.getenv('USER')
            subprocess.run([
                'pkexec', 'sh', '-c',
                f'usermod -aG input {username} && '
                'modprobe uinput && '
                'echo "uinput" > /etc/modules-load.d/uinput.conf'
            ], check=True)
            
            self.perm_status.setText("Status: ✓ Permissions configured successfully")
            self.perm_progress.hide()
            return True
            
        except Exception as e:
            self.perm_status.setText(f"Status: ✗ Error configuring permissions: {str(e)}")
            self.perm_progress.hide()
            self.perm_button.setEnabled(True)
            return False

def main():
    """Run the keyboard manager application."""
    app = setup_qt_app()
    manager = KeyboardManager()
    manager.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())