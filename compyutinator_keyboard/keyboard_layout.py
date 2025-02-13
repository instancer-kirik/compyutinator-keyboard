"""
Keyboard Layout Widget for visualizing and editing keyboard configurations.
"""

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QVBoxLayout, QComboBox,
    QPushButton, QTextEdit, QCheckBox, QFileDialog, QSystemTrayIcon, QMenu, QMessageBox, QSpinBox
)
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, QMimeData, QTimer
from PyQt6.QtGui import QPainter, QPen, QColor, QPixmap, QDrag, QIcon, QTextCursor
import os
import re
import subprocess
import tempfile
from PyQt6.QtCore import QProcess
from PyQt6.QtWidgets import QApplication

class KeyboardLayout(QWidget):
    """Widget for displaying and editing keyboard layouts."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # Create main layout (store as instance variable with different name)
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setSpacing(4)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create controls layout
        controls_layout = QHBoxLayout()
        self.main_layout.addLayout(controls_layout)
        
        # Add staggered layout toggle
        self.offset_toggle = QCheckBox("Staggered Layout")
        self.offset_toggle.setChecked(True)  # Default to staggered
        controls_layout.addWidget(self.offset_toggle)
        
        # Add key size controls
        key_size_layout = QHBoxLayout()
        key_size_layout.addWidget(QLabel("Key Size:"))
        self.key_size_spin = QSpinBox()
        self.key_size_spin.setRange(30, 100)
        self.key_size_spin.setValue(50)
        self.key_size_spin.valueChanged.connect(self.update_key_sizes)
        key_size_layout.addWidget(self.key_size_spin)
        controls_layout.addLayout(key_size_layout)
        
        # Add config editor
        self.config_edit = QTextEdit()
        self.config_edit.setPlaceholderText("Paste your KMonad config here...")
        self.main_layout.addWidget(self.config_edit)
        
        # Add output box first so it's available for messages
        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)
        self.output_box.setMinimumHeight(100)
        self.output_box.setStyleSheet("""
            QTextEdit {
                background-color: #2a2a2a;
                color: #ff6b6b;
                border: 1px solid #ff6b6b;
                border-radius: 4px;
                padding: 8px;
                font-family: monospace;
            }
        """)
        
        # Add device selection
        device_layout = QHBoxLayout()
        device_label = QLabel("Keyboard Device:")
        self.device_combo = QComboBox()
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh_devices)
        
        device_layout.addWidget(device_label)
        device_layout.addWidget(self.device_combo)
        device_layout.addWidget(refresh_button)
        self.main_layout.addLayout(device_layout)
        
        # Add control buttons
        button_layout = QHBoxLayout()
        
        self.start_button = QPushButton("Start KMonad")
        self.start_button.clicked.connect(self.toggle_kmonad)
        
        debug_button = QPushButton("Debug in Terminal")
        debug_button.clicked.connect(self.debug_in_terminal)
        
        kill_button = QPushButton("Kill All KMonad")
        kill_button.clicked.connect(self.kill_all_kmonad)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(debug_button)
        button_layout.addWidget(kill_button)
        
        # Add minimize checkbox
        self.minimize_to_tray = QCheckBox("Minimize to Tray")
        self.minimize_to_tray.setChecked(True)
        button_layout.addWidget(self.minimize_to_tray)
        
        self.main_layout.addLayout(button_layout)
        
        # Add output box at bottom
        self.main_layout.addWidget(self.output_box)
        
        # Initialize after UI is ready
        self.kmonad_process = None
        self.refresh_devices()
        self.load_default_config()
        
        # Create warning label first
        self.warning_label = QLabel(self)
        self.warning_label.setStyleSheet("""
            QLabel {
                color: #ff6b6b;
                background-color: #2a2a2a;
                border: 1px solid #ff6b6b;
                border-radius: 4px;
                padding: 8px;
                margin: 4px;
            }
        """)
        self.warning_label.hide()
        # Add warning label to top of layout
        self.main_layout.insertWidget(0, self.warning_label)
        
        # Initialize other attributes
        self.dragging = False
        self.drag_source = None
        self.drag_source_row = None
        self.active_row = None
        self.row_states = {}
        self.setAcceptDrops(True)
        
        # Define default layouts
        self.default_layout = {
            "Function": ["esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"],
            "Number": ["grv", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "mins", "eql", "bspc"],
            "QWERTY": ["tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "lbrc", "rbrc", "bsls"],
            "Home": ["caps", "a", "s", "d", "f", "g", "h", "j", "k", "l", "scln", "quot", "ret"],
            "Shift": ["lsft", "z", "x", "c", "v", "b", "n", "m", "comm", "dot", "slsh", "rsft"],
            "Control": ["lctl", "lmet", "lalt", "spc", "ralt", "rmet", "menu", "rctl"]
        }
        
        # Add layout selector
        layout_selector = QHBoxLayout()
        layout_selector.addWidget(QLabel("Base Layout:"))
        self.layout_combo = QComboBox()
        self.layout_combo.addItems(["QWERTY", "Colemak", "Dvorak"])
        self.layout_combo.currentTextChanged.connect(self.change_layout)
        layout_selector.addWidget(self.layout_combo)
        self.main_layout.insertLayout(1, layout_selector)
        
        # Now create keyboard layout
        self.create_keyboard_layout()
        
        # Add special key functions
        self.special_keys = {
            "caps": "(tap-hold 200 esc lctl)",  # Caps is Esc when tapped, Ctrl when held
            "lsft": "(tap-hold-next 200 ( lsft)",  # Shift with tap-hold for parentheses
            "rsft": "(tap-hold-next 200 ) rsft)",
        }

        # Check for existing KMonad process on startup
        self.check_existing_kmonad()

        # Add system tray
        self.create_tray_icon()

        # Add predefined layouts
        self.layouts = {
            "QWERTY": {
                "Function": ["esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"],
                "Number": ["grv", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "mins", "eql", "bspc"],
                "QWERTY": ["tab", "q", "w", "e", "r", "t", "y", "u", "i", "o", "p", "lbrc", "rbrc", "bsls"],
                "Home": ["caps", "a", "s", "d", "f", "g", "h", "j", "k", "l", "scln", "quot", "ret"],
                "Shift": ["lsft", "z", "x", "c", "v", "b", "n", "m", "comm", "dot", "slsh", "rsft"],
                "Control": ["lctl", "lmet", "lalt", "spc", "ralt", "rmet", "menu", "rctl"]
            },
            "Colemak": {
                "Function": ["esc", "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12"],
                "Number": ["grv", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "mins", "eql", "bspc"],
                "QWERTY": ["tab", "q", "w", "f", "p", "g", "j", "l", "u", "y", "scln", "lbrc", "rbrc", "bsls"],
                "Home": ["caps", "a", "r", "s", "t", "d", "h", "n", "e", "i", "o", "quot", "ret"],
                "Shift": ["lsft", "z", "x", "c", "v", "b", "k", "m", "comm", "dot", "slsh", "rsft"],
                "Control": ["lctl", "lmet", "lalt", "spc", "ralt", "rmet", "menu", "rctl"]
            }
        }

        # Add default KMonad configs
        self.kmonad_configs = {
            "QWERTY-Colemak": """
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
        }

        # Add row offsets for staggered layout
        self.row_offsets = {
            "Function": 0,
            "Number": 0,
            "QWERTY": 25,  # Quarter key offset
            "Home": 35,    # Third key offset
            "Shift": 45,   # Half key offset
            "Control": 15  # Small offset
        }

    def show_warning(self, message, timeout=5000):
        """Show warning message in output box."""
        from datetime import datetime
        current = self.output_box.toPlainText()
        timestamp = datetime.now().strftime("%H:%M:%S")
        new_message = f"[{timestamp}] {message}"
        
        if current:
            new_message = current + "\n" + new_message
        
        self.output_box.setText(new_message)
        self.output_box.moveCursor(QTextCursor.MoveOperation.End)

    def toggle_warning_size(self):
        """Toggle between normal and expanded warning size."""
        if self.warning_expanded:
            self.warning_text.setMinimumHeight(150)
            self.warning_text.setMaximumHeight(150)
            self.expand_button.setText("▼")
        else:
            self.warning_text.setMinimumHeight(400)
            self.warning_text.setMaximumHeight(800)
            self.expand_button.setText("▲")
        self.warning_expanded = not self.warning_expanded

    def debug_in_terminal(self):
        """Run KMonad in terminal with debug output."""
        try:
            # Save current config to temp file
            config_file = os.path.join(tempfile.gettempdir(), "kmonad_debug.kbd")
            with open(config_file, 'w') as f:
                f.write(self.config_edit.toPlainText())
            
            # Create debug script with more verbose output
            debug_script = f"""#!/bin/bash
set -x  # Show commands being executed

echo "=== Current User and Groups ==="
id
echo

echo "=== Device Permissions ==="
ls -l /dev/input/event*
echo

echo "=== Input Device Details ==="
cat /proc/bus/input/devices
echo

echo "=== Config File Contents ==="
cat {config_file}
echo

echo "=== Testing KMonad ==="
kmonad -d {config_file} 2>&1  # Capture both stdout and stderr
echo

echo "Press Enter to close..."
read
"""
            script_path = os.path.join(tempfile.gettempdir(), "kmonad_debug.sh")
            with open(script_path, 'w') as f:
                f.write(debug_script)
            os.chmod(script_path, 0o755)

            # Try to launch terminal more aggressively
            terminal_cmds = [
                ["konsole", "-e", f"bash {script_path}"],
                ["gnome-terminal", "--", "bash", script_path],
                ["xterm", "-e", f"bash {script_path}"],
                ["alacritty", "-e", f"bash {script_path}"]
            ]

            for cmd in terminal_cmds:
                try:
                    subprocess.Popen(cmd)
                    self.show_warning(f"Launched debug in {cmd[0]}", 5000)
                    return
                except FileNotFoundError:
                    continue

            self.show_warning(
                "No terminal found. Install one of:\n"
                "- konsole\n"
                "- gnome-terminal\n"
                "- xterm\n"
                "- alacritty",
                10000
            )

        except Exception as e:
            self.show_warning(
                f"Error launching debug: {str(e)}\n"
                "Try running manually:\n"
                f"bash {script_path}",
                30000
            )

    def refresh_devices(self):
        """Refresh the list of available keyboard devices."""
        self.device_combo.clear()
        try:
            devices = []
            
            # Try by-path firstnarst
            by_path = "/dev/input/by-path"
            if os.path.exists(by_path):
                for device in os.listdir(by_path):
                    if "kbd" in device.lower():
                        full_path = os.path.join(by_path, device)
                        real_path = os.path.realpath(full_path)
                        if os.path.exists(real_path):
                            # Get device name from /proc/bus/input/devices
                            with open('/proc/bus/input/devices', 'r') as f:
                                content = f.read()
                                event_num = real_path.split('event')[-1]
                                for block in content.split('\n\n'):
                                    if f'event{event_num}' in block:
                                        name = [line for line in block.split('\n') 
                                               if line.startswith('N: Name=')]
                                        if name:
                                            name = name[0].split('"')[1]
                                            devices.append((
                                                full_path,  # Use by-path path
                                                f"{name} ({full_path})",
                                                'platform' in device
                                            ))

            # Also check by-id
            by_id = "/dev/input/by-id"
            if os.path.exists(by_id):
                for device in os.listdir(by_id):
                    if "kbd" in device.lower():
                        full_path = os.path.join(by_id, device)
                        real_path = os.path.realpath(full_path)
                        if os.path.exists(real_path):
                            # Get device name from /proc/bus/input/devices
                            with open('/proc/bus/input/devices', 'r') as f:
                                content = f.read()
                                event_num = real_path.split('event')[-1]
                                for block in content.split('\n\n'):
                                    if f'event{event_num}' in block:
                                        name = [line for line in block.split('\n') 
                                               if line.startswith('N: Name=')]
                                        if name:
                                            name = name[0].split('"')[1]
                                            devices.append((
                                                full_path,  # Use by-id path
                                                f"{name} ({full_path})",
                                                False
                                            ))

            # Fallback to direct event devices if needed
            if not devices:
                with open('/proc/bus/input/devices', 'r') as f:
                    content = f.read()
                    for block in content.split('\n\n'):
                        if 'kbd' in block.lower():
                            name = [line for line in block.split('\n') 
                                   if line.startswith('N: Name=')]
                            handlers = [line for line in block.split('\n') 
                                      if line.startswith('H: Handlers=')]
                            if name and handlers:
                                name = name[0].split('"')[1]
                                for handler in handlers[0].split('=')[1].split():
                                    if handler.startswith('event'):
                                        path = f"/dev/input/{handler}"
                                        devices.append((
                                            path,
                                            f"{name} ({path})",
                                            False
                                        ))

            if devices:
                # Sort devices - platform keyboards first, then alphabetically
                devices.sort(key=lambda x: (not x[2], x[1]))
                
                # Add devices to combo box
                for path, description, _ in devices:
                    self.device_combo.addItem(description, path)
                
                # Select first device (should be main keyboard)
                self.device_combo.setCurrentIndex(0)
                
                self.show_warning(
                    f"Found {len(devices)} keyboard devices\n"
                    f"Selected: {self.device_combo.currentText()}",
                    5000
                )
            else:
                self.show_warning("No keyboard devices found", 10000)
                self.device_combo.addItem("No keyboard devices found")

        except Exception as e:
            self.show_warning(f"Error accessing keyboard devices: {str(e)}", 10000)
            self.device_combo.addItem("Error accessing devices")

    def update_config(self):
        """Update KMonad config with current layout and device."""
        device = self.device_combo.currentData()  # Get the raw device path
        if not device:
            self.show_warning("No keyboard device selected", 5000)
            return

        config = f"""(defcfg
  input  (device-file "{device}")
  output (uinput-sink "KMonad: Compyutinator")
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

(deflayer default
  esc  f1   f2   f3   f4   f5   f6   f7   f8   f9   f10  f11  f12
  grv  1    2    3    4    5    6    7    8    9    0    -    =    bspc
  tab  q    w    e    r    t    y    u    i    o    p    [    ]    \\
  @cap a    s    d    f    g    h    j    k    l    ;    '    ret
  lsft z    x    c    v    b    n    m    ,    .    /    rsft
  lctl lmet lalt           spc            ralt rmet menu rctl
)"""
        self.config_edit.setText(config)

    def load_config(self):
        """Load KMonad config from file."""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Load KMonad Config",
            os.path.expanduser("~/.config/kmonad"),
            "KMonad Config (*.kbd);;All Files (*.*)"
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    self.config_edit.setText(f.read())
                self.parse_config(self.config_edit.toPlainText())
            except Exception as e:
                self.show_warning(f"Error loading config: {str(e)}")

    def save_config(self):
        """Save KMonad config to file."""
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save KMonad Config",
            os.path.expanduser("~/.config/kmonad"),
            "KMonad Config (*.kbd);;All Files (*.*)"
        )
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.config_edit.toPlainText())
            except Exception as e:
                self.show_warning(f"Error saving config: {str(e)}")

    def generate_layout_config(self, use_default=False, use_special=False) -> str:
        """Generate KMonad layout configuration from current key positions."""
        if not hasattr(self, 'default_layout') or not self.default_layout:
            return ""
            
        layout = []
        for row in range(self.layout.count() - 3):  # Skip device selector and controls
            row_widget = self.layout.itemAt(row).widget()
            if isinstance(row_widget, QWidget):
                row_name = row_widget.property("row_name")
                row_layout = row_widget.layout()
                if not row_layout:  # Skip if row layout is not initialized
                    continue
                    
                row_keys = []
                if use_default and row_name in self.default_layout:
                    row_keys = self.default_layout[row_name]
                else:
                    for i in range(row_layout.count() - 1):  # Skip stretch
                        key_block = row_layout.itemAt(i).widget()
                        if isinstance(key_block, KeyBlock):
                            key = key_block.key if key_block.key != " " else "_"
                            if use_special and key in self.special_keys:
                                key = self.special_keys[key]
                            row_keys.append(key)
                            
                if row_keys:  # Only add non-empty rows
                    layout.append(" ".join(row_keys))
                    
        return "\n  ".join(layout)

    def create_keyboard_layout(self):
        """Create initial empty keyboard layout."""
        # Define row configurations with explicit max lengths
        self.row_configs = [
            {"name": "Function", "length": 13},
            {"name": "Number", "length": 14},
            {"name": "QWERTY", "length": 14},
            {"name": "Home", "length": 13},
            {"name": "Shift", "length": 12},
            {"name": "Control", "length": 8}
        ]
        
        # Create rows
        for config in self.row_configs:
            row_widget = QWidget()
            row_widget.setProperty("row_name", config["name"])
            row_widget.setProperty("max_length", config["length"])
            row_layout = QHBoxLayout(row_widget)
            row_layout.setSpacing(2)
            row_layout.setContentsMargins(2, 2, 2, 2)
            
            # Create key blocks with default layout
            default_keys = self.default_layout[config["name"]]
            for i in range(config["length"]):
                key = default_keys[i] if i < len(default_keys) else " "
                key_block = KeyBlock(key, self)
                key_block.setText(key)  # Set visible text
                row_layout.addWidget(key_block)
            
            row_layout.addStretch()
            self.main_layout.addWidget(row_widget)

    def toggle_kmonad(self):
        """Toggle KMonad on/off."""
        if self.kmonad_process is None or self.kmonad_process.state() == QProcess.ProcessState.NotRunning:
            try:
                # Kill any existing KMonad processes first
                subprocess.run(['pkill', 'kmonad'], check=False)
                
                # Save current config to temp file
                config_file = os.path.join(tempfile.gettempdir(), "temp_kmonad.kbd")
                with open(config_file, 'w') as f:
                    f.write(self.config_edit.toPlainText())
                
                # Verify config file exists and contents
                if not os.path.exists(config_file):
                    raise RuntimeError(f"Config file not created: {config_file}")
                with open(config_file) as f:
                    self.show_warning(f"Config contents:\n{f.read()}")

                # Check KMonad installation
                which_result = subprocess.run(['which', 'kmonad'], capture_output=True, text=True)
                if which_result.returncode != 0:
                    raise RuntimeError("KMonad not found in PATH")
                kmonad_path = which_result.stdout.strip()
                self.show_warning(f"Found KMonad at: {kmonad_path}")

                # Check permissions
                ls_result = subprocess.run(['ls', '-l', '/dev/uinput'], capture_output=True, text=True)
                self.show_warning(f"uinput permissions:\n{ls_result.stdout}")
                
                groups_result = subprocess.run(['groups'], capture_output=True, text=True)
                self.show_warning(f"Current user groups:\n{groups_result.stdout}")

                # Start KMonad process with full error capture
                self.kmonad_process = QProcess()
                self.kmonad_process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
                
                # Connect signals
                self.kmonad_process.readyReadStandardOutput.connect(self.handle_kmonad_output)
                self.kmonad_process.errorOccurred.connect(self.handle_kmonad_error)
                self.kmonad_process.finished.connect(self.handle_kmonad_finished)
                
                # Start KMonad with debug output
                cmd = [kmonad_path, "-d", config_file]
                self.show_warning(f"Starting KMonad: {' '.join(cmd)}")
                self.kmonad_process.start(kmonad_path, ["-d", config_file])
                
                if not self.kmonad_process.waitForStarted(1000):
                    error = self.kmonad_process.errorString()
                    raise RuntimeError(f"Failed to start KMonad: {error}")
                
                # Wait a bit and check if process is still running
                QTimer.singleShot(1000, self.check_kmonad_running)
                
                self.start_button.setText("Stop KMonad")
                self.show_warning("KMonad started, checking status...")
                
            except Exception as e:
                self.show_warning(
                    f"Error starting KMonad: {str(e)}\n"
                    "Try running debug to troubleshoot",
                    30000
                )
        else:
            try:
                self.kmonad_process.kill()
                subprocess.run(['pkill', 'kmonad'], check=False)
                self.show_warning("KMonad stopped")
                self.start_button.setText("Start KMonad")
            except Exception as e:
                self.show_warning(f"Error stopping KMonad: {str(e)}")

    def check_kmonad_running(self):
        """Check if KMonad is still running after start."""
        try:
            # Check process
            ps_result = subprocess.run(
                ['ps', 'aux'], 
                capture_output=True, 
                text=True
            )
            if "kmonad" not in ps_result.stdout.lower():
                # KMonad died - check system log
                journal_result = subprocess.run(
                    ['journalctl', '-n', '50'], 
                    capture_output=True, 
                    text=True
                )
                self.show_warning(
                    "Error: KMonad failed to start\n"
                    f"System log:\n{journal_result.stdout}\n"
                    "Common issues:\n"
                    "1. uinput module not loaded (run 'sudo modprobe uinput')\n"
                    "2. Permission denied on /dev/uinput\n"
                    "3. User not in input group\n"
                    "4. Invalid config syntax\n"
                    "Try running: kmonad -d /tmp/temp_kmonad.kbd",
                    0
                )
                return

            # Check if device was created
            ls_result = subprocess.run(
                ['ls', '-l', '/dev/input/by-id'], 
                capture_output=True, 
                text=True
            )
            if "kmonad" not in ls_result.stdout.lower():
                self.show_warning(
                    "Warning: KMonad running but device not created\n"
                    "Try typing 'a' - it should output 'b'\n"
                    "If not working, check permissions and run debug",
                    0
                )
                return

            self.show_warning(
                "KMonad running and device created\n"
                "Try typing 'a' - it should output 'b'"
            )

        except Exception as e:
            self.show_warning(f"Error checking KMonad: {str(e)}")

    def handle_kmonad_output(self):
        """Handle KMonad process output."""
        if self.kmonad_process:
            output = bytes(self.kmonad_process.readAllStandardOutput()).decode()
            if output.strip():
                self.show_warning(f"KMonad output: {output.strip()}")

    def handle_kmonad_error(self, error):
        """Handle KMonad process errors."""
        error_text = {
            QProcess.ProcessError.FailedToStart: "Failed to start KMonad",
            QProcess.ProcessError.Crashed: "KMonad crashed",
            QProcess.ProcessError.Timedout: "KMonad timed out",
            QProcess.ProcessError.WriteError: "Failed to write to KMonad",
            QProcess.ProcessError.ReadError: "Failed to read from KMonad",
            QProcess.ProcessError.UnknownError: "Unknown KMonad error"
        }.get(error, f"KMonad error: {error}")
        
        self.show_warning(
            f"Error: {error_text}\n"
            "Click 'Debug in Terminal' for more details",
            0  # Don't auto-hide errors
        )

    def handle_kmonad_finished(self, exit_code, exit_status):
        """Handle KMonad process finishing."""
        self.start_button.setText("Start KMonad")
        if exit_code != 0:
            self.show_warning(
                f"KMonad exited with code {exit_code}\n"
                "Common issues:\n"
                "1. Invalid device path\n"
                "2. Permission denied\n"
                "3. Config syntax error\n"
                "Try running debug to troubleshoot",
                0  # Don't auto-hide errors
            )

    def check_existing_kmonad(self):
        """Check for existing KMonad processes and update UI accordingly."""
        try:
            # Check for running kmonad processes
            result = subprocess.run(
                ['pgrep', '-a', 'kmonad'],
                capture_output=True,
                text=True
            )
            
            if result.stdout:
                self.kmonad_pid = int(result.stdout.split()[0])
                self.start_button.setText("Stop KMonad")
                # Create process object for existing kmonad
                self.kmonad_process = QProcess()
                self.kmonad_process.setProcessId(self.kmonad_pid)
            else:
                self.kmonad_pid = None
                self.start_button.setText("Start KMonad")
                
        except subprocess.CalledProcessError:
            self.show_warning("Error checking KMonad processes")

    def kill_existing_kmonad(self):
        """Kill any existing KMonad processes."""
        try:
            subprocess.run(['pkill', 'kmonad'], check=True)
            return True
        except subprocess.CalledProcessError:
            self.show_warning("Error killing existing KMonad processes")
            return False

    def closeEvent(self, event):
        """Handle window close event."""
        if self.minimize_to_tray.isChecked():
            event.ignore()
            self.hide()
        else:
            # Clean up process object but don't kill KMonad
            if self.kmonad_process is not None:
                self.kmonad_process.setParent(None)
                self.kmonad_process = None
            event.accept()

    def create_tray_icon(self):
        """Create system tray icon and menu."""
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme('input-keyboard'))
        
        # Create tray menu
        self.tray_menu = QMenu()
        
        self.show_action = self.tray_menu.addAction("Show")
        self.show_action.triggered.connect(self.show)
        
        self.toggle_action = self.tray_menu.addAction("Stop KMonad")
        self.toggle_action.triggered.connect(self.toggle_kmonad)
        
        self.tray_menu.addSeparator()
        
        quit_action = self.tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_application)
        
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        
        # Show tray icon
        self.tray_icon.show()
        
    def update_tray_status(self, running=False):
        """Update tray icon tooltip and menu to reflect KMonad status."""
        if running:
            self.tray_icon.setToolTip("KMonad Running")
            self.toggle_action.setText("Stop KMonad")
            # Optional: change icon to indicate running state
            self.tray_icon.setIcon(QIcon.fromTheme('input-keyboard-virtual-on'))
        else:
            self.tray_icon.setToolTip("KMonad Stopped")
            self.toggle_action.setText("Start KMonad")
            self.tray_icon.setIcon(QIcon.fromTheme('input-keyboard'))

    def tray_activated(self, reason):
        """Handle tray icon activation."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()
                self.activateWindow()

    def quit_application(self):
        """Quit the application."""
        # Optionally kill KMonad before quitting
        if self.kmonad_process is not None:
            reply = QMessageBox.question(
                self,
                "Quit",
                "Stop KMonad before quitting?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                self.kill_existing_kmonad()
        
        QApplication.quit()

    def update_layout(self, state):
        """Update keyboard layout based on offset toggle."""
        for row_idx in range(self.layout.count() - 3):  # Skip device selector and controls
            row_widget = self.layout.itemAt(row_idx).widget()
            if isinstance(row_widget, QWidget):
                row_layout = row_widget.layout()
                row_name = row_widget.property("row_name")
                
                # Calculate offset for this row
                offset = self.row_offsets.get(row_name, 0) if state else 0
                
                # Update margin to create offset
                row_layout.setContentsMargins(offset, 2, 2, 2)
                row_widget.setContentsMargins(offset, 2, 2, 2)  # Also update widget margins
                
                # Force layout update
                row_widget.updateGeometry()
                self.update()
                
                # Store state for this row
                self.row_states[row_idx] = {
                    'offset': offset,
                    'active': state
                }

    def parse_config(self, config_text):
        """Parse KMonad config and update layout."""
        try:
            # Find the deflayer section
            layer_match = re.search(r'\(deflayer\s+default\s+([\s\S]+?)\)', config_text)
            if not layer_match:
                return
                
            layout_text = layer_match.group(1)
            rows = layout_text.strip().split('\n')
            
            # Update key blocks
            for row_idx, row in enumerate(rows):
                if row_idx >= self.layout.count() - 3:  # Skip device selector and controls
                    break
                    
                row_widget = self.layout.itemAt(row_idx).widget()
                if isinstance(row_widget, QWidget):
                    row_layout = row_widget.layout()
                    keys = row.strip().split()
                    
                    for key_idx, key in enumerate(keys):
                        if key_idx >= row_layout.count() - 1:  # Skip stretch
                            break
                            
                        key_block = row_layout.itemAt(key_idx).widget()
                        if isinstance(key_block, KeyBlock):
                            # Handle special key mappings
                            if key in self.special_keys:
                                key = key.strip('()')  # Remove parentheses from aliases
                            key_block.key = key
                            key_block.setText(key)
                            
        except Exception as e:
            self.show_warning(f"Error parsing config: {str(e)}")

    def get_layout_config(self):
        """Get current layout configuration."""
        layout = []
        for row_idx in range(self.layout.count() - 3):  # Skip device selector and controls
            row_widget = self.layout.itemAt(row_idx).widget()
            if isinstance(row_widget, QWidget):
                row_layout = row_widget.layout()
                row_keys = []
                
                for key_idx in range(row_layout.count() - 1):  # Skip stretch
                    key_block = row_layout.itemAt(key_idx).widget()
                    if isinstance(key_block, KeyBlock):
                        row_keys.append(key_block.key)
                        
                layout.append(row_keys)
                
        return layout

    def change_layout(self, layout_name):
        """Change keyboard layout."""
        if layout_name in self.layouts:
            self.default_layout = self.layouts[layout_name]
            # Update visual layout
            self.update_visual_layout()
            # Update config
            if layout_name == "Colemak":
                self.config_edit.setText(
                    self.kmonad_configs["QWERTY-Colemak"].replace(
                        "DEVICE_ID", 
                        self.device_combo.currentText()
                    ))

    def update_visual_layout(self):
        """Update visual layout with current mapping."""
        for row_idx in range(self.layout.count() - 3):
            row_widget = self.layout.itemAt(row_idx).widget()
            if isinstance(row_widget, QWidget):
                row_name = row_widget.property("row_name")
                if row_name in self.default_layout:
                    row_layout = row_widget.layout()
                    keys = self.default_layout[row_name]
                    for key_idx, key in enumerate(keys):
                        if key_idx < row_layout.count() - 1:
                            key_block = row_layout.itemAt(key_idx).widget()
                            if isinstance(key_block, KeyBlock):
                                key_block.key = key
                                key_block.setText(key)

    def kill_all_kmonad(self):
        """Kill all running KMonad processes."""
        try:
            subprocess.run(['pkill', 'kmonad'], check=False)
            self.show_warning("Killed all KMonad processes")
        except Exception as e:
            self.show_warning(f"Error killing KMonad: {str(e)}")

    def load_default_config(self):
        """Load default KMonad config."""
        device = self.device_combo.currentData()
        if not device:
            self.show_warning("No keyboard device selected", 5000)
            return

        # Simple test config - maps 'a' to 'b' to verify remapping works
        default_config = f"""(defcfg
  input  (device-file "{device}")
  output (uinput-sink "KMonad: Compyutinator")
  fallthrough true
  allow-cmd true
)

(defsrc
  a
)

(deflayer default
  b
)"""
        self.config_edit.setText(default_config)
        self.show_warning(
            "Loaded test config - 'a' should type as 'b'\n"
            "Try typing 'a' to test if KMonad is working",
            0
        )

    def spreadRow(self, row_layout):
        """Spread keys in a row based on staggered layout setting."""
        is_staggered = self.offset_toggle.isChecked()
        row_index = self.get_row_index(row_layout)
        
        # Calculate offset based on row
        if is_staggered:
            offset = row_index * 25  # Staggered offset
        else:
            offset = 0  # Aligned layout
            
        # Apply offset to first spacer in row
        if row_layout.count() > 0:
            first_item = row_layout.itemAt(0)
            if isinstance(first_item, QSpacerItem):
                row_layout.removeItem(first_item)
                row_layout.insertItem(0, QSpacerItem(offset, 0))

    def get_row_index(self, row_layout):
        """Get the index of a row in the keyboard layout."""
        parent = row_layout.parent()
        if parent:
            main_layout = parent.parent().layout()
            for i in range(main_layout.count()):
                if main_layout.itemAt(i).widget() == parent:
                    return i
        return 0

    def update_key_sizes(self):
        """Update the size of all key widgets."""
        size = self.key_size_spin.value()
        for row in self.findChildren(QWidget, "keyboard_row"):
            for key in row.findChildren(KeyBlock):
                key.setFixedSize(size, size)

class KeyBlock(QWidget):
    """A custom widget representing a keyboard key."""
    
    is_dragging = False
    dragged_key = None  # Class variable to track currently dragged key

    def __init__(self, key, parent=None):
        super().__init__(parent)
        self.key = key
        self.original_key = key
        self.is_placeholder = False
        self.is_target = False
        self.is_neighbor = False
        self.drop_side = None  # 'left' or 'right' or None
        self.setFixedSize(50, 50)
        self.setText(key)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)  # Enable mouse tracking for hover
        
        # Enable animation
        self.animation = QPropertyAnimation(self, b"pos")
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutQuad)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Set colors based on state
        if self.is_placeholder:
            bg_color = QColor("#1a1a1a")
            text_color = QColor("#404040")
            border_color = QColor("#2a2a2a")
        else:
            bg_color = QColor("#2a2a2a")
            text_color = QColor("white")
            border_color = QColor("#3a3a3a")
            
            if self.is_target and KeyBlock.is_dragging:
                bg_color = QColor("#3a5a3a")
                border_color = QColor("#4a6a4a")
            elif self.is_target:
                # Subtle highlight when just hovering
                bg_color = QColor("#2d2d2d")
                border_color = QColor("#3d3d3d")
            elif self.is_neighbor and KeyBlock.is_dragging:
                bg_color = QColor("#2a3a2a")
                border_color = QColor("#3a5a3a")
        
        # Draw background
        painter.fillRect(self.rect(), bg_color)
        
        # Draw border with drop indicators
        pen = QPen(border_color)
        pen.setWidth(2)
        painter.setPen(pen)
        
        if self.drop_side == 'left':
            left_pen = QPen(QColor("#90ff90"))
            left_pen.setWidth(4)
            painter.setPen(left_pen)
            painter.drawLine(0, 0, 0, self.height())
            painter.setPen(pen)
        elif self.drop_side == 'right':
            right_pen = QPen(QColor("#90ff90"))
            right_pen.setWidth(4)
            painter.setPen(right_pen)
            painter.drawLine(self.width()-1, 0, self.width()-1, self.height())
            painter.setPen(pen)
        
        painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 4, 4)
        
        # Draw text
        painter.setPen(text_color)
        font = painter.font()
        font.setPointSize(10)
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.key)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self.is_placeholder:
            self.dragStartPosition = event.pos()
            KeyBlock.is_dragging = True
            KeyBlock.dragged_key = self
            # Start spreading immediately
            parent_row = self.parent()
            if parent_row:
                self.spreadRow(parent_row.layout())
            self.update()

    def mouseMoveEvent(self, event):
        if not (event.buttons() & Qt.MouseButton.LeftButton) or not KeyBlock.is_dragging:
            return
            
        if (event.pos() - self.dragStartPosition).manhattanLength() < QApplication.startDragDistance():
            return

        # Start drag
        drag = QDrag(self)
        mimeData = QMimeData()
        mimeData.setText(self.key)
        drag.setMimeData(mimeData)

        # Create semi-transparent drag pixmap
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        self.render(pixmap)
        painter = QPainter(pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.fillRect(pixmap.rect(), QColor(0, 0, 0, 127))
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.pos())

        # Set placeholder state
        self.is_placeholder = True
        self.key = ""
        self.update()

        # Execute drag
        result = drag.exec(Qt.DropAction.MoveAction)
        
        # Reset states
        KeyBlock.is_dragging = False
        KeyBlock.dragged_key = None

        if result == Qt.DropAction.IgnoreAction:
            self.is_placeholder = False
            self.key = self.original_key
            self.update()

    def dragEnterEvent(self, event):
        if event.mimeData().hasText() and KeyBlock.is_dragging:
            event.accept()
            parent_row = self.parent()
            if parent_row:
                row_layout = parent_row.layout()
                self.spreadRow(row_layout)
                self.is_target = True
                self.update()

    def dragMoveEvent(self, event):
        """Handle drag move events."""
        if event.mimeData().hasText():
            event.accept()
            # Update target state
            self.is_target = True
            # Use position() instead of pos() for QDragMoveEvent
            mouse_x = event.position().x()
            self.drop_side = 'right' if mouse_x > self.width() / 2 else 'left'
            
            # Update row spreading based on drop position
            parent_row = self.parent()
            if parent_row:
                row_layout = parent_row.layout()
                # Clear other targets in row
                for i in range(row_layout.count() - 1):
                    key = row_layout.itemAt(i).widget()
                    if isinstance(key, KeyBlock) and key != self:
                        key.is_target = False
                        key.drop_side = None
                # Update current target
                self.is_target = True
                self.update()
                # Only spread row if we're actually dragging a key
                if KeyBlock.is_dragging:
                    self.spreadRow(row_layout)

    def dragLeaveEvent(self, event):
        """Handle key block being dragged out."""
        self.is_target = False
        self.drop_side = None
        self.update()
        
        # Reset row spacing when key is dragged out
        keyboard_layout = self.get_keyboard_layout()
        parent_row = self.get_parent_row()
        if keyboard_layout and parent_row:
            if keyboard_layout.offset_toggle.isChecked():
                # Maintain staggered layout
                row_index = keyboard_layout.get_row_index(parent_row.layout())
                offset = row_index * 25
                self.adjustRowSpacing(parent_row.layout(), offset)
            else:
                # Reset to aligned layout
                self.adjustRowSpacing(parent_row.layout(), 0)
    
    def dropEvent(self, event):
        """Handle drop events."""
        if event.mimeData().hasText():
            source = event.source()
            if source != self:
                # Handle key swap
                new_key = event.mimeData().text()
                if self.is_placeholder:
                    self.is_placeholder = False
                    self.key = new_key
                    self.original_key = new_key
                else:
                    source.key = self.key
                    source.original_key = self.key
                    self.key = new_key
                    self.original_key = new_key
                
                # Reset states
                self.is_target = False
                self.drop_side = None
                source.is_placeholder = False
                
                # Update visuals
                self.update()
                source.update()
                
                # Adjust row spacing after drop
                keyboard_layout = self.get_keyboard_layout()
                parent_row = self.get_parent_row()
                if keyboard_layout and parent_row:
                    if keyboard_layout.offset_toggle.isChecked():
                        row_index = keyboard_layout.get_row_index(parent_row.layout())
                        offset = row_index * 25
                        self.adjustRowSpacing(parent_row.layout(), offset)
                    else:
                        self.adjustRowSpacing(parent_row.layout(), 0)
                
            event.accept()
    
    def adjustRowSpacing(self, row_layout, offset):
        """Adjust spacing of keys in a row."""
        # Remove existing spacers
        for i in range(row_layout.count()-1, -1, -1):
            item = row_layout.itemAt(i)
            if isinstance(item, QSpacerItem):
                row_layout.removeItem(item)
        
        # Add initial offset spacer
        if offset > 0:
            row_layout.insertItem(0, QSpacerItem(offset, 0))
        
        # Add spacing between keys
        key_spacing = 5
        for i in range(row_layout.count()):
            if isinstance(row_layout.itemAt(i).widget(), KeyBlock):
                if i < row_layout.count() - 1:  # Don't add after last key
                    row_layout.insertItem(i + 1, QSpacerItem(key_spacing, 0))
        
        # Add stretch at end
        row_layout.addStretch()
    
    def get_keyboard_layout(self):
        """Find the KeyboardLayout parent widget."""
        parent = self.parent()
        while parent:
            if isinstance(parent, KeyboardLayout):
                return parent
            parent = parent.parent()
        return None
    
    def get_parent_row(self):
        """Get the parent row widget."""
        parent = self.parent()
        while parent:
            if parent.objectName() == "keyboard_row":
                return parent
            parent = parent.parent()
        return None

    def enterEvent(self, event):
        """Handle mouse enter for hover effects."""
        if KeyBlock.is_dragging and KeyBlock.dragged_key != self:
            # Get parent row and spread only if actually dragging
            parent_row = self.parent()
            if parent_row:
                row_layout = parent_row.layout()
                # If this is same row as source, handle placeholder
                if KeyBlock.dragged_key and KeyBlock.dragged_key.parent() == parent_row:
                    KeyBlock.dragged_key.is_placeholder = False
                    KeyBlock.dragged_key.update()
                self.spreadRow(row_layout)
                self.is_target = True
                self.update()
        else:
            # Just update appearance without spreading if not dragging
            self.is_target = True
            self.update()

    def leaveEvent(self, event):
        """Handle mouse leave."""
        parent_row = self.parent()
        if parent_row and KeyBlock.is_dragging:
            row_layout = parent_row.layout()
            self.resetRow(row_layout)
        self.is_target = False
        self.drop_side = None
        self.update()

    def spreadRow(self, row_layout):
        """Spread keys in row to accommodate dragged key."""
        # Only spread if actually dragging
        if not KeyBlock.is_dragging:
            return
            
        spacing = 20  # Spread spacing
        target_index = row_layout.indexOf(self)
        
        # Get current row offset (for staggered layout)
        row_widget = row_layout.parent()
        keyboard_layout = row_widget.parent()
        is_staggered = keyboard_layout.offset_toggle.isChecked()
        
        # Get stagger offset if in staggered mode
        base_offset = 0
        if is_staggered:
            row_name = row_widget.property("row_name")
            base_offset = keyboard_layout.row_offsets.get(row_name, 0)
        
        # Calculate positions
        for i in range(row_layout.count() - 1):
            key = row_layout.itemAt(i).widget()
            if isinstance(key, KeyBlock):
                if key.is_placeholder:
                    continue
                
                # Calculate base position with stagger
                new_x = base_offset + (i * (key.width() + 2))  # Base position
                
                # Add spreading space when dragging
                if i > target_index:
                    new_x += spacing  # Make room for dragged key
                
                # Move key
                current_pos = key.pos()
                if current_pos.x() != new_x:
                    key.animate_to(QPoint(new_x, current_pos.y()))
                
                # Update visual state
                key.is_target = (i == target_index)
                key.is_neighbor = abs(i - target_index) == 1
                key.update()

    def resetRow(self, row_layout):
        """Reset row to normal spacing."""
        # Get stagger offset
        row_widget = row_layout.parent()
        keyboard_layout = row_widget.parent()
        is_staggered = keyboard_layout.offset_toggle.isChecked()
        
        base_offset = 0
        if is_staggered:
            row_name = row_widget.property("row_name")
            base_offset = keyboard_layout.row_offsets.get(row_name, 0)
        
        normal_spacing = 2  # Normal spacing between keys
        for i in range(row_layout.count() - 1):
            key = row_layout.itemAt(i).widget()
            if isinstance(key, KeyBlock):
                # Reset to original position with stagger
                new_x = base_offset + (i * (key.width() + normal_spacing))
                current_pos = key.pos()
                if current_pos.x() != new_x:
                    key.animate_to(QPoint(new_x, current_pos.y()))
                # Reset visual state
                key.is_neighbor = False
                key.update()

    def setText(self, text):
        """Set the text of the key block."""
        self.key = text
        

    def animate_to(self, new_pos):
        """Animate key block to new position."""
        if self.pos() == new_pos:
            return
        
        self.animation.stop()
        self.animation.setStartValue(self.pos())
        self.animation.setEndValue(new_pos)
        self.animation.start()