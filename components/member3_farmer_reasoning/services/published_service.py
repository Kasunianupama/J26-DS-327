"""Load the local C3 aggregate briefing only on an explicit published-data request."""
import os
from pathlib import Path

from dotenv import dotenv_values

from .aggregate_brief import build_brief
from .aggregate_repository import read_context
from .data_readiness import connection_settings


def load_published_brief():
    """Keep secrets server-side and never substitute demo or teammate predictions."""
    root = Path(__file__).resolve().parents[3]
    settings = dict(dotenv_values(root / '.env', interpolate=False))
    settings.update(os.environ)
    return build_brief(read_context(connection_settings(settings)))
