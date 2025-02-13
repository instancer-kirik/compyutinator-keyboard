#!/usr/bin/env python3

import sys
import pyaudio
import json
import os
from pathlib import Path
from vosk import Model, KaldiRecognizer
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QLabel, 
                            QApplication, QTextEdit, QComboBox, QPushButton, QCheckBox, QSystemTrayIcon, QMenu)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtGui import QPainter, QTextCursor, QColor, QIcon
import numpy as np
import pyautogui
import time
from PyQt6 import QtCore  # Added missing import
from compyutinator_common import setup_qt_app

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
        self.peak_decay = 0.05
        self.setMinimumHeight(20)
        self.setMaximumHeight(20)
        
        # Adjust calibration values for better sensitivity
        self.min_threshold = 50   # Lower minimum threshold
        self.max_threshold = 2000 # Lower maximum threshold
        
        # Start update timer for smooth decay
        self.update_timer = QtCore.QTimer(self)
        self.update_timer.timeout.connect(self.decay_peak)
        self.update_timer.start(50)  # Update every 50ms
    
    def decay_peak(self):
        """Decay peak level over time"""
        if self.peak_level > self.level:
            self.peak_level = max(self.level, self.peak_level - self.peak_decay)
            self.update()
    
    def setLevel(self, level):
        """Set current audio level and update peak."""
        # More sensitive normalization
        raw_level = max(0, level - self.min_threshold)
        normalized = min(1.0, (raw_level / (self.max_threshold - self.min_threshold)) ** 0.5)  # Square root for better low-level response
        self.level = normalized
        
        # Update peak level
        if normalized > self.peak_level:
            self.peak_level = normalized
        
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

    def __init__(self, model_path, device_index=None, sample_rate=16000, 
                 channels=1, format=pyaudio.paFloat32, frames_per_buffer=1024):
        super().__init__()
        self.model_path = model_path
        self.running = True
        self.paused = False
        self.device_index = device_index
        
        # Initialize Vosk model with better params
        self.model = Model(self.model_path)
        self.recognizer = KaldiRecognizer(self.model, 16000)
        self.recognizer.SetWords(True)  # Enable word timing
        self.recognizer.SetMaxAlternatives(1)  # Reduce alternatives for better accuracy
        
        # Audio setup
        self.format = format
        self.channels = channels
        self.frames_per_buffer = 2048  # Larger buffer for better recognition
        
        # Get device's native rate
        p = pyaudio.PyAudio()
        device_info = p.get_device_info_by_index(device_index)
        self.device_rate = int(device_info.get('defaultSampleRate', 48000))
        p.terminate()
        
        # Level calibration
        self.level_calibration = {'boost': 2.0}
        
        # Audio buffer with fixed size
        self.buffer_size = 8192  # Larger fixed buffer
        self.audio_buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.buffer_pos = 0
        
        # Transcription state
        self.last_text = ""
        self.silence_frames = 0
        self.min_silence_frames = 10  # Minimum silence frames before processing
        
    def _audio_callback(self, in_data, frame_count, time_info, status):
        """Handle incoming audio data."""
        if status:
            print(f"Stream status: {status}")
        
        if not self.paused:
            # Convert to numpy array
            audio_data = np.frombuffer(in_data, dtype=np.float32)
            
            # Calculate level and detect silence
            level = np.max(np.abs(audio_data))
            is_silence = level < 0.01
            
            if is_silence:
                self.silence_frames += 1
            else:
                self.silence_frames = 0
            
            # Update level meter
            self.audio_level_update.emit(int(level * 100))
            
            # Add to circular buffer
            samples_to_write = min(len(audio_data), self.buffer_size - self.buffer_pos)
            self.audio_buffer[self.buffer_pos:self.buffer_pos + samples_to_write] = \
                audio_data[:samples_to_write]
            self.buffer_pos = (self.buffer_pos + samples_to_write) % self.buffer_size
        
        return (None, pyaudio.paContinue)
    
    def run(self):
        """Main processing loop for audio transcription."""
        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.format,
                channels=self.channels,
                rate=self.device_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.frames_per_buffer,
                stream_callback=self._audio_callback
            )
            
            print(f"Started audio stream with: rate={self.device_rate}, channels={self.channels}")
            stream.start_stream()
            
            while self.running:
                # Process after silence or buffer full
                if self.silence_frames >= self.min_silence_frames or self.buffer_pos >= self.buffer_size - 1024:
                    # Get contiguous buffer
                    if self.buffer_pos > 0:
                        audio_data = np.concatenate([
                            self.audio_buffer[self.buffer_pos:],
                            self.audio_buffer[:self.buffer_pos]
                        ])
                    else:
                        audio_data = self.audio_buffer.copy()
                    
                    # Resample
                    resampled = self._resample(audio_data)
                    if resampled is not None:
                        # Convert to int16 for Vosk
                        vosk_data = (resampled * 32767).astype(np.int16).tobytes()
                        
                        if self.recognizer.AcceptWaveform(vosk_data):
                            result = json.loads(self.recognizer.Result())
                            text = result.get('text', '').strip()
                            if text and text != self.last_text:
                                self.transcription_update.emit(text, True)
                                self.last_text = text
                    
                    # Reset buffer
                    self.buffer_pos = 0
                    self.audio_buffer.fill(0)
                
                self.msleep(10)
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            
        except Exception as e:
            print(f"Error in transcription thread: {e}")
            self.audio_debug.emit(f"Thread error: {e}")

    def _resample(self, data):
        """Simple linear resampling."""
        if len(data) == 0:
            return None
            
        # Calculate resampling ratio
        ratio = 16000 / self.device_rate
        target_length = int(len(data) * ratio)
        
        # Create evenly spaced indices
        orig_indices = np.arange(len(data))
        new_indices = np.linspace(0, len(data) - 1, target_length)
        
        # Linear interpolation
        resampled = np.interp(new_indices, orig_indices, data)
        
        return resampled

    def cleanup(self):
        """Clean up audio resources."""
        try:
            if hasattr(self, 'stream') and self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            
            if hasattr(self, 'p') and self.p:
                self.p.terminate()
                self.p = None
                
        except Exception as e:
            self.audio_debug.emit(f"Cleanup error: {e}")

    def stop(self):
        """Stop the transcription thread."""
        self.running = False
        self.cleanup()

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

class TranscriberWindow(QMainWindow):
    def __init__(self, model_path=None):
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
        
        # Add system tray icon with enhanced menu
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon.fromTheme("audio-input-microphone"))
        self.tray_icon.setToolTip("Transcriber")
        
        # Create enhanced tray menu
        tray_menu = QMenu()
        
        # Transcription toggle
        self.toggle_action = tray_menu.addAction("Start Transcription")
        self.toggle_action.triggered.connect(self.toggle_transcription)
        
        tray_menu.addSeparator()
        
        # Voice typing submenu
        typing_menu = QMenu("Voice Typing")
        
        # Enable/disable voice typing
        self.typing_action = typing_menu.addAction("Type at Cursor")
        self.typing_action.setCheckable(True)
        self.typing_action.setChecked(self.type_at_cursor)
        self.typing_action.triggered.connect(self.toggle_cursor_typing)
        
        # Word threshold setting
        threshold_menu = typing_menu.addMenu("Min Words")
        for words in [1, 2, 3, 4, 5]:
            action = threshold_menu.addAction(str(words))
            action.setCheckable(True)
            action.setChecked(self.typing_threshold == words)
            action.triggered.connect(lambda checked, w=words: self.set_word_threshold(w))
        
        # Cooldown setting
        cooldown_menu = typing_menu.addMenu("Cooldown")
        for delay in [0.2, 0.5, 1.0, 1.5]:
            action = cooldown_menu.addAction(f"{delay}s")
            action.setCheckable(True)
            action.setChecked(self.typing_cooldown == delay)
            action.triggered.connect(lambda checked, d=delay: self.set_typing_cooldown(d))
        
        tray_menu.addMenu(typing_menu)
        
        # Device selection submenu
        device_menu = tray_menu.addMenu("Input Device")
        self.device_actions = {}  # Store device actions
        self.update_device_menu(device_menu)
        
        tray_menu.addSeparator()
        
        # Show/hide window
        self.show_action = tray_menu.addAction("Show Window")
        self.show_action.triggered.connect(self.toggle_window)
        
        tray_menu.addSeparator()
        
        # Quit action
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        # Update menu state timer
        self.menu_update_timer = QTimer()
        self.menu_update_timer.timeout.connect(self.update_menu_state)
        self.menu_update_timer.start(1000)  # Update every second

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
            
            # Get detailed device info
            p = pyaudio.PyAudio()
            device_info = p.get_device_info_by_index(device_index)
            print(f"\nStarting transcription with device: {device_info['name']}")
            
            # Force standard sample rate for better compatibility
            sample_rate = 16000  # Vosk works best with 16kHz
            channels = 1  # Force mono for speech recognition
            
            # Create and start new thread
            self.transcription_thread = RealTimeTranscriptionThread(
                self.model_path,
                device_index=device_index,
                sample_rate=sample_rate,
                channels=channels,
                format=pyaudio.paFloat32,
                frames_per_buffer=1024
            )
            
            # Connect signals
            self.transcription_thread.audio_debug.connect(self.handle_audio_debug)
            self.transcription_thread.transcription_update.connect(self.update_transcription)
            self.transcription_thread.audio_level_update.connect(self.audio_level.setLevel)
            
            # Start thread
            self.transcription_thread.start()
            self.transcribe_button.setText("Stop Transcription")
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error starting audio: {error_msg}")
            self.handle_audio_debug(f"Error: {error_msg}")
            self.transcription_thread = None
            self.transcribe_button.setText("Start Transcription")

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
            cursor.insertText(text + "\n")
            self.statusBar().showMessage(f"Transcribed: {text}")
            
            # Type at cursor if enabled and enough time has passed
            if (self.type_at_cursor and 
                len(text.split()) >= self.typing_threshold and
                text != self.last_typed_text and
                current_time - self.last_type_time > self.typing_cooldown):
                
                try:
                    pyautogui.write(text + " ")
                    self.last_typed_text = text
                    self.last_type_time = current_time
                except Exception as e:
                    print(f"Typing error: {e}")
        else:
            # Show partial text in status bar
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

    def update_device_menu(self, menu):
        """Update the device selection menu."""
        menu.clear()
        self.device_actions.clear()
        
        p = pyaudio.PyAudio()
        current_device = self.device_selector.currentData()
        
        for i in range(p.get_device_count()):
            device_info = p.get_device_info_by_index(i)
            if device_info['maxInputChannels'] > 0:
                action = menu.addAction(device_info['name'])
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
        # Update transcription toggle text
        is_running = hasattr(self, 'transcription_thread') and self.transcription_thread
        self.toggle_action.setText("Stop Transcription" if is_running else "Start Transcription")
        
        # Update typing action
        self.typing_action.setChecked(self.type_at_cursor)
        
        # Update device selection
        current_device = self.device_selector.currentData()
        for idx, action in self.device_actions.items():
            action.setChecked(idx == current_device)

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
