"""
MIDI Keyboard Module - Enables using the keyboard as a MIDI input device.
"""

import logging
import threading
from typing import Dict, Optional, Set

import mido
import rtmidi
from PyQt6.QtCore import QObject, pyqtSignal, QRect, Qt
from PyQt6.QtGui import QPainter, QColor, QPen
from PyQt6.QtWidgets import QWidget, QVBoxLayout

logger = logging.getLogger(__name__)

class PianoKeyboard(QWidget):
    """Visual piano keyboard widget."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.active_notes = set()
        
        # Piano layout constants
        self.white_keys = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77]  # C D E F G A B C D E F
        self.black_keys = [61, 63, 66, 68, 70, 73, 75, 78]  # C# D# F# G# A# C# D# F#
        
        # Default note labels (Colemak layout)
        self.key_labels = {
            60: 'A',   # C4  (white)
            61: 'W',   # C#4 (black)
            62: 'R',   # D4  (white)
            63: 'F',   # D#4 (black)
            64: 'S',   # E4  (white)
            65: 'T',   # F4  (white)
            66: 'G',   # F#4 (black)
            67: 'D',   # G4  (white)
            68: 'J',   # G#4 (black)
            69: 'H',   # A4  (white)
            70: 'L',   # A#4 (black)
            71: 'N',   # B4  (white)
            72: 'E',   # C5  (white)
            73: 'U',   # C#5 (black)
            74: 'I',   # D5  (white)
            75: 'Y',   # D#5 (black)
            76: 'O',   # E5  (white)
            77: '\'',  # F5  (white)
            78: '[',   # F#5 (black)
        }
        
        # Note names for display
        self.note_names = {
            60: 'C4',
            61: 'C#4',
            62: 'D4',
            63: 'D#4',
            64: 'E4',
            65: 'F4',
            66: 'F#4',
            67: 'G4',
            68: 'G#4',
            69: 'A4',
            70: 'A#4',
            71: 'B4',
            72: 'C5',
            73: 'C#5',
            74: 'D5',
            75: 'D#5',
            76: 'E5',
            77: 'F5',
            78: 'F#5'
        }
        
        # Define key geometry
        self.white_key_width = 40
        self.black_key_width = 24
        self.white_key_height = 120
        self.black_key_height = 80
        
        # Colors
        self.white_key_color = QColor("#ffffff")
        self.black_key_color = QColor("#000000")
        self.active_white_key_color = QColor("#90ff90")
        self.active_black_key_color = QColor("#307030")
        self.border_color = QColor("#000000")
        self.label_color = QColor("#808080")
        self.active_label_color = QColor("#ffffff")
        self.note_name_color = QColor("#404040")
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Draw white keys first
        x = 0
        white_key_positions = {}  # Store positions for black key placement
        for note in self.white_keys:
            self.draw_white_key(painter, x, note)
            white_key_positions[note] = x
            x += self.white_key_width
        
        # Then draw black keys on top
        for note in self.black_keys:
            # Find position based on the white key before it
            base_note = note - 1
            if base_note in white_key_positions:
                x = white_key_positions[base_note] + self.white_key_width - self.black_key_width // 2
                self.draw_black_key(painter, x, note)
    
    def is_white_key(self, note):
        """Determine if a note is a white key."""
        return note in self.white_keys
    
    def draw_white_key(self, painter, x, note):
        """Draw a white piano key."""
        is_active = note in self.active_notes
        rect = QRect(x, 0, self.white_key_width, self.white_key_height)
        
        # Draw key background
        painter.fillRect(rect, self.active_white_key_color if is_active else self.white_key_color)
        
        # Draw border
        painter.setPen(QPen(self.border_color, 1))
        painter.drawRect(rect)
        
        # Draw key label if exists
        if note in self.key_labels:
            label_rect = QRect(x, rect.height() - 30, self.white_key_width, 25)
            painter.setPen(self.active_label_color if is_active else self.label_color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.key_labels[note])
        
        # Draw note name
        if note in self.note_names:
            name_rect = QRect(x, 5, self.white_key_width, 20)
            painter.setPen(self.note_name_color)
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, self.note_names[note])
    
    def draw_black_key(self, painter, x, note):
        """Draw a black piano key."""
        is_active = note in self.active_notes
        rect = QRect(x, 0, self.black_key_width, self.black_key_height)
        
        # Draw key background
        painter.fillRect(rect, self.active_black_key_color if is_active else self.black_key_color)
        
        # Draw border
        painter.setPen(QPen(self.border_color, 1))
        painter.drawRect(rect)
        
        # Draw key label if exists
        if note in self.key_labels:
            label_rect = QRect(x, rect.height() - 25, self.black_key_width, 20)
            painter.setPen(self.active_label_color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.key_labels[note])
        
        # Draw note name
        if note in self.note_names:
            name_rect = QRect(x, 5, self.black_key_width, 20)
            painter.setPen(self.active_label_color)
            painter.drawText(name_rect, Qt.AlignmentFlag.AlignCenter, self.note_names[note])

    def update_labels(self, new_labels: Dict[int, str]):
        """Update key labels from new mapping."""
        self.key_labels = new_labels
        self.update()  # Redraw with new labels

    def note_on(self, note: int):
        """Highlight a key when note is played."""
        self.active_notes.add(note)
        self.update()

    def note_off(self, note: int):
        """Un-highlight a key when note is released."""
        self.active_notes.discard(note)
        self.update()

class MIDIKeyboard(QObject):
    """Handles MIDI keyboard emulation functionality."""
    
    # Signals for UI feedback
    note_on = pyqtSignal(int, int)  # note, velocity
    note_off = pyqtSignal(int)  # note
    midi_error = pyqtSignal(str)  # error message
    
    def __init__(self):
        super().__init__()
        self.midi_out = None
        self.port_name = "Compyutinator:0"  # ALSA style port name
        self.base_octave = 4
        self.velocity = 100
        self.active_notes: Set[int] = set()
        self.sustain = False
        self.sustained_notes: Set[int] = set()
        
        # Create piano visualization
        self.piano_widget = PianoKeyboard()
        self.note_on.connect(self.piano_widget.note_on)
        self.note_off.connect(self.piano_widget.note_off)
        
        # Default key to MIDI note mapping (matching the piano keyboard labels)
        self.key_map: Dict[str, int] = {
            'a': 60,   # C4
            'w': 61,   # C#4
            'r': 62,   # D4
            'f': 63,   # D#4
            's': 64,   # E4
            't': 65,   # F4
            'g': 66,   # F#4
            'd': 67,   # G4
            'j': 68,   # G#4
            'h': 69,   # A4
            'l': 70,   # A#4
            'n': 71,   # B4
            'e': 72,   # C5
            'u': 73,   # C#5
            'i': 74,   # D5
            'y': 75,   # D#5
            'o': 76,   # E5
            '\'': 77,  # F5
            '[': 78,   # F#5
        }
        
        # Function key controls
        self.control_map = {
            'F1': self.decrease_octave,
            'F2': self.increase_octave,
            'F3': self.decrease_velocity,
            'F4': self.increase_velocity,
        }
        
        self._setup_midi()
    
    def _setup_midi(self):
        """Initialize MIDI output port."""
        try:
            available_ports = mido.get_output_names()
            logger.info(f"Available MIDI ports: {available_ports}")
            
            # First try to connect to PipeWire MIDI
            pipewire_ports = [p for p in available_ports if 'pipewire' in p.lower()]
            if pipewire_ports:
                self.midi_out = mido.open_output(pipewire_ports[0])
                logger.info(f"Connected to PipeWire MIDI port: {pipewire_ports[0]}")
            else:
                # Create virtual port with PipeWire-compatible name
                try:
                    logger.info("Creating virtual MIDI port...")
                    self.midi_out = mido.open_output(
                        'Compyutinator:midi_out',
                        virtual=True,
                        client_name='Compyutinator'
                    )
                    logger.info("Virtual MIDI port created successfully")
                    
                    # Try to automatically connect using pw-link
                    try:
                        import subprocess
                        logger.info("Attempting to connect using pw-link...")
                        
                        # First get a list of all nodes
                        logger.info("Running pw-cli list-nodes...")
                        nodes = subprocess.run(['pw-cli', 'list-nodes'], capture_output=True, text=True)
                        logger.info("=== PipeWire Nodes ===")
                        logger.info(nodes.stdout)
                        
                        # Then get all links
                        logger.info("Running pw-link -io...")
                        result = subprocess.run(['pw-link', '-io'], capture_output=True, text=True)
                        logger.info("=== PipeWire Links ===")
                        logger.info(result.stdout)
                        
                        # Also try listing just MIDI ports
                        logger.info("Running pw-link -m...")
                        midi_ports = subprocess.run(['pw-link', '-m'], capture_output=True, text=True)
                        logger.info("=== MIDI Ports ===")
                        logger.info(midi_ports.stdout)
                        
                        compyutinator_out = None
                        reaper_midi12_in = None
                        
                        for line in result.stdout.splitlines():
                            logger.info(f"Checking line: {line}")
                            
                            # Look for any line containing our keywords
                            if any(x in line for x in ['Compyutinator', 'MIDI', 'Reaper', 'capture', 'Midi-Bridge']):
                                logger.info(f"Found relevant port: {line}")
                                
                                # Look for Compyutinator output in Midi-Bridge
                                if 'Midi-Bridge' in line and 'Compyutinator' in line and ('capture' in line.lower() or 'out' in line.lower()):
                                    compyutinator_out = line.split()[0]
                                    logger.info(f"Found Compyutinator output: {line} -> {compyutinator_out}")
                                
                                # Look for Reaper MIDI Input 12
                                if any(x in line for x in ['REAPER', 'Reaper']) and any(x in line for x in ['MIDI Input 12', 'MIDI 12', 'midi12']):
                                    reaper_midi12_in = line.split()[0]
                                    logger.info(f"Found Reaper MIDI Input 12: {line} -> {reaper_midi12_in}")
                        
                        logger.info(f"Found Compyutinator out: {compyutinator_out}")
                        logger.info(f"Found Reaper MIDI Input 12: {reaper_midi12_in}")
                        
                        # Try to connect
                        if compyutinator_out and reaper_midi12_in:
                            try:
                                logger.info(f"Attempting connection: {compyutinator_out} -> {reaper_midi12_in}")
                                result = subprocess.run(
                                    ['pw-link', compyutinator_out, reaper_midi12_in], 
                                    check=True, 
                                    capture_output=True, 
                                    text=True
                                )
                                logger.info(f"Successfully connected: {compyutinator_out} -> {reaper_midi12_in}")
                                logger.info(f"Connection output: {result.stdout}")
                            except subprocess.CalledProcessError as e:
                                logger.warning(f"Failed to connect {compyutinator_out} -> {reaper_midi12_in}")
                                logger.warning(f"Error output: {e.output}")
                                logger.warning(f"Error stderr: {e.stderr}")
                                # Try running pw-link with -v for verbose output
                                try:
                                    verbose = subprocess.run(['pw-link', '-v', compyutinator_out, reaper_midi12_in], 
                                                      capture_output=True, text=True)
                                    logger.warning(f"Verbose connection attempt output: {verbose.stdout}")
                                    logger.warning(f"Verbose connection attempt error: {verbose.stderr}")
                                except:
                                    pass
                        else:
                            logger.warning("Could not find required ports")
                            if not compyutinator_out:
                                logger.warning("Missing Compyutinator output in Midi-Bridge")
                            if not reaper_midi12_in:
                                logger.warning("Missing Reaper MIDI Input 12")
                    except Exception as e:
                        logger.warning(f"Could not auto-connect: {e}")
                        logger.warning(f"Exception details: {str(e)}")
                        import traceback
                        logger.warning(f"Traceback: {traceback.format_exc()}")
                    
                except Exception as e:
                    error_msg = (
                        f"Could not create MIDI port. Error: {e}\n"
                        f"Available ports are:\n{available_ports}\n"
                        "Make sure you have PipeWire MIDI support:\n"
                        "sudo pacman -S pipewire-alsa pipewire-jack qjackctl"
                    )
                    raise RuntimeError(error_msg)
            
            # Send test message
            self.midi_out.send(mido.Message('note_on', note=60, velocity=1))
            self.midi_out.send(mido.Message('note_off', note=60, velocity=0))
            logger.info("Sent test MIDI message")
            
        except Exception as e:
            logger.error(f"Failed to setup MIDI: {e}")
            self.midi_error.emit(str(e))
    
    def key_press(self, key: str) -> bool:
        """Handle key press events."""
        if not self.midi_out:
            return False
            
        # Handle function key controls
        if key in self.control_map:
            self.control_map[key]()
            return True
            
        # Handle sustain
        if key == 'Control_L':
            self.sustain = True
            self._send_control_change(64, 127)  # Sustain pedal on
            return True
            
        # Handle note on
        if key in self.key_map:
            note = self.key_map[key] + ((self.base_octave - 4) * 12)
            if note not in self.active_notes:
                self._send_note_on(note)
            return True
            
        return False
    
    def key_release(self, key: str) -> bool:
        """Handle key release events."""
        if not self.midi_out:
            return False
            
        # Handle sustain release
        if key == 'Control_L':
            self.sustain = False
            self._send_control_change(64, 0)  # Sustain pedal off
            self._release_sustained_notes()
            return True
            
        # Handle note off
        if key in self.key_map:
            note = self.key_map[key] + ((self.base_octave - 4) * 12)
            if self.sustain:
                self.sustained_notes.add(note)
            else:
                self._send_note_off(note)
            return True
            
        return False
    
    def _send_note_on(self, note: int):
        """Send MIDI note on message."""
        try:
            self.midi_out.send(mido.Message('note_on', note=note, velocity=self.velocity))
            self.active_notes.add(note)
            self.note_on.emit(note, self.velocity)
            logger.debug(f"Note On: {note} velocity: {self.velocity}")
        except Exception as e:
            logger.error(f"Failed to send note on: {e}")
            self.midi_error.emit(str(e))
    
    def _send_note_off(self, note: int):
        """Send MIDI note off message."""
        try:
            self.midi_out.send(mido.Message('note_off', note=note, velocity=0))
            self.active_notes.discard(note)
            self.sustained_notes.discard(note)
            self.note_off.emit(note)
            logger.debug(f"Note Off: {note}")
        except Exception as e:
            logger.error(f"Failed to send note off: {e}")
            self.midi_error.emit(str(e))
    
    def _send_control_change(self, control: int, value: int):
        """Send MIDI control change message."""
        try:
            self.midi_out.send(mido.Message('control_change', control=control, value=value))
            logger.debug(f"Control Change: {control} value: {value}")
        except Exception as e:
            logger.error(f"Failed to send control change: {e}")
            self.midi_error.emit(str(e))
    
    def _release_sustained_notes(self):
        """Release all sustained notes."""
        for note in self.sustained_notes.copy():
            self._send_note_off(note)
    
    def increase_octave(self):
        """Increase the base octave."""
        if self.base_octave < 8:
            self.base_octave += 1
            logger.debug(f"Octave up: {self.base_octave}")
    
    def decrease_octave(self):
        """Decrease the base octave."""
        if self.base_octave > 0:
            self.base_octave -= 1
            logger.debug(f"Octave down: {self.base_octave}")
    
    def increase_velocity(self):
        """Increase the note velocity."""
        if self.velocity < 127:
            self.velocity = min(127, self.velocity + 10)
            logger.debug(f"Velocity up: {self.velocity}")
    
    def decrease_velocity(self):
        """Decrease the note velocity."""
        if self.velocity > 0:
            self.velocity = max(0, self.velocity - 10)
            logger.debug(f"Velocity down: {self.velocity}")
    
    def cleanup(self):
        """Clean up MIDI resources."""
        if self.midi_out:
            # Turn off any active notes
            for note in self.active_notes.copy():
                self._send_note_off(note)
            self.midi_out.close()
            logger.info("MIDI port closed")

    def update_key_map(self, new_map: Dict[str, int]):
        """Update key mappings and piano keyboard labels."""
        self.key_map = new_map
        # Update piano keyboard labels
        new_labels = {note: key.upper() for key, note in new_map.items()}
        self.piano_widget.update_labels(new_labels) 