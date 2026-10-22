"""Offline synthetic audio and mocked speech inference; no farm audio or databases."""
import io
import math
import sys
import wave
from array import array
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from components.member3_farmer_reasoning.services import local_voice as voice


@pytest.mark.parametrize('language,task', [('en','transcribe'),('si','transcribe'),('ta','transcribe')])
def test_language_tasks_stay_local_and_return_reviewable_native_draft(monkeypatch, language, task):
    monkeypatch.setattr(voice,'voice_status',lambda:dict(ready=True))
    monkeypatch.setattr(voice,'decode_bounded_audio',lambda data:[0.1]*16000)
    model=Mock()
    model.transcribe.return_value=([SimpleNamespace(text='Synthetic question only.')],SimpleNamespace())
    loader=Mock(return_value=model);monkeypatch.setattr(voice,'_load_model',loader)
    result=voice.transcribe_audio(b'synthetic-not-real-audio',language,'audio/webm;codecs=opus')
    assert result['question_text']=='Synthetic question only.'
    assert result['cloud_processing'] is False and result['provider']=='local_whisper'
    assert result['translated'] is False
    assert model.transcribe.call_args.kwargs['task']==task
    assert model.transcribe.call_args.kwargs['vad_filter'] is True
    assert model.transcribe.call_args.kwargs['condition_on_previous_text'] is False


@pytest.mark.parametrize('payload,language,mime', [(b'a','invalid','audio/webm'),(b'a','en','text/plain'),(b'','en','audio/webm'),(b'x'*(voice.MAX_AUDIO_BYTES+1),'en','audio/webm')], ids=['unsupported-language','unsupported-format','empty','oversized'])
def test_invalid_requests_do_not_decode_or_load_models(monkeypatch,payload,language,mime):
    decode=Mock();monkeypatch.setattr(voice,'decode_bounded_audio',decode)
    with pytest.raises(voice.VoiceError):voice.transcribe_audio(payload,language,mime)
    decode.assert_not_called()


def test_missing_setup_never_downloads_or_opens_audio(monkeypatch):
    monkeypatch.setattr(voice,'voice_status',lambda:dict(ready=False))
    decode=Mock();monkeypatch.setattr(voice,'decode_bounded_audio',decode)
    with pytest.raises(voice.VoiceError,match='setup is incomplete'):voice.transcribe_audio(b'a','en','audio/webm')
    decode.assert_not_called()


def test_busy_inference_is_bounded_without_queue_or_automatic_retry(monkeypatch):
    monkeypatch.setattr(voice,'voice_status',lambda:dict(ready=True))
    voice._inference_lock.acquire()
    try:
        with pytest.raises(voice.VoiceError,match='Another recording'):voice.transcribe_audio(b'a','en','audio/webm')
    finally:voice._inference_lock.release()


def test_model_failure_is_sanitized_and_releases_lock(monkeypatch):
    monkeypatch.setattr(voice,'voice_status',lambda:dict(ready=True))
    monkeypatch.setattr(voice,'decode_bounded_audio',lambda data:[0.1]*16000)
    monkeypatch.setattr(voice,'_load_model',Mock(side_effect=RuntimeError('private-diagnostic')))
    with pytest.raises(voice.VoiceError) as error:voice.transcribe_audio(b'a','en','audio/webm')
    assert 'private-diagnostic' not in str(error.value)
    assert voice._inference_lock.acquire(blocking=False)
    voice._inference_lock.release()


def test_loader_is_cpu_only_and_cannot_download(monkeypatch):
    factory=Mock();monkeypatch.setitem(sys.modules,'faster_whisper',SimpleNamespace(WhisperModel=factory))
    voice._load_model.cache_clear()
    try:
        voice._load_model('synthetic-model-directory')
        assert factory.call_args.kwargs['local_files_only'] is True
        assert factory.call_args.kwargs['device']=='cpu'
        assert factory.call_args.kwargs['compute_type']=='int8'
    finally:voice._load_model.cache_clear()


def synthetic_wave(seconds=1, silent=False):
    output=io.BytesIO()
    samples=array('h',(0 if silent else int(5000*math.sin(2*math.pi*440*i/16000)) for i in range(int(seconds*16000))))
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(samples.tobytes())
    return output.getvalue()


def test_bounded_decoder_accepts_synthetic_tone_and_rejects_silence_and_long_audio():
    pytest.importorskip('av')
    decoded=voice.decode_bounded_audio(synthetic_wave())
    assert len(decoded)==16000
    with pytest.raises(voice.VoiceError,match='audible speech'):voice.decode_bounded_audio(synthetic_wave(silent=True))
    with pytest.raises(voice.VoiceError,match='30 seconds'):voice.decode_bounded_audio(synthetic_wave(seconds=31))


def test_voice_api_uses_raw_audio_with_no_database_or_private_diagnostics(monkeypatch):
    from backend.app.api.routes import agent
    app=FastAPI();app.include_router(agent.router);client=TestClient(app)
    fake=Mock(return_value=dict(question_text='Synthetic test',provider='local_whisper',cloud_processing=False))
    monkeypatch.setattr(agent,'transcribe_audio',fake)
    response=client.post('/agent/voice/transcribe?language=si',content=b'synthetic-audio',headers={'Content-Type':'audio/webm'})
    assert response.status_code==200 and response.json()['cloud_processing'] is False
    assert fake.call_args.args==(b'synthetic-audio','si','audio/webm')
    fake.reset_mock()
    assert client.post('/agent/voice/transcribe',content=b'x'*(voice.MAX_AUDIO_BYTES+1)).status_code==413
    fake.assert_not_called()
    fake.side_effect=voice.VoiceError('Safe setup message')
    assert client.post('/agent/voice/transcribe',content=b'a').json()['detail']=='Safe setup message'
