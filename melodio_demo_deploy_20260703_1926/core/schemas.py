from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RecommendReq(BaseModel):
    query: str
    n: int = 15
    provider: str = "local"
    context: Any = None


class RadioContinueReq(BaseModel):
    query: str = ""
    n: int = 5
    provider: str = "local"
    analysis: Any = None
    groups: Any = None
    context: Any = None
    exclude: list[dict[str, str]] = []


class PlayerReq(BaseModel):
    title: str
    artist: str = ""


class StreamReq(BaseModel):
    songs: list[dict[str, str]]
    offset: int = 0


class DjTtsReq(BaseModel):
    dj: Any = None


class DjBuildReq(BaseModel):
    query: str
    provider: str = "local"
    analysis: Any = None
    groups: Any = None
    answer: str = ""
    context: Any = None


class TtsPreviewReq(BaseModel):
    provider: str = "doubao"
    text: str
    voice_id: str = ""
    speaker: str = ""


class AsrReq(BaseModel):
    audio_base64: str
    mime_type: str = "audio/webm"
