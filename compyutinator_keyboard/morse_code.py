"""Morse Code Module - Provides Morse code visualization and recognition."""

from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
                            QTextEdit, QPushButton, QGridLayout, QSpinBox, QComboBox, QScrollArea, QProgressBar)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QColor, QPen, QRadialGradient
import time
import numpy as np
import sounddevice as sd
import threading
import queue
import random
import string

class MorseTone:
    """Handles Morse code audio tones."""
    
    def __init__(self, frequency=800, sample_rate=44100):
        self.frequency = frequency
        self.sample_rate = sample_rate
        self.is_playing = False
        self.stream = None
        self.input_stream = None  # Add this to fix the attribute error
        
        # Generate tone with no fade for short taps
        duration = 0.02  # 20ms base tone
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        self.tone = np.sin(2 * np.pi * frequency * t).astype(np.float32)
        
        # Amplify the signal for better audibility
        self.tone *= 0.9  # Increase volume to 90% of max
        
        # Create separate tones for dot and dash
        self.dot_tone = self.tone  # Short tone for dots
        
        # Longer tone for dashes
        dash_duration = 0.1  # 100ms for dash
        t_dash = np.linspace(0, dash_duration, int(sample_rate * dash_duration), False)
        self.dash_tone = np.sin(2 * np.pi * frequency * t_dash).astype(np.float32)
        self.dash_tone *= 0.9
        
        # Detection parameters
        self.freq_filter = np.exp(-2.0j * np.pi * frequency / sample_rate)
        self.z = 0
        self.last_magnitude = 0
        self.detection_history = []
        self.noise_floor = 0.0005
        
        # State tracking
        self.signal_start = None
        self.debounce_time = 0.002  # 2ms debounce
        self.last_state_change = 0
        self.is_listening = False  # Add this to fix state tracking
        
        # Audio monitoring
        self.audio_monitor_callback = None
        self.audio_level = 0
    
    def play(self, is_dot=True):
        """Start playing tone with type selection."""
        # Stop any existing playback
        if self.is_playing:
            sd.stop()
            if self.stream:
                self.stream.stop()
                self.stream.close()
                self.stream = None
        
        # Start new playback
        self.stream = sd.OutputStream(
            channels=1,
            samplerate=self.sample_rate,
            blocksize=128,  # Smaller blocks
            dtype=np.float32,
            latency='low'
        )
        self.stream.start()
        self.is_playing = True
        
        # Select and play tone
        tone = self.dot_tone if is_dot else self.dash_tone
        sd.play(tone, self.sample_rate)
    
    def start_listening(self, callback, device_idx=None, monitor_callback=None):
        """Start listening with better short signal detection."""
        self.audio_monitor_callback = monitor_callback
        
        def audio_callback(indata, frames, time, status):
            if status:
                print(status)
            
            now = time.time()
            chunk_size = 64  # Smaller chunks for faster response
            
            for i in range(0, len(indata), chunk_size):
                chunk = indata[i:i+chunk_size, 0]
                
                # Fast power calculation
                power = np.sum(np.square(chunk)) / chunk_size
                
                # Goertzel for frequency detection
                self.z = 0
                for sample in chunk:
                    self.z = sample + self.freq_filter * self.z
                tone_power = abs(self.z) / chunk_size
                
                # Combined detection using both power and frequency
                signal_strength = np.sqrt(power * tone_power)
                
                # Update noise floor more aggressively for silence
                if signal_strength < self.noise_floor * 2:
                    self.noise_floor = (self.noise_floor * 0.95 + 
                                      signal_strength * 0.05)
                
                # Thresholds with better separation
                threshold_on = max(self.noise_floor * 15, 0.003)
                threshold_off = threshold_on * 0.4
                
                # State change detection with immediate response
                if signal_strength > threshold_on:
                    if not self.is_listening:
                        self.is_listening = True
                        self.signal_start = now
                        callback(True)
                elif signal_strength < threshold_off:
                    if self.is_listening:
                        self.is_listening = False
                        callback(False)
                
                # Update level meter
                if self.audio_monitor_callback:
                    self.audio_monitor_callback(signal_strength)
        
        try:
            if not self.input_stream:
                self.input_stream = sd.InputStream(
                    device=device_idx,
                    channels=1,
                    samplerate=self.sample_rate,
                    blocksize=128,  # Smaller blocks
                    callback=audio_callback,
                    latency='low'  # Request low latency
                )
                self.input_stream.start()
        except Exception as e:
            print(f"Error starting audio input: {e}")
            return False
        return True
    
    def stop_listening(self):
        """Stop listening for tones."""
        if self.input_stream:
            self.input_stream.stop()
            self.input_stream.close()
            self.input_stream = None
        self.is_listening = False
    
    def stop(self):
        """Stop playing tone."""
        self.is_playing = False
        sd.stop()
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        if self.input_stream:  # Add check for input_stream
            self.stop_listening()

class MorseChart(QWidget):
    """Widget displaying Morse code chart."""
    
    # Move morse_dict to class level
    morse_dict = {
        'A': '.-',     'B': '-...',   'C': '-.-.', 
        'D': '-..',    'E': '.',      'F': '..-.',
        'G': '--.',    'H': '....',   'I': '..',
        'J': '.---',   'K': '-.-',    'L': '.-..',
        'M': '--',     'N': '-.',     'O': '---',
        'P': '.--.',   'Q': '--.-',   'R': '.-.',
        'S': '...',    'T': '-',      'U': '..-',
        'V': '...-',   'W': '.--',    'X': '-..-',
        'Y': '-.--',   'Z': '--..',
        '1': '.----',  '2': '..---',  '3': '...--',
        '4': '....-',  '5': '.....',  '6': '-....',
        '7': '--...',  '8': '---..',  '9': '----.',
        '0': '-----',  ' ': ' '
    }
    
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Create grid layout directly (no scroll)
        grid = QGridLayout()
        grid.setSpacing(10)
        
        # Style for code labels - more compact
        code_style = """
            QLabel {
                color: #ffffff;
                font-family: 'Courier New', monospace;
                font-size: 20px;
                padding: 8px;
                background-color: #2a2a2a;
                border-radius: 6px;
                min-width: 100px;
            }
            QLabel:hover {
                background-color: #3a3a3a;
                border: 2px solid #50c0ff;
            }
        """
        
        # Create two-column layout
        row = 0
        col = 0
        max_cols = 8  # More columns, less vertical space
        
        # Letters first
        for char in string.ascii_uppercase:
            code = self.morse_dict[char]
            label = QLabel(f"{char}: {code}")
            label.setStyleSheet(code_style)
            grid.addWidget(label, row, col)
            col += 1
            if col >= max_cols:
                col = 0
                row += 1
        
        # Numbers on last row
        row += 1
        col = 0
        for num in string.digits:
            code = self.morse_dict[num]
            label = QLabel(f"{num}: {code}")
            label.setStyleSheet(code_style)
            grid.addWidget(label, row, col)
            col += 1
        
        layout.addLayout(grid)

class MorseVisualizer(QWidget):
    """Widget for visualizing Morse code input."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(50)
        self.signals = []  # List of (start_time, duration, is_dot)
        self.max_history = 2.0  # Seconds of history to show
        
        # Start update timer
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start(50)  # 20 FPS
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Background
        painter.fillRect(self.rect(), QColor("#1a1a1a"))
        
        # Draw signals
        now = time.time()
        width = self.width()
        height = self.height()
        
        for start, duration, is_dot in self.signals:
            # Convert time to x position
            age = now - start
            if age > self.max_history:
                continue
                
            x_start = width * (1 - age / self.max_history)
            x_width = width * (duration / self.max_history)
            
            # Draw signal
            color = QColor("#50c0ff") if is_dot else QColor("#ff6b6b")
            painter.fillRect(int(x_start), 10, 
                           max(2, int(x_width)), height - 20, 
                           color)
    
    def add_signal(self, duration, is_dot):
        """Add a new signal to visualize."""
        self.signals.append((time.time(), duration, is_dot))
        # Clean up old signals
        now = time.time()
        self.signals = [s for s in self.signals 
                       if now - s[0] <= self.max_history]

class MorsePractice(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        
        # Practice controls
        controls = QHBoxLayout()
        
        # Mode selection
        self.mode = QComboBox()
        self.mode.addItems(["Random Letters", "Random Words", "Custom Text"])
        controls.addWidget(QLabel("Practice Mode:"))
        controls.addWidget(self.mode)
        
        # Start/Stop button
        self.practice_button = QPushButton("Start Practice")
        self.practice_button.setCheckable(True)
        self.practice_button.toggled.connect(self.toggle_practice)
        controls.addWidget(self.practice_button)
        
        # Speed control
        self.wpm = QSpinBox()
        self.wpm.setRange(5, 40)
        self.wpm.setValue(15)
        controls.addWidget(QLabel("WPM:"))
        controls.addWidget(self.wpm)
        
        layout.addLayout(controls)
        
        # Practice display
        self.target_text = QLabel()
        self.target_text.setStyleSheet("""
            QLabel {
                color: #50c0ff;
                font-size: 24px;
                font-weight: bold;
                padding: 20px;
                background-color: #1a1a1a;
                border-radius: 8px;
            }
        """)
        layout.addWidget(self.target_text)
        
        # Score display
        self.score = QLabel("Score: 0/0")
        layout.addWidget(self.score)
        
        # Practice state
        self.practice_timer = QTimer()
        self.practice_timer.timeout.connect(self.next_practice_char)
        self.current_text = ""
        self.correct_count = 0
        self.total_count = 0
    
    def toggle_practice(self, checked):
        if checked:
            self.start_practice()
        else:
            self.stop_practice()
    
    def start_practice(self):
        mode = self.mode.currentText()
        if mode == "Random Letters":
            self.current_text = "".join(random.choices(string.ascii_uppercase, k=5))
        elif mode == "Random Words":
            words = ["MORSE", "CODE", "PRACTICE", "RADIO", "SIGNAL"]
            self.current_text = random.choice(words)
        # Custom text mode uses existing text
        
        self.target_text.setText(self.current_text)
        interval = 60000 / (self.wpm.value() * 5)  # Convert WPM to ms per char
        self.practice_timer.start(int(interval))
    
    def stop_practice(self):
        self.practice_timer.stop()
        self.target_text.clear()
    
    def next_practice_char(self):
        if self.current_text:
            self.current_text = self.current_text[1:]
            if not self.current_text:
                self.stop_practice()
                self.practice_button.setChecked(False)
            self.target_text.setText(self.current_text)

class AudioMonitor(QWidget):
    """Widget for monitoring audio input level."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(30, 30)
        self.setMaximumSize(30, 30)
        self.level = 0
        self.active = False
        self.peak_level = 0
        
        # Faster updates
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update)
        self.update_timer.start(16)  # ~60 FPS
    
    def set_level(self, level):
        """Update level with peak tracking."""
        self.level = level
        self.peak_level = max(self.peak_level * 0.95, level)
        self.update()
    
    def set_active(self, active):
        """Set activity state."""
        self.active = active
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw circle
        rect = self.rect().adjusted(2, 2, -2, -2)
        if self.active:
            color = QColor("#50ff50")  # Green when active
        else:
            color = QColor("#ff5050")  # Red when inactive
        
        # Create gradient with float coordinates
        center_x = rect.center().x()
        center_y = rect.center().y()
        radius = rect.width() / 2
        gradient = QRadialGradient(center_x, center_y, radius)
        
        # Add gradient stops with level-based brightness
        base_brightness = 100 + int(self.level * 1000)  # More sensitive
        gradient.setColorAt(0, color.lighter(min(200, base_brightness)))
        gradient.setColorAt(1, color)
        
        painter.setBrush(gradient)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(rect)

class MorseRecognizer(QWidget):
    text_recognized = pyqtSignal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(20)
        
        # Add device selection and controls
        device_controls = QHBoxLayout()
        
        # Input device selection
        self.input_device = QComboBox()
        self.input_device.addItems(self._get_input_devices())
        device_controls.addWidget(QLabel("Input:"))
        device_controls.addWidget(self.input_device)
        
        # Listen button and monitor
        self.listen_button = QPushButton("Listen")
        self.listen_button.setCheckable(True)
        self.listen_button.toggled.connect(self.toggle_listening)
        device_controls.addWidget(self.listen_button)
        
        self.audio_monitor = AudioMonitor()
        device_controls.addWidget(self.audio_monitor)
        
        # Level meter
        self.level_meter = QProgressBar()
        self.level_meter.setOrientation(Qt.Orientation.Horizontal)
        self.level_meter.setRange(0, 100)
        self.level_meter.setTextVisible(False)
        self.level_meter.setStyleSheet("""
            QProgressBar {
                border: 2px solid #2a2a2a;
                border-radius: 5px;
                background: #1a1a1a;
                height: 10px;
                min-width: 100px;
            }
            QProgressBar::chunk {
                background: #50c0ff;
                border-radius: 3px;
            }
        """)
        device_controls.addWidget(self.level_meter)
        
        self.layout.addLayout(device_controls)
        
        # Style for controls
        control_style = """
            QLabel {
                font-size: 18px;
                color: #ffffff;
            }
            QPushButton {
                font-size: 18px;
                padding: 10px;
                min-width: 120px;
                background-color: #2a2a2a;
                border-radius: 8px;
            }
            QPushButton:checked {
                background-color: #50c0ff;
            }
            QSpinBox {
                font-size: 18px;
                padding: 8px;
                min-width: 100px;
                background-color: #2a2a2a;
                border-radius: 6px;
            }
            QComboBox {
                font-size: 18px;
                padding: 8px;
                min-width: 150px;
                background-color: #2a2a2a;
                border-radius: 6px;
            }
        """
        
        # Add controls with new style
        for widget in self.findChildren((QPushButton, QSpinBox, QComboBox, QLabel)):
            widget.setStyleSheet(control_style)
        
        # Create tone controls
        tone_controls = QHBoxLayout()
        
        # Frequency control
        freq_label = QLabel("Tone Frequency (Hz):")
        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(200, 2000)
        self.freq_spin.setValue(800)
        self.freq_spin.valueChanged.connect(self.update_tone)
        tone_controls.addWidget(freq_label)
        tone_controls.addWidget(self.freq_spin)
        
        # Enable sound checkbox
        self.sound_enabled = QPushButton("Enable Sound")
        self.sound_enabled.setCheckable(True)
        tone_controls.addWidget(self.sound_enabled)
        
        self.layout.addLayout(tone_controls)
        
        # Create visualizer
        self.visualizer = MorseVisualizer()
        self.layout.addWidget(self.visualizer)
        
        # Create output display with possible interpretations
        output_layout = QHBoxLayout()
        
        # Main output
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        output_layout.addWidget(self.output, stretch=2)
        
        # Alternative interpretations
        self.alternatives = QTextEdit()
        self.alternatives.setReadOnly(True)
        self.alternatives.setPlaceholderText("Alternative interpretations...")
        output_layout.addWidget(self.alternatives, stretch=1)
        
        self.layout.addLayout(output_layout)
        
        # Adjust timing constants
        self.dot_max = 0.08      # 80ms max for dot
        self.dash_min = 0.06     # 60ms min for dash
        self.char_gap = 0.2      # 200ms between chars
        self.word_gap = 0.4      # 400ms between words
        
        # State
        self.key_down_time = None
        self.last_key_up_time = None
        self.current_char = []
        
        # Morse to text conversion
        self.morse_to_text = {v: k for k, v in MorseChart(None).morse_dict.items()}
        
        # Initialize tone generator
        self.tone = MorseTone(frequency=self.freq_spin.value())
        
        # Timer for showing alternatives
        self.alt_timer = QTimer()
        self.alt_timer.timeout.connect(self.show_alternatives)
        self.alt_timer.setInterval(200)  # Check every 200ms
        self.alt_timer.start()
        
        # Add input mode selection
        input_controls = QHBoxLayout()
        self.input_mode = QComboBox()
        self.input_mode.addItems(["Keyboard", "Microphone", "Audio Input"])
        self.input_mode.currentTextChanged.connect(self.change_input_mode)
        input_controls.addWidget(QLabel("Input Mode:"))
        input_controls.addWidget(self.input_mode)
        
        # Add threshold control for audio input
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(1, 100)
        self.threshold_spin.setValue(10)
        self.threshold_spin.valueChanged.connect(self.update_threshold)
        input_controls.addWidget(QLabel("Threshold:"))
        input_controls.addWidget(self.threshold_spin)
        
        # Add audio monitor and listen button to input controls
        self.audio_monitor = AudioMonitor()
        input_controls.addWidget(self.audio_monitor)
        
        self.listen_button = QPushButton("Listen")
        self.listen_button.setCheckable(True)
        self.listen_button.toggled.connect(self.toggle_listening)
        input_controls.addWidget(self.listen_button)
        
        # Add detection parameters
        self.detection_controls = QHBoxLayout()
        
        # Detection frequency range
        self.freq_range = QSpinBox()
        self.freq_range.setRange(10, 200)
        self.freq_range.setValue(50)
        self.freq_range.valueChanged.connect(self.update_detection)
        self.detection_controls.addWidget(QLabel("Freq Range (Hz):"))
        self.detection_controls.addWidget(self.freq_range)
        
        # Detection smoothing
        self.smoothing = QSpinBox()
        self.smoothing.setRange(1, 20)
        self.smoothing.setValue(5)
        self.smoothing.valueChanged.connect(self.update_detection)
        self.detection_controls.addWidget(QLabel("Smoothing:"))
        self.detection_controls.addWidget(self.smoothing)
        
        self.layout.insertLayout(0, input_controls)
        
        # Input mode state
        self.current_mode = "Keyboard"
        
        # Add practice section
        self.practice = MorsePractice()
        self.layout.addWidget(self.practice)
        
        # Add audio level meter
        self.level_meter = QProgressBar()
        self.level_meter.setOrientation(Qt.Orientation.Horizontal)
        self.level_meter.setRange(0, 100)
        self.level_meter.setTextVisible(False)
        self.level_meter.setStyleSheet("""
            QProgressBar {
                border: 2px solid #2a2a2a;
                border-radius: 5px;
                background: #1a1a1a;
                height: 10px;
            }
            QProgressBar::chunk {
                background: #50c0ff;
                border-radius: 3px;
            }
        """)
        input_controls.addWidget(self.level_meter)
        
        # Add timing display
        timing_layout = QHBoxLayout()
        self.timing_label = QLabel("Last: ")
        timing_layout.addWidget(self.timing_label)
        self.layout.addLayout(timing_layout)
        
        # Add current pattern display
        self.pattern_label = QLabel("Pattern: ")
        timing_layout.addWidget(self.pattern_label)
    
    def _get_input_devices(self):
        """Get list of available input devices."""
        devices = []
        try:
            for i in range(sd.query_devices()):
                device = sd.query_devices(i)
                if device['max_input_channels'] > 0:
                    name = f"{device['name']} ({i})"
                    devices.append(name)
        except:
            devices = ["Default"]
        return devices
    
    def _get_output_devices(self):
        """Get list of available output devices."""
        devices = []
        try:
            for i in range(sd.query_devices()):
                device = sd.query_devices(i)
                if device['max_output_channels'] > 0:
                    name = f"{device['name']} ({i})"
                    devices.append(name)
        except:
            devices = ["Default"]
        return devices
    
    def update_tone(self):
        """Update tone frequency."""
        if hasattr(self, 'tone'):
            self.tone.stop()
        self.tone = MorseTone(frequency=self.freq_spin.value())
    
    def show_alternatives(self):
        """Show possible interpretations of current input."""
        if not self.current_char:
            self.alternatives.clear()
            return
            
        morse_char = ''.join(self.current_char)
        possible = []
        
        # Check for similar patterns
        for code, char in self.morse_to_text.items():
            if code.startswith(morse_char) or morse_char.startswith(code):
                possible.append(f"{char}: {code}")
        
        self.alternatives.setText("\n".join(possible))
    
    def key_down(self):
        """Handle key press."""
        now = time.time()
        self.key_down_time = now
        
        # Check if this is a new character
        if (self.last_key_up_time and 
            now - self.last_key_up_time > self.char_gap):
            self.finish_character()
        
        # Play tone if enabled - don't decide dot/dash yet
        if self.sound_enabled.isChecked():
            self.tone.play(is_dot=True)  # Always start with dot tone
    
    def key_up(self):
        """Handle key release."""
        if not self.key_down_time:
            return
            
        now = time.time()
        duration = now - self.key_down_time
        
        # Stop current tone
        if self.sound_enabled.isChecked():
            self.tone.stop()
        
        # Determine if dot or dash
        is_dot = duration <= self.dot_max
        symbol = '.' if is_dot else '-'
        self.current_char.append(symbol)
        
        # Update displays
        self.timing_label.setText(f"Last: {duration:.3f}s ({symbol})")
        self.pattern_label.setText(f"Pattern: {''.join(self.current_char)}")
        
        # Visualize
        self.visualizer.add_signal(duration, is_dot)
        
        self.last_key_up_time = now
        self.key_down_time = None
        
        # Show possible matches
        self.show_alternatives()
    
    def finish_character(self):
        """Convert current signals to character."""
        if not self.current_char:
            return
            
        morse_char = ''.join(self.current_char)
        if morse_char in self.morse_to_text:
            char = self.morse_to_text[morse_char]
            self.output.insertPlainText(char)
            self.text_recognized.emit(char)
            print(f"Recognized: {morse_char} -> {char}")  # Debug output
        else:
            print(f"Unknown pattern: {morse_char}")  # Debug output
        
        self.current_char = []
        self.pattern_label.setText("Pattern: ")
        
        # Add word space if needed
        if (self.last_key_up_time and 
            time.time() - self.last_key_up_time > self.word_gap):
            self.output.insertPlainText(' ')
            self.text_recognized.emit(' ')
    
    def change_input_mode(self, mode):
        """Handle input mode change."""
        self.current_mode = mode
        if hasattr(self, 'tone'):
            self.tone.stop_listening()
            
        if mode in ["Microphone", "Audio Input"]:
            # Get selected device index
            device_name = self.input_device.currentText()
            device_idx = None
            if "(" in device_name and ")" in device_name:
                device_idx = int(device_name.split("(")[-1].strip(")"))
            
            def audio_callback(is_on):
                if is_on:
                    self.key_down()
                else:
                    self.key_up()
            
            if not self.tone.start_listening(audio_callback, device_idx, 
                                          self.update_audio_level):
                self.listen_button.setChecked(False)
    
    def update_threshold(self, value):
        """Update audio detection threshold."""
        if hasattr(self, 'tone'):
            self.tone.threshold = value / 1000  # Convert to float range
    
    def toggle_listening(self, enabled):
        """Toggle audio input listening."""
        if enabled:
            self.change_input_mode(self.input_mode.currentText())
            self.audio_monitor.set_active(True)
        else:
            if hasattr(self, 'tone'):
                self.tone.stop_listening()
            self.audio_monitor.set_active(False)
    
    def update_detection(self):
        """Update detection parameters."""
        if hasattr(self, 'tone'):
            self.tone.freq_range = self.freq_range.value()
            self.tone.smoothing = self.smoothing.value() / 10.0
    
    def update_audio_level(self, level):
        """Update audio level meter."""
        normalized = min(100, int(level * 5000))  # More sensitive scaling
        self.level_meter.setValue(normalized)
        self.audio_monitor.set_level(level)
        
        # Update activity indicator based on ratio to noise floor
        if hasattr(self, 'tone'):
            is_active = level > self.tone.noise_floor * 10
            self.audio_monitor.set_active(is_active)
            if is_active:
                self.level_meter.setStyleSheet("""
                    QProgressBar::chunk {
                        background: #50ff50;
                        border-radius: 3px;
                    }
                """)
            else:
                self.level_meter.setStyleSheet("""
                    QProgressBar::chunk {
                        background: #50c0ff;
                        border-radius: 3px;
                    }
                """)
    
    def cleanup(self):
        """Clean up resources."""
        if hasattr(self, 'tone'):
            self.tone.stop()
            self.tone.stop_listening() 