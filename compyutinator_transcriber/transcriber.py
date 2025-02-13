#!/usr/bin/env python3

import sys
import pyaudio
import json
import os
from pathlib import Path
from vosk import Model, KaldiRecognizer
from PyQt6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QLabel, 
                            QApplication, QTextEdit, QComboBox, QPushButton, QCheckBox)
from PyQt6.QtCore import pyqtSignal, QThread, Qt, QTimer
from PyQt6.QtGui import QPainter, QTextCursor, QColor
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
        
        # Get device's native rate
        p = pyaudio.PyAudio()
        device_info = p.get_device_info_by_index(device_index)
        self.device_rate = int(device_info.get('defaultSampleRate', 48000))
        p.terminate()
        
        # Use device's native rate for capture
        self.sample_rate = self.device_rate
        self.channels = channels
        self.format = format
        self.frames_per_buffer = frames_per_buffer
        
        # Initialize Vosk model
        self.model = Model(self.model_path)
        self.recognizer = KaldiRecognizer(self.model, 16000)  # Vosk always uses 16kHz
        
        # Initialize resampling buffer with fixed size
        self.buffer_size = 8192  # Fixed buffer size
        self.resample_buffer = np.zeros(self.buffer_size, dtype=np.float32)
        self.buffer_pos = 0
        
        # Level calibration
        self.level_calibration = {'boost': 2.0}
        
        # Calibrate based on device type
        if device_index is not None:
            p = pyaudio.PyAudio()
            info = p.get_device_info_by_index(device_index)
            name = info['name'].lower()
            
            if 'tascam' in name:
                self.level_calibration.update({
                    'min': 25,
                    'max': 1500,
                    'boost': 2.5
                })
            elif 'built-in' in name or 'internal' in name:
                self.level_calibration.update({
                    'min': 100,
                    'max': 4000,
                    'boost': 3.0
                })
            p.terminate()

    def resample(self, audio_data):
        """Resample audio data to 16kHz using fixed buffer."""
        if self.device_rate == 16000:
            return audio_data
            
        # Calculate resampling ratio
        ratio = 16000 / self.device_rate
        
        # Add new data to buffer
        samples_to_add = min(len(audio_data), self.buffer_size - self.buffer_pos)
        self.resample_buffer[self.buffer_pos:self.buffer_pos + samples_to_add] = audio_data[:samples_to_add]
        self.buffer_pos += samples_to_add
        
        # Check if we have enough data
        min_samples = int(512 / ratio)  # Minimum samples needed for output
        if self.buffer_pos < min_samples:
            return None
        
        # Calculate output size
        output_size = int(self.buffer_pos * ratio)
        
        # Resample using linear interpolation
        x = np.linspace(0, self.buffer_pos - 1, output_size)
        resampled = np.interp(x, np.arange(self.buffer_pos), self.resample_buffer[:self.buffer_pos])
        
        # Keep remaining samples
        remaining = self.buffer_pos - min_samples
        if remaining > 0:
            self.resample_buffer[:remaining] = self.resample_buffer[min_samples:self.buffer_pos]
        self.buffer_pos = remaining
        
        return resampled.astype(np.float32)
    
    def run(self):
        """Main processing loop for audio transcription."""
        try:
            p = pyaudio.PyAudio()
            stream = p.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                input_device_index=self.device_index,
                frames_per_buffer=self.frames_per_buffer
            )
            
            print(f"Started audio stream with: rate={self.sample_rate}, channels={self.channels}")
            stream.start_stream()
            
            while self.running:
                if not self.paused:
                    try:
                        # Read and convert audio
                        data = stream.read(self.frames_per_buffer, exception_on_overflow=False)
                        audio_data = np.frombuffer(data, dtype=np.float32)
                        
                        # Update level meter
                        level = np.max(np.abs(audio_data)) * self.level_calibration['boost']
                        self.audio_level_update.emit(int(level * 100))
                        
                        # Resample to 16kHz
                        resampled = self.resample(audio_data)
                        if resampled is not None:
                            # Convert to int16 for Vosk
                            vosk_data = (resampled * 32767).astype(np.int16).tobytes()
                            
                            if self.recognizer.AcceptWaveform(vosk_data):
                                result = json.loads(self.recognizer.Result())
                                if result.get('text'):
                                    self.transcription_update.emit(result['text'], True)
                            else:
                                partial = json.loads(self.recognizer.PartialResult())
                                if partial.get('partial'):
                                    self.transcription_update.emit(partial['partial'], False)
                                    
                    except Exception as e:
                        print(f"Error processing audio: {e}")
                        self.audio_debug.emit(f"Processing error: {e}")
            
            stream.stop_stream()
            stream.close()
            p.terminate()
            
        except Exception as e:
            print(f"Error in transcription thread: {e}")
            self.audio_debug.emit(f"Thread error: {e}")
            
        finally:
            self.running = False

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
        self.typing_threshold = 3  # Minimum words before typing
        self.typing_interval = 0.5  # Minimum time between typing actions

        # Connect device change signal
        self.device_selector.currentIndexChanged.connect(self.change_device)

        # Set window flags to stay active in background
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

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
        cursor.insertText(text + "\n")
        
        # Type at cursor position in the active window
        if self.type_at_cursor:
            # Only type if we have enough words and haven't recently typed the same text
            words = text.strip().split()
            if (len(words) >= self.typing_threshold and 
                text.strip() != self.last_typed_text):
                
                try:
                    # Store current focus
                    current_focus = QApplication.focusWidget()
                    
                    # Type the text
                    pyautogui.write(text, interval=0.01)
                    pyautogui.press('space')
                    
                    # Update tracking variables
                    self.last_typed_text = text.strip()
                    
                    # Restore focus if needed
                    if current_focus:
                        current_focus.setFocus()
                        
                except Exception as e:
                    print(f"Typing error: {e}")
        
        # Periodically clear very long buffers to prevent memory issues
        if len(self.transcription_buffer) > 1000:
            self.transcription_buffer = self.transcription_buffer[-500:]

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
