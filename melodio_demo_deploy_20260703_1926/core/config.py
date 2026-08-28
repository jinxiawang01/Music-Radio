from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

IS_VERCEL = os.getenv("VERCEL", "").strip().lower() in {"1", "true"}
RUNTIME_WRITE_DIR = Path(os.getenv("MELODIO_RUNTIME_DIR", "/tmp/melodio_demo" if IS_VERCEL else str(BASE_DIR)))
RUNTIME_WRITE_DIR.mkdir(parents=True, exist_ok=True)


def load_text_prompt(relative_path: str) -> str:
    return (BASE_DIR / relative_path).read_text(encoding="utf-8").strip()
