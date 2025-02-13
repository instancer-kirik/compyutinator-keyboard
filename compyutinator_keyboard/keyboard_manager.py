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
import logging

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
from PyQt6.QtGui import QDrag, QPixmap, QPainter, QTextCursor, QIcon, QColor
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
    QTabWidget,
    QSystemTrayIcon
)

# Fix imports to work both as module and directly
try:
    from .keyboard_layout import KeyboardLayout
    from .midi_keyboard import MIDIKeyboard
    from compyutinator_common import setup_qt_app
    from compyutinator_transcriber.transcriber import TranscriberWindow
    from .morse_code import MorseChart, MorseRecognizer
except ImportError:
    from .keyboard_layout import KeyboardLayout
    from .midi_keyboard import MIDIKeyboard
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from compyutinator_common import setup_qt_app
    from compyutinator_transcriber.transcriber import TranscriberWindow
    from .morse_code import MorseChart, MorseRecognizer

# Add this constant near the top of the file
KEYBOARD_ICON_SVG = """
<svg width="64" height="64" viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">
    <rect x="8" y="16" width="48" height="32" rx="4" fill="none" stroke="currentColor" stroke-width="4"/>
    <rect x="16" y="24" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="24" y="24" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="32" y="24" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="40" y="24" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="16" y="32" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="24" y="32" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="32" y="32" width="6" height="6" rx="1" fill="currentColor"/>
    <rect x="40" y="32" width="6" height="6" rx="1" fill="currentColor"/>
</svg>
"""

logger = logging.getLogger(__name__)

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

        # Install event filter to catch key events globally
        app = QApplication.instance()
        app.installEventFilter(self)

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
        
        # Transcriber tab
        transcriber_tab = QWidget()
        transcriber_layout = QVBoxLayout(transcriber_tab)
        
        # Create transcriber widget with direct model path
        model_path = os.path.join(os.path.dirname(__file__), '..', 'models', 'vosk-model-small-en-us-0.15')
        if not os.path.exists(model_path):
            logger.warning(f"Could not find Vosk model at {model_path}")
            model_path = None
        
        self.transcriber = TranscriberWindow(model_path=model_path)
        # Remove window decorations since it's embedded
        self.transcriber.setWindowFlags(Qt.WindowType.Widget)
        transcriber_layout.addWidget(self.transcriber)
        
        tab_widget.addTab(transcriber_tab, "Transcriber")
        
        # Morse Code tab
        morse_tab = QWidget()
        morse_layout = QVBoxLayout(morse_tab)
        
        # Add Morse chart
        morse_chart = MorseChart()
        morse_layout.addWidget(morse_chart)
        
        # Add Morse recognizer
        self.morse_recognizer = MorseRecognizer()
        morse_layout.addWidget(self.morse_recognizer)
        
        # Add instructions
        instructions = QLabel(
            "Use Space or Enter to input Morse code:\n"
            "• Short press (< 0.15s) for dot\n"
            "• Long press (> 0.15s) for dash\n"
            "• Wait 0.5s for new character\n"
            "• Wait 1.0s for word space"
        )
        morse_layout.addWidget(instructions)
        
        tab_widget.addTab(morse_tab, "Morse Code")
        
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
    
    def eventFilter(self, obj, event):
        """Handle events even when window doesn't have focus."""
        if event.type() in (event.Type.KeyPress, event.Type.KeyRelease):
            # Handle MIDI keyboard events
            if self.midi_keyboard:
                if event.type() == event.Type.KeyPress and not event.isAutoRepeat():
                    if self.midi_keyboard.key_press(event.text() or event.key()):
                        return True
                elif event.type() == event.Type.KeyRelease and not event.isAutoRepeat():
                    if self.midi_keyboard.key_release(event.text() or event.key()):
                        return True
            
            # Handle Morse code input
            if hasattr(self, 'morse_recognizer'):
                if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
                    if event.type() == event.Type.KeyPress and not event.isAutoRepeat():
                        self.morse_recognizer.key_down()
                        return True
                    elif event.type() == event.Type.KeyRelease and not event.isAutoRepeat():
                        self.morse_recognizer.key_up()
                        return True
                        
        return super().eventFilter(obj, event)
    
    def closeEvent(self, event):
        """Handle application close."""
        # Stop transcription if running
        if hasattr(self, 'transcriber'):
            try:
                self.transcriber.stop_transcription()
                self.transcriber.close()
            except:
                pass
        
        # Handle other cleanup
        if self.midi_keyboard:
            self.midi_keyboard.cleanup()
        
        event.accept()

    def create_tray_icon(self):
        """Create system tray icon and menu."""
        self.tray_icon = QSystemTrayIcon(self)
        
        # Create icon from SVG
        icon = QIcon()
        for state in [QIcon.Mode.Normal, QIcon.Mode.Disabled, QIcon.Mode.Active, QIcon.Mode.Selected]:
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if state == QIcon.Mode.Disabled:
                painter.setPen(QColor(128, 128, 128))  # Gray for disabled
            else:
                painter.setPen(QColor(255, 255, 255))  # White for other states
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, KEYBOARD_ICON_SVG)
            painter.end()
            icon.addPixmap(pixmap, state)
        
        self.tray_icon.setIcon(icon)
        
        # Rest of the create_tray_icon method remains the same...

class SetupWizard(QWizard):
    """Setup wizard for first-time configuration."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Keyboard Manager Setup")
        
        # Add pages
        self.addPage(self.create_intro_page())
        self.addPage(self.create_udev_page())
        self.addPage(self.create_permissions_page())
        self.addPage(self.create_modules_page())
        self.addPage(self.create_finish_page())
        
        # Add progress bars
        self.udev_progress = QProgressBar()
        self.udev_progress.hide()
        self.perm_progress = QProgressBar()
        self.perm_progress.hide()
        
        # Set minimum size
        self.setMinimumSize(600, 400)
        
        # Allow skipping if already configured
        self.setOption(QWizard.WizardOption.IndependentPages, True)
    
    def create_intro_page(self):
        """Create introduction page."""
        page = QWizardPage()
        page.setTitle("Welcome to Keyboard Manager Setup")
        layout = QVBoxLayout()
        
        label = QLabel(
            "This wizard will help you set up your system for KMonad:\n\n"
            "• udev rules for keyboard access\n"
            "• User group permissions\n"
            "• uinput module loading\n\n"
            "You may need to enter your password for system changes."
        )
        label.setWordWrap(True)
        layout.addWidget(label)
        
        page.setLayout(layout)
        return page
    
    def create_udev_page(self):
        """Create udev rules setup page."""
        page = QWizardPage()
        page.setTitle("udev Rules Setup")
        layout = QVBoxLayout()
        
        # Add skip checkbox
        self.skip_udev = QCheckBox("Skip (if already configured)")
        layout.addWidget(self.skip_udev)
        
        # Status label
        self.udev_status = QLabel("Checking current configuration...")
        layout.addWidget(self.udev_status)
        
        # Setup button
        self.udev_button = QPushButton("Setup udev Rules")
        self.udev_button.clicked.connect(self.setup_udev_rules)
        layout.addWidget(self.udev_button)
        
        # Progress bar
        layout.addWidget(self.udev_progress)
        
        # Check current config
        if os.path.exists("/etc/udev/rules.d/99-kmonad-keyboards.rules"):
            self.udev_status.setText("✓ udev rules already configured")
            self.skip_udev.setChecked(True)
            self.udev_button.setEnabled(False)
        else:
            self.udev_status.setText("udev rules need to be configured")
        
        page.setLayout(layout)
        return page
    
    def create_permissions_page(self):
        """Create permissions setup page."""
        page = QWizardPage()
        page.setTitle("User Permissions Setup")
        layout = QVBoxLayout()
        
        # Add skip checkbox
        self.skip_perms = QCheckBox("Skip (if already configured)")
        layout.addWidget(self.skip_perms)
        
        # Status label
        self.perm_status = QLabel("Checking current configuration...")
        layout.addWidget(self.perm_status)
        
        # Setup button
        self.perm_button = QPushButton("Setup Permissions")
        self.perm_button.clicked.connect(self.setup_permissions)
        layout.addWidget(self.perm_button)
        
        # Progress bar
        layout.addWidget(self.perm_progress)
        
        # Check current config
        username = os.getenv('USER')
        try:
            groups = subprocess.check_output(['groups', username]).decode()
            if 'input' in groups:
                self.perm_status.setText("✓ User already in input group")
                self.skip_perms.setChecked(True)
                self.perm_button.setEnabled(False)
            else:
                self.perm_status.setText("User needs to be added to input group")
        except:
            self.perm_status.setText("Could not check group membership")
        
        page.setLayout(layout)
        return page
    
    def create_modules_page(self):
        """Create page for module loading."""
        page = QWizardPage()
        page.setTitle("Kernel Module Setup")
        layout = QVBoxLayout()
        
        # Status label
        self.module_status = QLabel("Checking modules...")
        layout.addWidget(self.module_status)
        
        # Setup button
        self.module_button = QPushButton("Load uinput Module")
        self.module_button.clicked.connect(self.setup_modules)
        layout.addWidget(self.module_button)
        
        # Check current status
        try:
            with open('/proc/modules') as f:
                modules = f.read()
                if 'uinput' in modules:
                    self.module_status.setText("✓ uinput module already loaded")
                    self.module_button.setEnabled(False)
                else:
                    self.module_status.setText("uinput module needs to be loaded")
        except Exception as e:
            self.module_status.setText(f"Error checking modules: {e}")
        
        page.setLayout(layout)
        return page

    def create_finish_page(self):
        """Create final setup page."""
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
        
        # Add status summary
        status = QLabel()
        status_text = "Setup Status:\n"
        
        # Check udev rules
        if os.path.exists('/etc/udev/rules.d/99-kmonad-keyboards.rules'):
            status_text += "✓ udev rules configured\n"
        else:
            status_text += "✗ udev rules not found\n"
        
        # Check user groups
        try:
            groups = subprocess.check_output(['groups']).decode()
            if 'input' in groups:
                status_text += "✓ User in input group\n"
            else:
                status_text += "✗ User not in input group\n"
        except:
            status_text += "? Could not check groups\n"
        
        # Check uinput module
        try:
            with open('/proc/modules') as f:
                if 'uinput' in f.read():
                    status_text += "✓ uinput module loaded\n"
                else:
                    status_text += "✗ uinput module not loaded\n"
        except:
            status_text += "? Could not check modules\n"
        
        status.setText(status_text)
        layout.addWidget(status)
        
        page.setLayout(layout)
        return page

    def setup_modules(self):
        """Set up required kernel modules."""
        try:
            # Load uinput module
            subprocess.run(['pkexec', 'sh', '-c', '''
                modprobe uinput
                echo "uinput" > /etc/modules-load.d/uinput.conf
                echo "# KMonad uinput module" > /etc/modules-load.d/kmonad.conf
                echo "uinput" >> /etc/modules-load.d/kmonad.conf
            '''], check=True)
            
            # Verify module is loaded
            with open('/proc/modules') as f:
                if 'uinput' in f.read():
                    self.module_status.setText("✓ uinput module loaded successfully")
                    self.module_button.setEnabled(False)
                    return True
                else:
                    self.module_status.setText("Error: Module not loaded after setup")
                    return False
                    
        except Exception as e:
            self.module_status.setText(f"Error loading module: {e}")
            return False

    def setup_udev_rules(self):
        """Set up udev rules for keyboard and uinput access."""
        try:
            # Create more comprehensive udev rules
            rules_content = """# KMonad keyboard access
KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
KERNEL=="event*", NAME="input/%k", MODE="0660", GROUP="input"
# Tag all keyboard devices
SUBSYSTEM=="input", KERNEL=="event*", ENV{ID_INPUT_KEYBOARD}=="1", TAG+="kmonad-keyboards"
"""
            # Use pkexec to write rules with elevated privileges
            with tempfile.NamedTemporaryFile(mode='w', suffix='.rules', delete=False) as temp:
                temp.write(rules_content)
                rules_path = temp.name
            
            subprocess.run([
                'pkexec', 'sh', '-c',
                f'''
                cp {rules_path} /etc/udev/rules.d/99-kmonad-keyboards.rules
                udevadm control --reload-rules
                udevadm trigger
                '''
            ], check=True)
            
            # Verify rules were created
            if os.path.exists('/etc/udev/rules.d/99-kmonad-keyboards.rules'):
                self.udev_status.setText("✓ udev rules configured successfully")
                return True
            else:
                self.udev_status.setText("Error: Rules file not created")
                return False
                
        except Exception as e:
            self.udev_status.setText(f"Error configuring udev rules: {e}")
            return False

    def setup_permissions(self):
        """Set up user permissions and groups."""
        try:
            username = os.getenv('USER')
            subprocess.run([
                'pkexec', 'sh', '-c',
                f'''
                # Add user to input group
                usermod -aG input {username}
                
                # Ensure /dev/uinput has correct permissions
                chgrp input /dev/uinput
                chmod g+rw /dev/uinput
                '''
            ], check=True)
            
            # Verify group membership
            groups = subprocess.check_output(['groups', username]).decode()
            if 'input' in groups:
                self.perm_status.setText("✓ Permissions configured successfully")
                return True
            else:
                self.perm_status.setText("Error: User not added to input group")
                return False
                
        except Exception as e:
            self.perm_status.setText(f"Error configuring permissions: {e}")
            return False

    def validateCurrentPage(self):
        """Validate each page before proceeding."""
        current_page = self.currentPage()
        
        if "udev" in current_page.title().lower():
            if not self.skip_udev.isChecked():
                return self.setup_udev_rules()
                
        elif "permission" in current_page.title().lower():
            if not self.skip_perms.isChecked():
                return self.setup_permissions()
                
        elif "module" in current_page.title().lower():
            with open('/proc/modules') as f:
                if 'uinput' not in f.read():
                    return self.setup_modules()
                    
        return True

def main():
    """Run the keyboard manager application."""
    app = setup_qt_app()
    manager = KeyboardManager()
    manager.show()
    return app.exec()

if __name__ == "__main__":
    sys.exit(main())