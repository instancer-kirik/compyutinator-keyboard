# Compyutinator Keyboard

A comprehensive keyboard configuration and management tool with voice transcription support and MIDI keyboard emulation for Linux systems.

## Features

- KMonad configuration management through a user-friendly GUI
- Voice transcription support using Vosk
- System-wide keyboard layout customization
- MIDI keyboard emulation for DAW integration
- Automatic setup of required system permissions
- Desktop integration

## Requirements

- Python 3.10 or higher
- KMonad installed and accessible in PATH
- Linux system with X11
- Input and uinput kernel modules
- Working microphone (for transcription features)
- ALSA and JACK for MIDI support

## Installation

### System Dependencies

For Arch Linux:
```bash
sudo pacman -S jack2 alsa-utils
```

For Ubuntu/Debian:
```bash
sudo apt install jackd2 libjack-dev libasound2-dev
```

### From PyPI

```bash
pip install compyutinator-keyboard
```

### From Source

1. Clone the repository:
```bash
git clone https://github.com/instancer-kirik/compyutinator-keyboard
cd compyutinator-keyboard
```

2. Install with uv:
```bash
uv venv
source .venv/bin/activate
uv pip install -e .
```

## First Time Setup

On first run, the application will guide you through:
1. Setting up required system permissions
2. Loading necessary kernel modules
3. Configuring user groups
4. Setting up udev rules
5. Configuring MIDI ports

You may need to log out and back in for group changes to take effect.

## Usage

### Keyboard Manager
```bash
compyutinator-keyboard
```

### Voice Transcription
```bash
compyutinator-transcriber
```

### MIDI Keyboard Mode

The keyboard can be used as a MIDI input device for DAWs like Reaper. In this mode:

- Regular keyboard keys are mapped to MIDI notes
- Function keys (F1-F12) control octave and velocity
- Modifier keys (Shift, Ctrl, Alt) can be used for sustain and modulation
- Custom MIDI mappings can be configured through the GUI

To use with Reaper:
1. Start JACK audio server
2. Launch compyutinator-keyboard
3. Enable MIDI mode in the settings
4. In Reaper, select "compyutinator" as a MIDI input device
5. Create a new track and arm it for recording

## Development

1. Install development dependencies:
```bash
uv pip install ruff pytest pytest-qt
```

2. Run tests:
```bash
pytest
```

3. Check code style:
```bash
ruff check .
```

## License

This project is licensed under the GNU General Public License v3 or later (GPLv3+).
See the LICENSE file for details. 