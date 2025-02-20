"""Transcription backend implementations."""

from abc import ABC, abstractmethod
import json
import time
import websockets
import asyncio
from vosk import Model, KaldiRecognizer
import numpy as np
import assemblyai as aai

class TranscriptionBackend(ABC):
    """Abstract base class for transcription backends."""
    
    @abstractmethod
    async def process_audio(self, audio_data):
        """Process audio data and return transcription."""
        pass
    
    @abstractmethod
    def cleanup(self):
        """Clean up resources."""
        pass

class VoskBackend(TranscriptionBackend):
    """Vosk-based transcription backend."""
    
    def __init__(self, model_path, sample_rate=16000):
        self.model = Model(model_path)
        self.recognizer = KaldiRecognizer(self.model, sample_rate)
        self.recognizer.SetWords(True)
        
    async def process_audio(self, audio_data):
        """Process audio through Vosk."""
        # Convert float32 to int16
        audio_int16 = (audio_data * 32767).astype(np.int16).tobytes()
        
        if self.recognizer.AcceptWaveform(audio_int16):
            result = json.loads(self.recognizer.Result())
            return result.get('text', ''), True
        else:
            partial = json.loads(self.recognizer.PartialResult())
            return partial.get('partial', ''), False
    
    def cleanup(self):
        """Clean up Vosk resources."""
        pass  # Vosk doesn't need explicit cleanup

class AssemblyAIBackend(TranscriptionBackend):
    """AssemblyAI-based real-time transcription backend."""
    
    def __init__(self, api_key, sample_rate=16000):
        aai.settings.api_key = api_key
        
        self.current_text = ""
        self.is_final = False
        self.error = None
        self.connected = False
        self.transcriber = None
        
    def _create_transcriber(self):
        """Create a new transcriber instance."""
        if self.transcriber:
            try:
                self.cleanup()
            except:
                pass
        
        return aai.RealtimeTranscriber(
            sample_rate=self.sample_rate,
            on_data=self._on_data,
            on_error=self._on_error
        )
    
    def _on_data(self, transcript):
        """Handle incoming transcription data."""
        self.current_text = transcript.text
        self.is_final = transcript.is_final
    
    def _on_error(self, error):
        """Handle errors."""
        if "paid-only" in str(error):
            print("AssemblyAI error: This feature requires a paid account")
            self.error = "Paid account required"
        else:
            print(f"AssemblyAI error: {error}")
            self.error = error
        self.connected = False
    
    async def connect(self):
        """Start the transcription stream."""
        if self.connected:
            return
            
        try:
            # Create new transcriber for each connection
            self.transcriber = self._create_transcriber()
            await self.transcriber.connect()
            self.connected = True
        except Exception as e:
            if "paid-only" in str(e):
                print("AssemblyAI error: This feature requires a paid account")
                raise RuntimeError("AssemblyAI requires a paid account")
            print(f"AssemblyAI connection error: {e}")
            self.connected = False
            self.transcriber = None
            raise
    
    async def process_audio(self, audio_data):
        """Process audio through AssemblyAI real-time API."""
        if self.error == "Paid account required":
            return "", False
            
        try:
            if not self.connected:
                await self.connect()
            
            if not self.transcriber:
                return "", False
                
            # Convert and send audio data
            audio_bytes = (audio_data * 32767).astype(np.int16).tobytes()
            await self.transcriber.stream(audio_bytes)
            
            # Return current transcription state
            return self.current_text, self.is_final
            
        except Exception as e:
            if "paid-only" not in str(e):  # Don't spam paid account errors
                print(f"AssemblyAI error: {e}")
            self.connected = False
            return "", False
    
    def cleanup(self):
        """Clean up AssemblyAI resources."""
        if self.transcriber:
            try:
                asyncio.get_event_loop().run_until_complete(self.transcriber.close())
            except:
                pass
            finally:
                self.connected = False
                self.transcriber = None

class StreamingMP3Backend(TranscriptionBackend):
    """Streams audio to MP3 and uses AssemblyAI's file API instead of real-time."""
    
    def __init__(self, api_key, sample_rate=16000):
        import io
        import soundfile as sf
        import pydub
        
        aai.settings.api_key = api_key
        self.transcriber = aai.Transcriber()
        
        self.buffer = io.BytesIO()
        self.sample_rate = sample_rate
        self.accumulated_audio = []
        self.last_process_time = time.time()
        self.process_interval = 2.0  # Process every 2 seconds
        
    async def process_audio(self, audio_data):
        """Buffer audio and process in chunks."""
        try:
            # Accumulate audio data
            self.accumulated_audio.append(audio_data)
            
            current_time = time.time()
            if current_time - self.last_process_time < self.process_interval:
                return "", False
                
            # Convert accumulated audio to MP3
            self.buffer.seek(0)
            self.buffer.truncate()
            
            # Combine audio chunks
            combined = np.concatenate(self.accumulated_audio)
            
            # Save as WAV first (in memory)
            wav_buffer = io.BytesIO()
            sf.write(wav_buffer, combined, self.sample_rate, format='WAV')
            
            # Convert to MP3
            wav_buffer.seek(0)
            audio = pydub.AudioSegment.from_wav(wav_buffer)
            audio.export(self.buffer, format='mp3')
            
            # Get transcription
            self.buffer.seek(0)
            transcript = self.transcriber.transcribe(self.buffer)
            
            # Reset for next chunk
            self.accumulated_audio = []
            self.last_process_time = current_time
            
            return transcript.text, True
            
        except Exception as e:
            print(f"Streaming error: {e}")
            return "", False
    
    def cleanup(self):
        """Clean up resources."""
        self.buffer.close() 