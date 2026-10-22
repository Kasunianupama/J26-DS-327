"""Offline CPU speech inference; download public model weights only via explicit CLI."""
import argparse
import importlib.util
import io
import json
import os
from functools import lru_cache
from pathlib import Path
from threading import Lock

MAX_AUDIO_BYTES = 6 * 1024 * 1024
MAX_SECONDS = 30
SAMPLE_RATE = 16000
LANGUAGES = ('en', 'si', 'ta')
MIME_TYPES = ('audio/webm', 'audio/ogg', 'audio/mp4', 'audio/wav', 'audio/x-wav')
_inference_lock = Lock()


class VoiceError(RuntimeError):
    """A safe, operator-readable voice failure without audio or private diagnostics."""


def model_directory():
    override = os.environ.get('C3_VOICE_MODEL_PATH')
    return Path(override).expanduser() if override else Path.home() / '.cache' / 'farmx-c3-speech' / 'base'


def voice_status():
    dependencies = importlib.util.find_spec('faster_whisper') is not None
    directory = model_directory()
    model_present = all((directory / name).is_file() for name in ('model.bin', 'config.json', 'tokenizer.json'))
    return dict(ready=dependencies and model_present, dependencies_available=dependencies,
                model_present=model_present, provider='local_whisper', cloud_processing=False,
                languages=list(LANGUAGES), max_seconds=MAX_SECONDS,
                message='Local speech files are available; first use loads the CPU model.' if dependencies and model_present
                else 'Local speech setup is incomplete. Install the C3 voice requirements and download its speech model.')


@lru_cache(maxsize=1)
def _load_model(directory):
    from faster_whisper import WhisperModel
    return WhisperModel(directory, device='cpu', compute_type='int8',
                        cpu_threads=min(4, os.cpu_count() or 2), num_workers=1,
                        local_files_only=True)


def decode_bounded_audio(payload):
    """Decode at most 30 seconds, retaining no audio files on disk."""
    import av
    import numpy as np
    parts, count = [], 0
    try:
        with av.open(io.BytesIO(payload), mode='r') as container:
            resampler = av.AudioResampler(format='s16', layout='mono', rate=SAMPLE_RATE)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples = converted.to_ndarray().reshape(-1)
                    count += samples.size
                    if count > MAX_SECONDS * SAMPLE_RATE:
                        raise VoiceError('Keep voice recordings within 30 seconds.')
                    parts.append(samples)
            for converted in resampler.resample(None):
                samples = converted.to_ndarray().reshape(-1)
                count += samples.size
                if count > MAX_SECONDS * SAMPLE_RATE:
                    raise VoiceError('Keep voice recordings within 30 seconds.')
                parts.append(samples)
        if count < SAMPLE_RATE // 4:
            raise VoiceError('The recording is too short. Please record a short question.')
        audio = np.concatenate(parts).astype(np.float32) / 32768.0
        if not np.isfinite(audio).all() or float(np.max(np.abs(audio))) < 0.0001:
            raise VoiceError('No audible speech was detected. Please try again.')
        return audio
    except VoiceError:
        raise
    except Exception:
        raise VoiceError('The audio recording could not be decoded. Try recording again.') from None


def transcribe_audio(payload, language, content_type):
    """Native English/Sinhala/Tamil ASR; user reviews the draft before sending."""
    if language not in LANGUAGES:
        raise VoiceError('Choose English, Sinhala or Tamil for speech input.')
    if content_type.split(';')[0].strip().lower() not in MIME_TYPES:
        raise VoiceError('This audio format is not supported.')
    if not payload or len(payload) > MAX_AUDIO_BYTES:
        raise VoiceError('Record a short question within the 6 MB limit.')
    if not voice_status()['ready']:
        raise VoiceError('Local speech setup is incomplete. Install the C3 voice requirements and download its speech model.')
    if not _inference_lock.acquire(blocking=False):
        raise VoiceError('Another recording is being processed. Please try again when it finishes.')
    try:
        audio = decode_bounded_audio(payload)
        model = _load_model(str(model_directory().resolve()))
        segments, _ = model.transcribe(audio, language=language,
            task='transcribe',
            beam_size=1, best_of=1, temperature=0.0, vad_filter=True,
            condition_on_previous_text=False, max_new_tokens=200)
        question = ' '.join(segment.text.strip() for segment in segments if segment.text.strip()).strip()
        if not question:
            raise VoiceError('No speech was recognised. Please try again.')
        if len(question) > 1500:
            raise VoiceError('The recognised question is too long. Please record a shorter question.')
        return dict(question_text=question, input_language=language, translated=False,
                    duration_seconds=round(len(audio) / SAMPLE_RATE, 2), model='whisper-base',
                    provider='local_whisper', cloud_processing=False)
    except VoiceError:
        raise
    except Exception:
        raise VoiceError('Local speech processing failed. Check the speech setup and try again.') from None
    finally:
        _inference_lock.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local C3 speech setup; never reads environment files or farm data.')
    parser.add_argument('--download-model', action='store_true', help='Explicitly download the public multilingual base speech weights once.')
    args = parser.parse_args(argv)
    if args.download_model:
        from faster_whisper.utils import download_model
        directory = model_directory()
        directory.mkdir(parents=True, exist_ok=True)
        download_model('base', output_dir=str(directory))
    print(json.dumps(voice_status()))


if __name__ == '__main__':
    main()
