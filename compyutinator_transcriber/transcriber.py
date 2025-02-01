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

    def __init__(self, model_path, device_index=None, sample_rate=48000, 
                 channels=1, format=pyaudio.paFloat32, frames_per_buffer=1024):
        super().__init__()
        self.model_path = model_path
        self.running = True
        self.paused = False
        self.device_index = device_index
        
        # Use default Vosk configuration
        self.model = Model(self.model_path)
        self.recognizer = KaldiRecognizer(self.model, sample_rate)
        
        # Increase silence threshold to reduce false positives
        self.silence_threshold = 300
        
        # Audio configuration
        self.sample_rate = sample_rate
        self.channels = channels
        self.format = format
        self.frames_per_buffer = frames_per_buffer
        
        # Add a buffer to accumulate partial results
        self.partial_buffer = ""
        self.last_final_text = ""
        self.min_words = 2  # Minimum words to consider a transcription valid
        self.confidence_threshold = 0.7  # Only accept transcriptions above this confidence
        self.last_transcription_time = time.time()
        
        # Adjust calibration for better sensitivity
        self.level_calibration = {
            'min': 50,    # Lower minimum
            'max': 2000,  # Lower maximum
            'boost': 2.0  # Increase boost
        }
        
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

    def run(self):
        p = pyaudio.PyAudio()
        try:
            self.audio_debug.emit("Opening audio stream...")
            
            # Get device info for debugging
            device_info = p.get_device_info_by_index(self.device_index)
            self.audio_debug.emit(f"Using device: {device_info['name']}")
            self.audio_debug.emit(f"Max input channels: {device_info['maxInputChannels']}")
            
            stream = p.open(format=self.format,
                          channels=self.channels,
                          rate=self.sample_rate,
                          input=True,
                          input_device_index=self.device_index,
                          frames_per_buffer=self.frames_per_buffer)
            
            self.audio_debug.emit("Audio stream opened successfully")
            self.audio_debug.emit(f"Sample rate: {self.sample_rate}")
            self.audio_debug.emit(f"Channels: {self.channels}")
            self.audio_debug.emit(f"Buffer size: {self.frames_per_buffer}")

            while self.running:
                if not self.paused:
                    try:
                        data = stream.read(self.frames_per_buffer, exception_on_overflow=False)
                        # Convert to numpy array for level calculation
                        audio_data = np.frombuffer(data, dtype=np.float32 if self.format == pyaudio.paFloat32 else np.int16)
                        
                        # Calculate RMS with better scaling
                        audio_data = np.abs(audio_data)  # Use absolute values
                        rms = np.sqrt(np.mean(np.square(audio_data)))
                        
                        # Apply more aggressive scaling for float32
                        if self.format == pyaudio.paFloat32:
                            level = int(rms * 20000 * self.level_calibration['boost'])  # Increase scaling
                        else:
                            level = int(rms * self.level_calibration['boost'])
                        
                        # Clamp to range
                        level = max(self.level_calibration['min'], 
                                   min(level, self.level_calibration['max']))
                        
                        self.audio_level_update.emit(level)
                        
                        # Process audio for transcription
                        if self.format == pyaudio.paFloat32:
                            audio_data = (audio_data * 32768).astype(np.int16)
                        
                        if self.recognizer.AcceptWaveform(audio_data.tobytes()):
                            result = json.loads(self.recognizer.Result())
                            
                            # Advanced result processing
                            if result.get("text"):
                                clean_text = result["text"].strip()
                                words = clean_text.split()
                                
                                # Apply multiple filters
                                current_time = time.time()
                                time_since_last_transcription = current_time - self.last_transcription_time
                                
                                if (len(words) >= self.min_words and 
                                    clean_text != self.last_final_text and 
                                    time_since_last_transcription > 0.5):  # Prevent rapid repeated transcriptions
                                    
                                    # Optional: Add confidence check if available
                                    if 'result' in result and result['result']:
                                        confidence = sum(word.get('conf', 0) for word in result['result']) / len(result['result'])
                                        if confidence < self.confidence_threshold:
                                            continue
                                    
                                    self.transcription_update.emit(clean_text, True)
                                    self.last_final_text = clean_text
                                    self.last_transcription_time = current_time
                                    self.partial_buffer = ""
                        else:
                            partial = json.loads(self.recognizer.PartialResult())
                            
                            # Partial result handling
                            if partial.get("partial"):
                                clean_partial = partial["partial"].strip()
                                partial_words = clean_partial.split()
                                
                                if (len(partial_words) >= self.min_words and 
                                    clean_partial != self.partial_buffer):
                                    
                                    self.partial_buffer = clean_partial
                                    self.transcription_update.emit(clean_partial, False)
                    except Exception as e:
                        self.audio_debug.emit(f"Audio error: {e}")
                        time.sleep(0.1)  # Prevent tight loop on error

        except Exception as e:
            self.audio_debug.emit(f"Failed to open audio stream: {e}")
        finally:
            self.audio_debug.emit("Cleaning up audio resources...")
            if 'stream' in locals():
                stream.stop_stream()
                stream.close()
            if 'p' in locals():
                p.terminate()
            self.running = False
            self.audio_debug.emit("Audio resources cleaned up")

    def stop(self):
        self.running = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

class TranscriberWindow(QMainWindow):
    def __init__(self, model_path=None):
        super().__init__()
        if model_path is None:
            # Import the model manager we just created
            from vosk_model_manager import VoskModelManager
            model_path = VoskModelManager.get_model_path('medium')  # Default to medium model
        
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
        if not hasattr(self, 'transcription_thread') or not self.transcription_thread.running:
            self.start_transcription()
        else:
            self.stop_transcription()

    def start_transcription(self, device_index=None):
        try:
            if device_index is None:
                device_index = self.device_selector.currentData()
            
            # Get detailed device info
            p = pyaudio.PyAudio()
            device_info = p.get_device_info_by_index(device_index)
            print(f"\nStarting transcription with device: {device_info['name']}")
            
            # Configure for device-specific settings
            sample_rate = int(device_info.get('defaultSampleRate', 48000))
            channels = 1  # Force mono for better speech recognition
            
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
            
            # print(f"Started transcription thread with:")
            # print(f"- Sample rate: {sample_rate}")
            # print(f"- Channels: {channels}")
            # print(f"- Format: paFloat32")
            # print(f"- Buffer size: 1024")
            
            self.transcribe_button.setText("Stop Transcription")
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error starting audio: {error_msg}")
            self.handle_audio_debug(f"Error: {error_msg}")

    def stop_transcription(self):
        if hasattr(self, 'transcription_thread'):
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        
        self.transcribe_button.setText("Start Transcription")

    def update_transcription(self, text, is_final):
        current_time = time.time()
        
        # Update transcription text
        cursor = self.transcription_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text + "\n")
        
        # Accumulate text in buffer
        if is_final:
            self.transcription_buffer += text + " "
        
        # Type at cursor position in the active window
        if self.type_at_cursor:
            # Only type if we have enough words and haven't recently typed the same text
            words = self.transcription_buffer.strip().split()
            if (len(words) >= self.typing_threshold and 
                self.transcription_buffer.strip() != self.last_typed_text):
                
                try:
                    # Use pyautogui with a slight delay to improve reliability
                    pyautogui.write(self.transcription_buffer, interval=0.01)
                    pyautogui.press('space')
                    
                    # Update tracking variables
                    self.last_typed_text = self.transcription_buffer.strip()
                    self.transcription_buffer = ""  # Reset buffer
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
        if hasattr(self, 'transcription_thread'):
            # Stop current thread
            self.transcription_thread.running = False
            self.transcription_thread.wait()

        # Start new thread with selected device
        device_index = self.device_selector.currentData()
        self.start_transcription(device_index)

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
