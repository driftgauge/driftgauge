from pathlib import Path

__package__ = "app"
__path__ = [str(Path(__file__).resolve().with_name("app"))]

from .main import app
