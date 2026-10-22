"""Bounded loopback-only Ollama transport and metadata/interpretation diagnostics."""
import argparse
import json
from threading import Lock
from time import monotonic

import httpx

MODEL = 'qwen3:4b-instruct'
BASE_URL = 'http://127.0.0.1:11434'
READ_TIMEOUT = 20
_inference = Lock()


class OllamaFailure(RuntimeError):
    """Public category only; never expose raw runtime diagnostics or user text."""
    def __init__(self, category):
        self.category = category
        super().__init__('Local interpretation ' + category)


def request_json(method, path, *, payload=None, timeout=READ_TIMEOUT, limit=65536):
    """Only fixed internal paths; no proxies, redirects, retries or arbitrary URLs."""
    if (method, path) not in {('GET', '/api/version'), ('GET', '/api/tags'), ('POST', '/api/chat')}:
        raise ValueError('Unsupported local runtime operation')
    started = monotonic()
    try:
        with httpx.Client(trust_env=False, follow_redirects=False,
                          timeout=httpx.Timeout(timeout, connect=2, pool=1)) as client:
            with client.stream(method, BASE_URL + path, json=payload) as result:
                if result.status_code == 404 and path == '/api/chat':
                    raise OllamaFailure('model_missing')
                if result.status_code != 200:
                    raise OllamaFailure('unavailable')
                content = bytearray()
                for chunk in result.iter_bytes():
                    if monotonic() - started > timeout + 2:
                        raise OllamaFailure('timeout')
                    if len(content) + len(chunk) > limit:
                        raise OllamaFailure('invalid_response')
                    content.extend(chunk)
        body = json.loads(content)
        if not isinstance(body, dict):
            raise OllamaFailure('invalid_response')
        return body
    except OllamaFailure:
        raise
    except httpx.TimeoutException:
        raise OllamaFailure('timeout') from None
    except (httpx.HTTPError, OSError):
        raise OllamaFailure('unavailable') from None
    except (ValueError, UnicodeError):
        raise OllamaFailure('invalid_response') from None


def classify(payload, *, timeout=READ_TIMEOUT):
    """At most one C3 inference per process; busy requests never wait in a queue."""
    if timeout not in (READ_TIMEOUT, 30):
        raise ValueError('Unsupported local inference budget')
    if not _inference.acquire(blocking=False):
        raise OllamaFailure('busy')
    try:
        return request_json('POST', '/api/chat', payload=payload, timeout=timeout)
    finally:
        _inference.release()


def readiness():
    """Metadata only: does not load a model, read settings or open a database."""
    try:
        version = request_json('GET', '/api/version', timeout=3).get('version')
        models = request_json('GET', '/api/tags', timeout=3, limit=1048576).get('models')
        if not isinstance(version, str) or len(version) > 64 or not isinstance(models, list):
            raise OllamaFailure('invalid_response')
        installed = any(isinstance(item, dict) and item.get('name') == MODEL for item in models)
        return dict(status='ready' if installed else 'model_missing', version=version,
                    model=MODEL, model_installed=installed, cloud_processing=False)
    except OllamaFailure as exc:
        return dict(status=exc.category, model=MODEL, cloud_processing=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Local Ollama check; no .env or database access.')
    parser.add_argument('--check', choices=['en', 'si', 'ta'],
                        help='Classify one fixed diagnostic phrase; sends no farm evidence.')
    args = parser.parse_args(argv)
    result = readiness()
    if args.check and result['status'] == 'ready':
        from .language_interpreter import qwen_plan
        phrases = dict(en='Show the recorded herd summary.',
                       si='වාර්තාගත රංචු සාරාංශය පෙන්වන්න.',
                       ta='பதிவுசெய்யப்பட்ட மந்தைச் சுருக்கத்தைக் காட்டுங்கள்.')
        started = monotonic()
        try:
            plan = qwen_plan(phrases[args.check])
            matches = plan.topic == 'herd' and plan.guard == 'historical'
            result.update(check=args.check, interpretation_status='passed' if matches else 'mismatch',
                          selected_topic=plan.topic, selected_guard=plan.guard)
        except OllamaFailure as exc:
            result.update(check=args.check, interpretation_status=exc.category)
        result['seconds'] = round(monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result['status'] == 'ready' and result.get('interpretation_status', 'passed') == 'passed' else 1


if __name__ == '__main__':
    # Use the canonical module so CLI and interpreter share exceptions and lock.
    from .local_ollama import main as entrypoint
    raise SystemExit(entrypoint())
