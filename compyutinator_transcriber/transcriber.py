#!/usr/bin/env python3

import sys
import pyaudio
import json
import os
from pathlib import Path
from vosk import Model, KaldiRecognizer
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QLabel, 
                            QApplication, QTextEdit, QComboBox, QPushButton, QCheckBox, QSystemTrayIcon, QMenu, QHBoxLayout, QLineEdit)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtGui import QPainter, QTextCursor, QColor, QIcon
import numpy as np
import pyautogui
import time
from PyQt6 import QtCore  # Added missing import
from compyutinator_common import setup_qt_app
import asyncio
from compyutinator_transcriber.backends import VoskBackend, AssemblyAIBackend

try:
    import tkinter
except ImportError:
    print("Installing required dependencies...")
    import subprocess
    try:
        subprocess.run(['sudo', 'pacman', '-S', 'tk', '--noconfirm'], check=True)
        import tkinter
    except Exception as e:
        print(f"Error: Could not install tkinter. Please run: sudo pacman -S tk")

class AudioLevelWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0
        self.peak_level = 0
        self.peak_decay = 0.02  # Faster decay
        self.setMinimumHeight(20)
        self.setMaximumHeight(20)
        
        # Better calibration values
        self.min_threshold = 1    # Lower minimum threshold
        self.max_threshold = 100  # Upper threshold
        
        # Start update timer for smooth decay
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.decay_peak)
        self.update_timer.start(16)  # ~60fps update rate
    
    def decay_peak(self):
        """Decay peak level over time"""
        if self.peak_level > self.level:
            self.peak_level = max(self.level, self.peak_level - self.peak_decay)
            self.update()
    
    def setLevel(self, level):
        """Set current audio level and update peak."""
        # More responsive level handling
        self.level = min(100, max(0, level)) / 100.0
        if self.level > self.peak_level:
            self.peak_level = self.level
        self.update()
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw background
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        
        width = self.width()
        height = self.height()
        
        # Draw level markers
        marker_positions = [0.6, 0.8]  # 60% and 80% markers
        for pos in marker_positions:
            x = int(width * pos)
            painter.fillRect(x, 0, 1, height, QColor(64, 64, 64))
        
        # Draw level bar
        if self.level > 0:
            level_width = int(width * self.level)
            for x in range(level_width):
                ratio = x / width
                if ratio < 0.6:
                    color = QColor(0, 255, 0)
                elif ratio < 0.8:
                    color = QColor(255, 255, 0)
                else:
                    color = QColor(255, 0, 0)
                painter.fillRect(x, 0, 1, height, color)
        
        # Draw peak marker
        if self.peak_level > 0:
            peak_x = int(width * self.peak_level)
            painter.fillRect(peak_x - 1, 0, 2, height, QColor(255, 255, 255))

class RealTimeTranscriptionThread(QThread):
    transcription_update = pyqtSignal(str, bool)
    audio_level_update = pyqtSignal(int)
    audio_debug = pyqtSignal(str)  # New signal for debug info

    def __init__(self, model_path, backend="vosk", api_key=None, 
                 device_index=None, sample_rate=16000, 
                 channels=1, format=pyaudio.paFloat32, frames_per_buffer=1024):
        super().__init__()
        self.running = True
        self.paused = False
        self.device_index = device_index
        
        # Initialize backend
        if backend == "assemblyai" and api_key:
            self.backend = AssemblyAIBackend(api_key, sample_rate=sample_rate)
        else:
            self.backend = VoskBackend(model_path, sample_rate=sample_rate)
        
        # Audio setup
        self.format = format
        self.channels = 1
        self.frames_per_buffer = 2048
        self.device_rate = self._get_device_rate()
        
        # Buffer setup
        self.buffer_size = int(self.device_rate * 0.2)
        self.audio_buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.buffer_pos = 0
        
        # Create event loop for async operations
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
    
    def run(self):
        """Main processing loop."""
        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.format,
                channels=self.channels,
                rate=self.device_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.frames_per_buffer
            )
            
            while self.running:
                if not self.paused:
                    # Read and process audio
                    data = stream.read(self.frames_per_buffer, exception_on_overflow=False)
                    audio_data = np.frombuffer(data, dtype=np.float32)
                    
                    # Update level meter
                    level = np.max(np.abs(audio_data))
                    self.audio_level_update.emit(int(level * 100))
                    
                    # Process through backend
                    text, is_final = self.loop.run_until_complete(
                        self.backend.process_audio(audio_data)
                    )
                    
                    if text:
                        self.transcription_update.emit(text, is_final)
                
                self.msleep(10)
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            
        except Exception as e:
            print(f"Error in transcription thread: {e}")
            self.audio_debug.emit(f"Thread error: {e}")
        
        finally:
            self.backend.cleanup()

    def _get_device_rate(self):
        """Get the device's native sample rate."""
        p = pyaudio.PyAudio()
        device_info = p.get_device_info_by_index(self.device_index)
        rate = int(device_info.get('defaultSampleRate', 48000))
        p.terminate()
        return rate

class TranscriberWindow(QMainWindow):
    def __init__(self, model_path=None, assemblyai_key=None):
        super().__init__()
        if model_path is None:
            model_path = find_vosk_model()  # Use the direct function instead of model manager
        
        self.model_path = model_path
        
        # More advanced Vosk configuration
        self.model = Model(self.model_path)
        
        # Use a more configurable recognizer with better defaults
        self.recognizer = KaldiRecognizer(self.model, 48000)
        self.recognizer.SetWords(True)  # Enable word-level timestamps
        self.recognizer.SetPartialWords(True)  # Enable partial word recognition
        
        # Advanced filtering parameters
        self.min_words = 2  # Minimum words to consider a transcription valid
        self.max_silence_duration = 1.0  # Maximum silence before considering a phrase complete
        
        # Confidence and filtering
        self.confidence_threshold = 0.7  # Only accept transcriptions above this confidence
        
        # Initialization of tracking variables
        self.partial_buffer = ""
        self.last_final_text = ""
        self.last_transcription_time = time.time()
        
        self.setWindowTitle("Real-time Transcriber")
        
        # Create main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        
        # Create debug text area
        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)
        self.debug_text.setMaximumHeight(150)
        layout.addWidget(QLabel("Debug Output:"))
        layout.addWidget(self.debug_text)
        
        # Add audio level meter
        self.audio_level = AudioLevelWidget()
        layout.addWidget(QLabel("Audio Level:"))
        layout.addWidget(self.audio_level)
        
        # Add checkbox for toggling cursor typing
        self.cursor_typing_checkbox = QCheckBox("Type at cursor position")
        self.cursor_typing_checkbox.setChecked(True)
        self.cursor_typing_checkbox.stateChanged.connect(self.toggle_cursor_typing)
        layout.addWidget(self.cursor_typing_checkbox)
        
        # Create transcription text area
        self.transcription_text = QTextEdit()
        self.transcription_text.setReadOnly(True)
        layout.addWidget(QLabel("Transcription:"))
        layout.addWidget(self.transcription_text)
        
        # Create device selector
        self.device_selector = QComboBox()
        layout.addWidget(QLabel("Select Audio Input Device:"))
        layout.addWidget(self.device_selector)
        
        # Add backend selection
        backend_layout = QHBoxLayout()
        self.backend_selector = QComboBox()
        self.backend_selector.addItems(["Vosk", "AssemblyAI"])
        backend_layout.addWidget(QLabel("Backend:"))
        backend_layout.addWidget(self.backend_selector)
        
        # Add API key input for AssemblyAI
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("AssemblyAI API Key")
        self.api_key_input.setText(assemblyai_key or "")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        backend_layout.addWidget(self.api_key_input)
        
        layout.addLayout(backend_layout)
        
        # Create buttons
        self.transcribe_button = QPushButton("Start Transcription")
        self.transcribe_button.clicked.connect(self.toggle_transcription)
        layout.addWidget(self.transcribe_button)
        
        self.clear_button = QPushButton("Clear Debug Log")
        self.clear_button.clicked.connect(self.clear_debug_text)
        layout.addWidget(self.clear_button)
        
        self.setup_audio_devices()
        self.type_at_cursor = True  # Default to typing at cursor
        
        # Add a buffer to accumulate partial transcriptions
        self.transcription_buffer = ""
        self.last_typed_text = ""
        
        # Adjust typing parameters
        self.typing_threshold = 2  # Minimum words
        self.typing_cooldown = 0.5  # Seconds between typing
        self.last_type_time = 0

        # Connect device change signal
        self.device_selector.currentIndexChanged.connect(self.change_device)

        # Set window flags to stay active in background
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        # Add status bar
        self.statusBar().showMessage("Ready")
        
        # Store menus as instance variables
        self.tray_menu = QMenu()
        self.typing_menu = QMenu("Voice Typing")
        self.device_menu = QMenu("Input Device")
        
        # Transcription toggle
        self.toggle_action = self.tray_menu.addAction("Start Transcription")
        self.toggle_action.triggered.connect(self.toggle_transcription)
        
        self.tray_menu.addSeparator()
        
        # Voice typing menu
        self.typing_action = self.typing_menu.addAction("Type at Cursor")
        self.typing_action.setCheckable(True)
        self.typing_action.setChecked(self.type_at_cursor)
        self.typing_action.triggered.connect(self.toggle_cursor_typing)
        
        # Word threshold submenu
        self.threshold_menu = self.typing_menu.addMenu("Min Words")
        self.threshold_actions = {}
        for words in [1, 2, 3, 4, 5]:
            action = self.threshold_menu.addAction(str(words))
            action.setCheckable(True)
            action.setChecked(self.typing_threshold == words)
            action.triggered.connect(lambda checked, w=words: self.set_word_threshold(w))
            self.threshold_actions[words] = action
        
        # Cooldown submenu
        self.cooldown_menu = self.typing_menu.addMenu("Cooldown")
        self.cooldown_actions = {}
        for delay in [0.2, 0.5, 1.0, 1.5]:
            action = self.cooldown_menu.addAction(f"{delay}s")
            action.setCheckable(True)
            action.setChecked(self.typing_cooldown == delay)
            action.triggered.connect(lambda checked, d=delay: self.set_typing_cooldown(d))
            self.cooldown_actions[delay] = action
        
        self.tray_menu.addMenu(self.typing_menu)
        
        # Device menu
        self.device_actions = {}  # Store device actions
        self.update_device_menu()
        self.tray_menu.addMenu(self.device_menu)
        
        self.tray_menu.addSeparator()
        
        # Show/hide window
        self.show_action = self.tray_menu.addAction("Show Window")
        self.show_action.triggered.connect(self.toggle_window)
        
        self.tray_menu.addSeparator()
        
        # Quit action
        self.quit_action = self.tray_menu.addAction("Quit")
        self.quit_action.triggered.connect(self.close)
        
        # Set up tray icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
        self.tray_icon.setToolTip("Transcriber")
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        
        # Update menu state timer
        self.menu_update_timer = QTimer()
        self.menu_update_timer.timeout.connect(self.update_menu_state)
        self.menu_update_timer.start(1000)

    def toggle_cursor_typing(self, state):
        self.type_at_cursor = state == Qt.CheckState.Checked.value

    def setup_audio_devices(self):
        p = pyaudio.PyAudio()
        self.device_selector.clear()
        
        print("\nAvailable Audio Devices:")
        print("-" * 50)
        
        # Find Tascam device
        tascam_index = None
        default_device = None
        
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            print(f"\nDevice {i}: {device_info['name']}")
            print(f"Max Input Channels: {device_info.get('maxInputChannels', 'Unknown')}")
            print(f"Default Sample Rate: {device_info.get('defaultSampleRate', 'Unknown')}")
            print(f"Input Latency: {device_info.get('defaultLowInputLatency', 'Unknown')}")
            
            # Only add input devices with actual input channels
            if device_info['maxInputChannels'] > 0:
                device_name = device_info['name']
                self.device_selector.addItem(device_name, i)
                
                # Look for Tascam device - be more specific about input
                if ('tascam' in device_name.lower() or 'us-1x2' in device_name.lower()) and device_info['maxInputChannels'] > 0:
                    tascam_index = i
                    print(f"*** Found Tascam input device at index {i} ***")
                    print(f"Full device info: {device_info}")
                    
                # Also note the default device
                if device_info.get('isDefaultInputDevice', False):
                    default_device = i
                    print("*** Default Input Device ***")
        
        print("-" * 50)
        p.terminate()
        
        # Select Tascam if found, otherwise default device
        if tascam_index is not None:
            self.device_selector.setCurrentIndex(self.device_selector.findData(tascam_index))
            print(f"Selected Tascam device at index {tascam_index}")
        elif default_device is not None:
            self.device_selector.setCurrentIndex(self.device_selector.findData(default_device))
            print("Selected default device")

    def toggle_transcription(self):
        """Toggle transcription on/off."""
        try:
            if hasattr(self, 'transcription_thread') and self.transcription_thread and self.transcription_thread.running:
                self.stop_transcription()
            else:
                self.start_transcription()
        except Exception as e:
            print(f"Error toggling transcription: {e}")
            self.handle_audio_debug(f"Error: {e}")

    def start_transcription(self, device_index=None):
        """Start transcription with the selected device."""
        try:
            if device_index is None:
                device_index = self.device_selector.currentData()
            
            backend = self.backend_selector.currentText().lower()
            api_key = self.api_key_input.text() if backend == "assemblyai" else None
            
            self.transcription_thread = RealTimeTranscriptionThread(
                model_path=self.model_path,
                backend=backend,
                api_key=api_key,
                device_index=device_index
            )
            
            # Connect signals and start
            self.transcription_thread.audio_debug.connect(self.handle_audio_debug)
            self.transcription_thread.transcription_update.connect(self.update_transcription)
            self.transcription_thread.audio_level_update.connect(self.audio_level.setLevel)
            
            self.transcription_thread.start()
            self.transcribe_button.setText("Stop Transcription")
            
        except Exception as e:
            print(f"Error starting transcription: {e}")
            self.handle_audio_debug(f"Error: {e}")

    def stop_transcription(self):
        """Stop transcription and clean up resources."""
        if hasattr(self, 'transcription_thread') and self.transcription_thread:
            try:
                # Signal thread to stop
                self.transcription_thread.running = False
                
                # Give it a short time to stop naturally
                if not self.transcription_thread.wait(1000):  # Wait up to 1 second
                    # Force terminate if still running
                    self.transcription_thread.terminate()
                    self.transcription_thread.wait()
                
                # Clear the thread
                self.transcription_thread = None
                self.transcribe_button.setText("Start Transcription")
                self.handle_audio_debug("Transcription stopped")
                
            except Exception as e:
                print(f"Error stopping transcription: {e}")
                # Force cleanup
                if hasattr(self, 'transcription_thread'):
                    self.transcription_thread.terminate()
                    self.transcription_thread = None
                self.transcribe_button.setText("Start Transcription")

    def update_transcription(self, text, is_final):
        """Handle transcribed text."""
        current_time = time.time()
        
        # Update transcription text
        cursor = self.transcription_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        
        if is_final:
            # Only add if text is meaningful
            if len(text.split()) >= 1:
                cursor.insertText(text + "\n")
                self.statusBar().showMessage(f"Transcribed: {text}")
                
                # Type at cursor if enabled
                if (self.type_at_cursor and 
                    len(text.split()) >= self.typing_threshold and
                    text != self.last_typed_text and
                    current_time - self.last_type_time > self.typing_cooldown):
                    
                    try:
                        # Add space after text
                        pyautogui.write(text + " ")
                        self.last_typed_text = text
                        self.last_type_time = current_time
                    except Exception as e:
                        print(f"Typing error: {e}")
        else:
            # Show partial text in status bar
            if text.strip():
                self.statusBar().showMessage(f"Hearing: {text}")

    def clear_debug_text(self):
        self.debug_text.clear()

    def handle_audio_debug(self, message):
        #self.debug_text.append(message)
        #print(f"Audio Debug: {message}")
        pass

    def change_device(self):
        """Handle device change from dropdown."""
        try:
            # Stop current transcription if running
            if hasattr(self, 'transcription_thread') and self.transcription_thread:
                self.stop_transcription()
            
            # Start new thread with selected device
            device_index = self.device_selector.currentData()
            if device_index is not None:
                self.start_transcription(device_index)
        except Exception as e:
            print(f"Error changing device: {e}")
            self.handle_audio_debug(f"Error changing device: {e}")

    def close(self):
        """Clean up resources before closing."""
        self.stop_transcription()
        super().close()

    def update_device_menu(self):
        """Update the device selection menu."""
        self.device_menu.clear()
        self.device_actions.clear()
        
        p = pyaudio.PyAudio()
        current_device = self.device_selector.currentData()
        
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                action = self.device_menu.addAction(device_info['name'])
                action.setCheckable(True)
                action.setChecked(i == current_device)
                action.triggered.connect(lambda checked, idx=i: self.select_device(idx))
                self.device_actions[i] = action
        
        p.terminate()
    
    def select_device(self, device_index):
        """Handle device selection from tray menu."""
        self.device_selector.setCurrentIndex(
            self.device_selector.findData(device_index)
        )
    
    def set_word_threshold(self, words):
        """Set minimum word threshold for typing."""
        self.typing_threshold = words
        self.update_menu_state()
    
    def set_typing_cooldown(self, delay):
        """Set typing cooldown delay."""
        self.typing_cooldown = delay
        self.update_menu_state()
    
    def toggle_window(self):
        """Toggle window visibility."""
        if self.isVisible():
            self.hide()
            self.show_action.setText("Show Window")
        else:
            self.show()
            self.show_action.setText("Hide Window")
    
    def update_menu_state(self):
        """Update menu checkmarks and text."""
        try:
            # Update transcription toggle text
            is_running = hasattr(self, 'transcription_thread') and self.transcription_thread
            self.toggle_action.setText("Stop Transcription" if is_running else "Start Transcription")
            
            # Update typing action
            self.typing_action.setChecked(self.type_at_cursor)
            
            # Update threshold actions
            for words, action in self.threshold_actions.items():
                action.setChecked(self.typing_threshold == words)
            
            # Update cooldown actions
            for delay, action in self.cooldown_actions.items():
                action.setChecked(self.typing_cooldown == delay)
            
            # Update device selection
            current_device = self.device_selector.currentData()
            for idx, action in self.device_actions.items():
                action.setChecked(idx == current_device)
                
        except RuntimeError as e:
            print(f"Menu update error (can be ignored): {e}")

def find_vosk_model():
    """Find the Vosk model in common locations"""
    possible_paths = [
        # First check CompyutinatorCode's model if it exists
        str(Path(__file__).parent.parent.parent.parent / "CompyutinatorCode/src/vosk-model-small-en-us-0.15"),
        # Then check package bundled model
        str(Path(__file__).parent / "models/vosk-model-small-en-us-0.15"),
        # Then check user locations
        str(Path.home() / ".local/share/vosk/vosk-model-small-en-us-0.15"),
        # Then system locations
        "/usr/local/share/vosk/vosk-model-small-en-us-0.15",
        "/usr/share/vosk/vosk-model-small-en-us-0.15",
    ]
    
    print("Searching for Vosk model...")
    for path in possible_paths:
        if os.path.exists(path):
            print(f"Found model at: {path}")
            return path
            
    # If model not found, download it
    try:
        model_dir = Path.home() / ".local/share/vosk"
        model_dir.mkdir(parents=True, exist_ok=True)
        print("Downloading Vosk model...")
        import requests
        from tqdm import tqdm
        
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        response = requests.get(url, stream=True)
        total_size = int(response.headers.get('content-length', 0))
        
        zip_path = model_dir / "model.zip"
        with open(zip_path, 'wb') as f, tqdm(
            desc="Downloading",
            total=total_size,
            unit='iB',
            unit_scale=True,
            unit_divisor=1024,
        ) as pbar:
            for data in response.iter_content(chunk_size=1024):
                size = f.write(data)
                pbar.update(size)
        
        print("\nExtracting model...")
        import zipfile
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(model_dir)
        zip_path.unlink()
        
        model_path = str(model_dir / "vosk-model-small-en-us-0.15")
        print(f"Model installed at: {model_path}")
        return model_path
        
    except KeyboardInterrupt:
        print("\nDownload cancelled.")
        if zip_path.exists():
            zip_path.unlink()
        return None
    except Exception as e:
        print(f"\nError downloading model: {e}")
        if zip_path.exists():
            zip_path.unlink()
        return None

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Real-time Speech-to-Text Transcriber')
    
    default_model = find_vosk_model()
    parser.add_argument('--model', default=default_model,
                      help='Path to the Vosk model directory (default: auto-detect)')
    
    args = parser.parse_args()
    
    if args.model is None:
        print("Error: Could not find Vosk model. Please download it from https://alphacephei.com/vosk/models")
        print("and extract to ~/.local/share/vosk/ or specify path with --model")
        sys.exit(1)
    
    app = setup_qt_app()
    window = TranscriberWindow(model_path=args.model)
    window.resize(800, 600)
    window.show()
    
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
