import os

from backend.app import create_app

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
STORAGE_PATH = os.path.join(PROJECT_ROOT, "accounts.json")

app = create_app(STORAGE_PATH)