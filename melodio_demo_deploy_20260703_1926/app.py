from __future__ import annotations

import base64
import binascii
import asyncio
import gzip
import hashlib
import json
import logging
import os
import random
import re
import secrets
import struct
import subprocess
import traceback
import time
import uuid
from asyncio import create_task, get_running_loop
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen

from fastapi import FastAPI, Request as FastAPIRequest, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI

from core.asr_protocol import (
    ASR_AUDIO_ONLY_REQUEST,
    ASR_FULL_CLIENT_REQUEST,
    ASR_GZIP,
    ASR_HEADER_SIZE,
    ASR_JSON_SERIALIZATION,
    ASR_NEG_SEQUENCE,
    ASR_NO_SERIALIZATION,
    ASR_POS_SEQUENCE,
    ASR_PROTOCOL_VERSION,
    ASR_SERVER_ERROR_RESPONSE,
)
from core.config import BASE_DIR, RUNTIME_WRITE_DIR, load_text_prompt
from core.schemas import (
    AsrReq,
    DjBuildReq,
    DjTtsReq,
    PlayerReq,
    RadioContinueReq,
    RecommendReq,
    StreamReq,
    TtsPreviewReq,
)

logger = logging.getLogger("melodio_demo")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


CORS_ALLOW_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",")
    if origin.strip()
]
DEMO_BASIC_AUTH_USER = os.getenv("DEMO_BASIC_AUTH_USER", "").strip()
DEMO_BASIC_AUTH_PASSWORD = os.getenv("DEMO_BASIC_AUTH_PASSWORD", "").strip()

app = FastAPI(title="Melodio Demo Clone")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


PROVIDERS: dict[str, dict[str, str | None]] = {
    "gemini": {
        "label": "Gemini Flash",
        "base_url": os.getenv("GEMINI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://generativelanguage.googleapis.com/v1beta/openai/",
        "model": os.getenv("GEMINI_MODEL") or os.getenv("OPENAI_MODEL") or "gemini-3.5-flash",
        "key": os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY"),
    },
    "deepseek": {
        "label": "DeepSeek Chat",
        "base_url": os.getenv("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
        "model": os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash",
        "key": os.getenv("DEEPSEEK_API_KEY"),
    },
    "doubao": {
        "label": "豆包 Doubao",
        "base_url": os.getenv("DOUBAO_BASE_URL") or "https://ark.cn-beijing.volces.com/api/v3",
        "model": os.getenv("DOUBAO_MODEL") or "doubao-pro-32k",
        "key": os.getenv("DOUBAO_API_KEY") or os.getenv("ARK_API_KEY"),
    },
}
DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "local")
_clients: dict[str, AsyncOpenAI] = {}
_online_cache: dict[tuple[str, str, int, str], tuple[float, dict[str, Any]]] = {}
_player_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_apple_music_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_stream_probe_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}
_spotify_token_cache: tuple[str, float] | None = None
_jobs: dict[str, dict[str, Any]] = {}
CACHE_TTL_SECONDS = 600
PLAYER_CACHE_TTL_SECONDS = 86400
APPLE_MUSIC_CACHE_TTL_SECONDS = 86400
PLAYER_CACHE_VERSION = "autoplay-v1"
STREAM_PROBE_TTL_SECONDS = 3600
STREAM_PROBE_MAX_WORKERS = max(1, int(os.getenv("STREAM_PROBE_MAX_WORKERS", "4") or 4))
STREAM_PROBE_CANDIDATE_LIMIT = max(5, int(os.getenv("STREAM_PROBE_CANDIDATE_LIMIT", "12") or 12))
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
MUSIC_PROVIDER = os.getenv("MUSIC_PROVIDER", "apple").strip().lower()
STATE_DIR = RUNTIME_WRITE_DIR / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
NETEASE_COOKIE_FILE = STATE_DIR / "netease_cookie.txt"
ENV_FILE = BASE_DIR / ".env"
NETEASE_COOKIE = os.getenv("NETEASE_COOKIE", "").strip()
if not NETEASE_COOKIE and NETEASE_COOKIE_FILE.exists():
    NETEASE_COOKIE = NETEASE_COOKIE_FILE.read_text(encoding="utf-8").strip()
NETEASE_API_URL = os.getenv("NETEASE_API_URL", "http://127.0.0.1:3000").rstrip("/")
_netease_api_process: subprocess.Popen | None = None
DJ_SERVICE_URL = os.getenv("DJ_SERVICE_URL", "https://vercel-app-six-nu.vercel.app/api/generate").strip()
DJ_SERVICE_ENABLED = os.getenv("DJ_SERVICE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DJ_SERVICE_MODE = os.getenv("DJ_SERVICE_MODE", "llm").strip().lower()
DJ_SERVICE_TIMEOUT_SEC = float(os.getenv("DJ_SERVICE_TIMEOUT_SEC", "45") or 45)
DJ_MODEL = os.getenv("DJ_MODEL", "claude-sonnet-4-6").strip()
DJ_LLM_PROVIDER = os.getenv("DJ_LLM_PROVIDER", "").strip().lower()
DJ_TTS_VOICE = os.getenv("DJ_TTS_VOICE", "male-qn-jingying").strip()
DJ_TTS_ENABLED = os.getenv("DJ_TTS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DJ_TTS_MAX_SEGMENTS = max(0, int(os.getenv("DJ_TTS_MAX_SEGMENTS", "2") or 2))
DJ_DOUBAO_TTS_OPENING_ENABLED = os.getenv("DJ_DOUBAO_TTS_OPENING_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DOUBAO_TTS_ENDPOINT = os.getenv("DOUBAO_TTS_ENDPOINT", "https://openspeech.bytedance.com/api/v3/tts/unidirectional").strip()
DOUBAO_TTS_API_KEY = os.getenv("DOUBAO_TTS_API_KEY", "").strip()
DOUBAO_TTS_APP_ID = (os.getenv("DOUBAO_TTS_APP_ID") or os.getenv("DOUBAO_TTS_APP_KEY") or "").strip()
DOUBAO_TTS_ACCESS_KEY = os.getenv("DOUBAO_TTS_ACCESS_KEY", "").strip()
DOUBAO_TTS_RESOURCE_ID = os.getenv("DOUBAO_TTS_RESOURCE_ID", "seed-tts-2.0").strip()
DOUBAO_TTS_SPEAKER = os.getenv("DOUBAO_TTS_SPEAKER", "zh_female_vv_uranus_bigtts").strip()
DOUBAO_TTS_MODEL = os.getenv("DOUBAO_TTS_MODEL", "seed-tts-2.0-expressive").strip()
DOUBAO_TTS_FORMAT = os.getenv("DOUBAO_TTS_FORMAT", "mp3").strip()
DOUBAO_TTS_SAMPLE_RATE = int(os.getenv("DOUBAO_TTS_SAMPLE_RATE", "24000") or 24000)
DOUBAO_TTS_SPEECH_RATE = int(os.getenv("DOUBAO_TTS_SPEECH_RATE", "-5") or -5)
DOUBAO_TTS_LOUDNESS_RATE = int(os.getenv("DOUBAO_TTS_LOUDNESS_RATE", "8") or 8)
DOUBAO_TTS_EMOTION = os.getenv("DOUBAO_TTS_EMOTION", "").strip()
DOUBAO_ASR_ENDPOINT = os.getenv("DOUBAO_ASR_ENDPOINT", "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel").strip()
DOUBAO_ASR_API_KEY = (
    os.getenv("DOUBAO_ASR_API_KEY")
    or os.getenv("DOUBAO_ASR_ACCESS_TOKEN")
    or os.getenv("DOUBAO_TTS_API_KEY")
    or ""
).strip()
DOUBAO_ASR_RESOURCE_ID = os.getenv("DOUBAO_ASR_RESOURCE_ID", "volc.seedasr.sauc.duration").strip()
DOUBAO_ASR_APP_ID = (os.getenv("DOUBAO_ASR_APP_ID") or os.getenv("DOUBAO_TTS_APP_ID") or os.getenv("DOUBAO_TTS_APP_KEY") or "").strip()
DOUBAO_ASR_LANGUAGE = os.getenv("DOUBAO_ASR_LANGUAGE", "zh-CN").strip()
DOUBAO_ASR_SAMPLE_RATE = int(os.getenv("DOUBAO_ASR_SAMPLE_RATE", "16000") or 16000)
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "").strip()
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID", "").strip()
MINIMAX_TTS_ENDPOINT = os.getenv("MINIMAX_TTS_ENDPOINT", "https://api.minimax.io/v1/t2a_v2").strip()
MINIMAX_TTS_WS_ENDPOINT = os.getenv("MINIMAX_TTS_WS_ENDPOINT", "wss://api.minimax.io/ws/v1/t2a_v2").strip()
MINIMAX_TTS_MODEL = os.getenv("MINIMAX_TTS_MODEL", "speech-2.8-turbo").strip()
MINIMAX_TTS_VOICE_ID = os.getenv("MINIMAX_TTS_VOICE_ID", "Chinese (Mandarin)_Warm_Bestie").strip()
MINIMAX_TTS_SPEED = float(os.getenv("MINIMAX_TTS_SPEED", "0.95") or 0.95)
MINIMAX_TTS_VOLUME = float(os.getenv("MINIMAX_TTS_VOLUME", "1.0") or 1.0)
MINIMAX_TTS_PITCH = int(os.getenv("MINIMAX_TTS_PITCH", "0") or 0)
MINIMAX_TTS_LANGUAGE_BOOST = os.getenv("MINIMAX_TTS_LANGUAGE_BOOST", "Chinese").strip()
TTS_CACHE_DIR = RUNTIME_WRITE_DIR / "tts_cache"
TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
DJ_KNOWLEDGE_DYNAMIC_ENABLED = os.getenv("DJ_KNOWLEDGE_DYNAMIC_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DJ_KNOWLEDGE_LOOKUP_LIMIT = max(0, int(os.getenv("DJ_KNOWLEDGE_LOOKUP_LIMIT", "2") or 2))
DJ_KNOWLEDGE_FETCH_TIMEOUT_SEC = float(os.getenv("DJ_KNOWLEDGE_FETCH_TIMEOUT_SEC", "0.9") or 0.9)
DJ_KNOWLEDGE_COMMENT_LIMIT = max(0, int(os.getenv("DJ_KNOWLEDGE_COMMENT_LIMIT", "12") or 12))
DJ_KNOWLEDGE_CACHE_FILE = STATE_DIR / "dj_knowledge_cache.json"
_dj_knowledge_cache: dict[str, Any] | None = None
_dj_knowledge_fetching: set[str] = set()


L2_INTENTS = [
    "entity_search", "music_qa", "general_reco", "filtered_reco", "similar_reco",
    "control", "favorite", "implicit_feedback", "music_gen", "lyrics", "continuation",
    "adaptation", "vocal_separation", "mixing", "audio_edit", "pitch_tempo",
    "audio_effect", "chitchat", "general_qa",
]
SONG_INTENTS = {"entity_search", "general_reco", "filtered_reco", "similar_reco"}
DIALOGUE_INTENTS = {"music_qa", "chitchat", "general_qa"}


def safe_text(value: Any, limit: int = 240) -> str:
    if value is None:
        return ""
    try:
        text = str(value)
    except Exception:
        return ""
    return re.sub(r"\s+", " ", text).strip()[:limit]


def sanitize_song_list_payload(songs: Any, limit: int = 5) -> list[dict[str, Any]]:
    if not isinstance(songs, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in songs[:limit]:
        song = sanitize_song_payload(item)
        if song.get("title") and song.get("artist"):
            cleaned.append(song)
    return cleaned


def compact_dj_speech(value: Any, limit: int) -> str:
    text = safe_text(value, max(limit * 2, limit))
    if len(text) <= limit:
        return text
    sentences = re.split(r"(?<=[。！？!?])", text)
    kept = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(kept + sentence) <= limit:
            kept += sentence
        elif kept:
            break
        else:
            kept = sentence[:limit].rstrip("，、；; ")
            break
    kept = kept.rstrip("，、；; ")
    if kept and kept[-1] not in "。！？!?" and len(kept) < limit:
        kept += "。"
    return kept[:limit]


def is_template_dj_text(text: str) -> bool:
    return contains_any(
        str(text or ""),
        [
            "入口打开",
            "合适的位置",
            "贴着「",
            "的颜色往里走",
            "不急着堆情绪",
        ],
    )


def sanitize_song_payload(song: Any) -> dict[str, Any]:
    if not isinstance(song, dict):
        return {}
    title = safe_text(song.get("title"), 120)
    artist = safe_text(song.get("artist"), 120)
    if not title:
        return {}
    clean: dict[str, Any] = {
        "title": title,
        "artist": artist,
        "reason": safe_text(song.get("reason"), 240),
        "group": safe_text(song.get("group"), 120),
        "source": safe_text(song.get("source"), 80),
    }
    for key in ("url", "spotify_search", "stream_url", "embed_url", "provider"):
        value = safe_text(song.get(key), 500 if key.endswith("url") or key == "spotify_search" else 120)
        if value:
            clean[key] = value
    for key in ("verified", "ok", "playable"):
        if key in song:
            clean[key] = bool(song.get(key))
    return {key: value for key, value in clean.items() if value not in ("", None)}


def sanitize_groups_payload(groups: Any, *, max_groups: int = 5, max_songs: int = 8) -> list[dict[str, Any]]:
    if not isinstance(groups, list):
        return []
    clean_groups: list[dict[str, Any]] = []
    for group in groups[:max_groups]:
        if not isinstance(group, dict):
            continue
        songs: list[dict[str, Any]] = []
        for song in (group.get("songs") if isinstance(group.get("songs"), list) else [])[:max_songs]:
            clean_song = sanitize_song_payload(song)
            if clean_song.get("title"):
                songs.append(clean_song)
        if songs:
            clean_groups.append({"title": safe_text(group.get("title") or "推荐结果", 120), "songs": songs})
    return clean_groups


def sanitize_analysis_payload(analysis: Any) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}
    target = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
    return {
        "domain": safe_text(analysis.get("domain"), 60),
        "intent": safe_text(analysis.get("intent"), 60),
        "entity_type": safe_text(analysis.get("entity_type") or "unknown", 60),
        "action": safe_text(analysis.get("action") or "classify", 60),
        "identified": bool(analysis.get("identified", True)),
        "reference": safe_text(analysis.get("reference"), 160),
        "target_entity": {
            "name": safe_text(target.get("name"), 120),
            "artist": safe_text(target.get("artist"), 120),
            "album": safe_text(target.get("album"), 120),
        },
        "traits": [safe_text(item, 80) for item in (analysis.get("traits") if isinstance(analysis.get("traits"), list) else [])[:8] if safe_text(item, 80)],
    }


def sanitize_context_payload(context: Any) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    history = context.get("history") if isinstance(context.get("history"), list) else []
    clean_history = []
    for item in history[-6:]:
        if not isinstance(item, dict):
            continue
        clean_history.append(
            {
                "role": safe_text(item.get("role"), 30),
                "content": safe_text(item.get("content"), 600),
            }
        )
    return {
        "session_id": safe_text(context.get("session_id"), 80),
        "interaction_mode": safe_text(context.get("interaction_mode"), 60),
        "playback_active": bool(context.get("playback_active")),
        "playback_status": safe_text(context.get("playback_status"), 40),
        "history": clean_history,
        "last_groups": sanitize_groups_payload(context.get("last_groups"), max_groups=5, max_songs=8),
        "mentioned_songs": sanitize_song_list_payload(context.get("mentioned_songs"), limit=5),
        "current_song": sanitize_song_payload(context.get("current_song")),
        "weather": safe_text(context.get("weather"), 80),
        "time": safe_text(context.get("time"), 80),
        "location": safe_text(context.get("location"), 80),
        "heartRate": safe_text(context.get("heartRate"), 40),
        "scene": safe_text(context.get("scene"), 80),
        "mood": safe_text(context.get("mood"), 80),
    }


def safe_error_message(exc: Exception) -> str:
    if isinstance(exc, RecursionError) or "maximum recursion depth" in str(exc):
        return "推荐接口内部状态异常，请刷新后重试。"
    return "推荐接口异常，请稍后重试。"


def demo_auth_enabled() -> bool:
    return bool(DEMO_BASIC_AUTH_USER and DEMO_BASIC_AUTH_PASSWORD)


def has_valid_demo_auth(request: FastAPIRequest) -> bool:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "basic" or not token:
        return False
    try:
        decoded = base64.b64decode(token).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(username, DEMO_BASIC_AUTH_USER) and secrets.compare_digest(
        password,
        DEMO_BASIC_AUTH_PASSWORD,
    )


@app.middleware("http")
async def require_demo_auth(request: FastAPIRequest, call_next):
    if not demo_auth_enabled() or request.url.path == "/healthz" or request.method == "OPTIONS":
        return await call_next(request)
    if has_valid_demo_auth(request):
        return await call_next(request)
    return JSONResponse(
        {"error": "需要输入测试账号密码。"},
        status_code=401,
        headers={"WWW-Authenticate": 'Basic realm="Melodio Demo"'},
    )


INTENT_POLICY = load_text_prompt("prompts/intent_policy.md")
SYSTEM_PROMPT = f"{INTENT_POLICY}\n\n---\n\n{load_text_prompt('prompts/intent_slot_sp.md')}"
RECOMMENDATION_PROMPT = load_text_prompt("prompts/recommendation_sp.md")


SONGS: list[dict[str, Any]] = [
    {
        "title": "泸沽湖",
        "artist": "麻园诗人",
        "traits": ["乐队的夏天", "西南摇滚", "辽阔", "粗粝", "公路感"],
        "genres": ["摇滚", "民谣摇滚"],
        "moods": ["辽阔", "孤独", "热烈"],
        "scenes": ["开车", "深夜", "旅行"],
    },
    {
        "title": "山雀",
        "artist": "万青",
        "traits": ["诗性", "城市", "摇滚", "叙事", "克制"],
        "genres": ["摇滚", "独立"],
        "moods": ["克制", "孤独"],
        "scenes": ["深夜", "通勤"],
    },
    {
        "title": "大石碎胸口",
        "artist": "万青",
        "traits": ["诗性", "荒诞", "摇滚", "铜管"],
        "genres": ["摇滚", "独立"],
        "moods": ["冷峻", "讽刺"],
        "scenes": ["深夜"],
    },
    {
        "title": "杀死那个石家庄人",
        "artist": "万青",
        "traits": ["叙事", "冷峻", "城市", "摇滚"],
        "genres": ["摇滚", "独立"],
        "moods": ["冷峻", "悲伤"],
        "scenes": ["深夜", "通勤"],
    },
    {
        "title": "秦皇岛",
        "artist": "万青",
        "traits": ["海边", "诗性", "摇滚", "低回"],
        "genres": ["摇滚", "独立"],
        "moods": ["克制", "辽阔"],
        "scenes": ["旅行", "雨天"],
    },
    {
        "title": "南方姑娘",
        "artist": "赵雷",
        "traits": ["民谣", "温柔", "城市", "叙事"],
        "genres": ["民谣"],
        "moods": ["温柔", "怀旧"],
        "scenes": ["雨天", "夜晚"],
    },
    {
        "title": "成都",
        "artist": "赵雷",
        "traits": ["民谣", "城市", "怀旧", "慢速"],
        "genres": ["民谣"],
        "moods": ["怀旧", "温柔"],
        "scenes": ["旅行", "夜晚"],
    },
    {
        "title": "理想三旬",
        "artist": "陈鸿宇",
        "traits": ["民谣", "低沉", "青春", "告别"],
        "genres": ["民谣"],
        "moods": ["怀旧", "伤感"],
        "scenes": ["深夜", "独处"],
    },
    {
        "title": "奇妙能力歌",
        "artist": "陈粒",
        "traits": ["独立民谣", "灵动", "女声", "想象力"],
        "genres": ["民谣", "独立"],
        "moods": ["灵动", "治愈"],
        "scenes": ["咖啡馆", "通勤"],
    },
    {
        "title": "喜欢",
        "artist": "张悬",
        "aliases": ["焦安溥", "jiaoanpu", "张悬"],
        "traits": ["女声", "民谣", "松弛", "亲密"],
        "genres": ["民谣", "独立"],
        "moods": ["温柔", "松弛"],
        "scenes": ["夜晚", "咖啡馆"],
    },
    {
        "title": "宝贝",
        "artist": "张悬",
        "aliases": ["焦安溥", "jiaoanpu", "张悬"],
        "traits": ["女声", "轻盈", "亲密", "民谣"],
        "genres": ["民谣", "独立"],
        "moods": ["温柔", "治愈"],
        "scenes": ["早晨", "咖啡馆"],
    },
    {
        "title": "玫瑰色的你",
        "artist": "张悬",
        "aliases": ["焦安溥", "jiaoanpu", "张悬"],
        "traits": ["独立", "女声", "明亮", "人文"],
        "genres": ["民谣", "独立"],
        "moods": ["温柔", "坚定"],
        "scenes": ["通勤", "夜晚"],
    },
    {
        "title": "晴天",
        "artist": "周杰伦",
        "aliases": ["zhoujielun", "jay chou"],
        "traits": ["华语流行", "校园", "旋律强", "怀旧"],
        "genres": ["流行"],
        "moods": ["怀旧", "温柔"],
        "scenes": ["通勤", "雨天"],
    },
    {
        "title": "七里香",
        "artist": "周杰伦",
        "aliases": ["zhoujielun", "jay chou"],
        "traits": ["华语流行", "夏天", "旋律强", "浪漫"],
        "genres": ["流行"],
        "moods": ["浪漫", "明亮"],
        "scenes": ["夏天", "通勤"],
    },
    {
        "title": "一路向北",
        "artist": "周杰伦",
        "aliases": ["zhoujielun", "jay chou"],
        "traits": ["公路", "伤感", "华语流行", "速度感"],
        "genres": ["流行"],
        "moods": ["伤感", "孤独"],
        "scenes": ["开车", "深夜"],
    },
    {
        "title": "夜空中最亮的星",
        "artist": "逃跑计划",
        "traits": ["乐队", "励志", "大合唱", "明亮"],
        "genres": ["摇滚", "流行摇滚"],
        "moods": ["坚定", "热血"],
        "scenes": ["开车", "夜晚"],
    },
    {
        "title": "突然好想你",
        "artist": "五月天",
        "traits": ["乐队", "华语流行", "思念", "副歌强"],
        "genres": ["流行摇滚"],
        "moods": ["伤感", "怀旧"],
        "scenes": ["深夜", "开车"],
    },
    {
        "title": "海阔天空",
        "artist": "Beyond",
        "traits": ["华语摇滚", "乐队", "励志", "大合唱"],
        "genres": ["摇滚", "流行摇滚"],
        "moods": ["热血", "坚定"],
        "scenes": ["开车", "现场"],
    },
    {
        "title": "玫瑰窃贼",
        "artist": "告五人",
        "traits": ["男女声", "流行摇滚", "浪漫", "轻快"],
        "genres": ["流行摇滚"],
        "moods": ["浪漫", "明亮"],
        "scenes": ["通勤", "约会"],
    },
    {
        "title": "在这颗行星所有的酒馆",
        "artist": "寸铁",
        "traits": ["乐夏同圈层", "后摇", "诗意", "爆发"],
        "genres": ["摇滚", "后摇"],
        "moods": ["辽阔", "热烈"],
        "scenes": ["深夜", "开车"],
    },
    {
        "title": "艾蜜莉",
        "artist": "回春丹",
        "traits": ["乐夏同圈层", "复古", "摇滚", "暧昧"],
        "genres": ["摇滚"],
        "moods": ["热烈", "复古"],
        "scenes": ["派对", "通勤"],
    },
    {
        "title": "道山靓仔",
        "artist": "五条人",
        "traits": ["乐夏同圈层", "方言", "荒诞", "南方"],
        "genres": ["民谣摇滚", "独立"],
        "moods": ["松弛", "荒诞"],
        "scenes": ["旅行", "夏天"],
    },
    {
        "title": "The Night We Met",
        "artist": "Lord Huron",
        "traits": ["英文", "伤感", "电影感", "慢速"],
        "genres": ["Indie Folk"],
        "moods": ["伤感", "孤独"],
        "scenes": ["深夜", "开车"],
    },
    {
        "title": "Let Her Go",
        "artist": "Passenger",
        "traits": ["英文", "民谣", "伤感", "旋律清晰"],
        "genres": ["Folk", "Pop"],
        "moods": ["伤感", "温柔"],
        "scenes": ["开车", "雨天"],
    },
    {
        "title": "Ocean Eyes",
        "artist": "Billie Eilish",
        "traits": ["暗黑流行", "女声", "低语", "空间感"],
        "genres": ["Alternative Pop"],
        "moods": ["空灵", "克制"],
        "scenes": ["深夜", "独处"],
    },
    {
        "title": "bury a friend",
        "artist": "Billie Eilish",
        "traits": ["暗黑流行", "低频", "实验", "耳语"],
        "genres": ["Alternative Pop"],
        "moods": ["暗黑", "紧张"],
        "scenes": ["夜晚"],
    },
    {
        "title": "Blinding Lights",
        "artist": "The Weeknd",
        "traits": ["英文", "复古合成器", "速度感", "夜行"],
        "genres": ["Synth Pop"],
        "moods": ["热血", "明亮"],
        "scenes": ["开车", "健身"],
    },
    {
        "title": "Midnight City",
        "artist": "M83",
        "traits": ["电子", "夜景", "合成器", "公路感"],
        "genres": ["电子", "Synth Pop"],
        "moods": ["辽阔", "热血"],
        "scenes": ["开车", "夜晚"],
    },
    {
        "title": "Strobe",
        "artist": "deadmau5",
        "traits": ["电子", "渐进", "长线条", "专注"],
        "genres": ["电子"],
        "moods": ["专注", "沉浸"],
        "scenes": ["工作", "健身"],
    },
    {
        "title": "Lose Yourself",
        "artist": "Eminem",
        "traits": ["说唱", "励志", "高能", "节奏强"],
        "genres": ["Hip Hop"],
        "moods": ["热血", "坚定"],
        "scenes": ["健身", "跑步"],
    },
    {
        "title": "Nujabes - Feather",
        "artist": "Nujabes",
        "traits": ["Lo-fi", "爵士说唱", "松弛", "律动"],
        "genres": ["Lo-fi", "Hip Hop"],
        "moods": ["松弛", "专注"],
        "scenes": ["工作", "学习"],
    },
    {
        "title": "Nuvole Bianche",
        "artist": "Ludovico Einaudi",
        "traits": ["钢琴", "纯音乐", "安静", "疗愈"],
        "genres": ["古典", "器乐"],
        "moods": ["安静", "治愈"],
        "scenes": ["睡前", "雨天", "学习"],
    },
    {
        "title": "Merry Christmas Mr. Lawrence",
        "artist": "Ryuichi Sakamoto",
        "traits": ["钢琴", "电影配乐", "克制", "东方感"],
        "genres": ["器乐", "电影配乐"],
        "moods": ["克制", "治愈"],
        "scenes": ["雨天", "学习"],
    },
]


ARTIST_ALIASES = {
    "焦安溥": "张悬",
    "jiaoanpu": "张悬",
    "张悬": "张悬",
    "zhoujielun": "周杰伦",
    "jay chou": "周杰伦",
    "周杰伦": "周杰伦",
    "许嵩": "许嵩",
    "vae": "许嵩",
    "billie eilish": "Billie Eilish",
    "麻园诗人": "麻园诗人",
    "万青": "万青",
    "万能青年旅店": "万青",
    "王菲": "王菲",
    "faye wong": "王菲",
    "海尔兄弟": "Higher Brothers",
    "higher brothers": "Higher Brothers",
    "higherbrothers": "Higher Brothers",
    "马思唯": "马思唯",
    "马思维": "马思唯",
    "马师傅": "马思唯",
    "masiwei": "马思唯",
    "knowknow": "KnowKnow",
    "谢帝": "谢帝",
    "gai": "GAI",
    "欧阳靖": "MC Jin",
    "mc jin": "MC Jin",
    "侃爷": "Kanye West",
    "坎耶": "Kanye West",
    "kanye": "Kanye West",
    "kanye west": "Kanye West",
    "霉霉": "Taylor Swift",
    "泰勒": "Taylor Swift",
    "taylorswift": "Taylor Swift",
    "taylor swift": "Taylor Swift",
    "碧梨": "Billie Eilish",
    "比莉艾利什": "Billie Eilish",
    "比利艾利什": "Billie Eilish",
    "打雷姐": "Lana Del Rey",
    "lana": "Lana Del Rey",
    "lana del rey": "Lana Del Rey",
    "a妹": "Ariana Grande",
    "ariana grande": "Ariana Grande",
    "火星哥": "Bruno Mars",
    "bruno mars": "Bruno Mars",
    "盆栽": "The Weeknd",
    "the weeknd": "The Weeknd",
    "啪姐": "Dua Lipa",
    "dua lipa": "Dua Lipa",
}

MUSIC_COLLECTION_ALIASES = {
    "乐夏": "乐队的夏天",
    "乐队的夏天": "乐队的夏天",
    "歌手": "歌手",
    "我是歌手": "歌手",
    "声生不息": "声生不息",
    "宝岛季": "声生不息宝岛季",
    "声生不息宝岛季": "声生不息宝岛季",
    "好声音": "中国好声音",
    "中国好声音": "中国好声音",
    "新说唱": "中国新说唱",
    "中国新说唱": "中国新说唱",
    "说唱新世代": "说唱新世代",
    "明日之子": "明日之子",
    "披哥": "披荆斩棘",
    "披荆斩棘": "披荆斩棘",
    "浪姐": "乘风破浪",
    "乘风破浪": "乘风破浪",
    "天赐": "天赐的声音",
    "天赐的声音": "天赐的声音",
}

ARTIST_SIGNATURE_SONGS = {
    "周杰伦": ["晴天", "七里香", "稻香", "夜曲", "青花瓷", "简单爱", "双截棍", "一路向北", "不能说的秘密", "告白气球", "以父之名", "发如雪"],
    "张悬": ["宝贝", "喜欢", "玫瑰色的你", "关于我爱你", "城市", "艳火"],
    "Billie Eilish": ["bad guy", "Ocean Eyes", "bury a friend", "when the party's over", "everything i wanted", "Happier Than Ever"],
    "麻园诗人": ["泸沽湖", "晚安", "母星", "昆明"],
    "万青": ["杀死那个石家庄人", "秦皇岛", "山雀", "大石碎胸口"],
    "许嵩": ["有何不可", "灰色头像", "玫瑰花的葬礼", "清明雨上", "庐州月", "雅俗共赏"],
    "王菲": ["红豆", "匆匆那年", "我愿意", "人间", "天空", "执迷不悔"],
    "Beyond": ["海阔天空", "光辉岁月", "真的爱你", "喜欢你"],
    "Higher Brothers": ["Made In China", "Young Master", "WeChat", "Empire", "Open It Up"],
}


DEMO_MUSIC_ENTITY_MEMORY = {
    "artist_aliases": {
        "回春丹": "回春丹",
        "麻园": "麻园诗人",
        "麻园诗人": "麻园诗人",
        "陈婧霏": "陈婧霏",
        "陈婧菲": "陈婧霏",
        "任素汐": "任素汐",
        "任素西": "任素汐",
        "草东": "草东没有派对",
        "草东没有派对": "草东没有派对",
        "新裤子": "新裤子",
        "刺猬": "刺猬",
        "痛仰": "痛仰乐队",
        "痛仰乐队": "痛仰乐队",
        "二手玫瑰": "二手玫瑰",
        "五条人": "五条人",
        "九连真人": "九连真人",
        "旅行团": "旅行团乐队",
        "旅行团乐队": "旅行团乐队",
        "海龟先生": "海龟先生",
        "木马": "木马",
        "达达": "达达乐队",
        "达达乐队": "达达乐队",
        "重塑": "重塑雕像的权利",
        "重塑雕像的权利": "重塑雕像的权利",
        "后海大鲨鱼": "后海大鲨鱼",
        "鹿先森": "鹿先森乐队",
        "鹿先森乐队": "鹿先森乐队",
        "马赛克": "马赛克乐队",
        "马赛克乐队": "马赛克乐队",
        "福禄寿": "福禄寿FloruitShow",
        "福禄寿FloruitShow": "福禄寿FloruitShow",
        "康士坦的变化球": "康士坦的变化球",
        "瓦依那": "瓦依那",
        "安达组合": "安达组合",
        "面孔": "面孔乐队",
        "面孔乐队": "面孔乐队",
        "盘尼西林": "盘尼西林",
        "click15": "Click#15",
        "click#15": "Click#15",
        "八仙饭店": "八仙饭店",
        "白皮书": "白皮书乐队",
        "白皮书乐队": "白皮书乐队",
        "椅子乐团": "椅子乐团",
        "鸟撞": "鸟撞",
        "布衣": "布衣乐队",
        "布衣乐队": "布衣乐队",
        "声音玩具": "声音玩具",
        "霓虹花园": "霓虹花园",
        "Joyside": "Joyside",
        "joyside": "Joyside",
        "Carsick Cars": "Carsick Cars",
        "carsick cars": "Carsick Cars",
        "Masiwei": "马思唯",
        "melo": "Melo",
        "psy.p": "Psy.P",
        "psyp": "Psy.P",
        "Psy.P": "Psy.P",
        "王以太": "王以太",
        "艾热": "艾热",
        "VaVa": "VaVa",
        "vava": "VaVa",
        "Jony J": "Jony J",
        "jony j": "Jony J",
        "Tizzy T": "Tizzy T",
        "tizzy t": "Tizzy T",
        "派克特": "派克特",
        "功夫胖": "功夫胖",
        "杨和苏": "杨和苏",
        "早安": "早安",
        "小青龙": "小青龙",
        "满舒克": "满舒克",
        "黄旭": "黄旭",
        "法老": "法老",
        "宝石gem": "宝石Gem",
        "宝石Gem": "宝石Gem",
        "董宝石": "宝石Gem",
        "乃万": "乃万",
        "刘聪": "刘聪",
        "capper": "Capper",
        "Capper": "Capper",
        "Bridge": "Bridge",
        "bridge": "Bridge",
        "盛宇": "盛宇",
        "大傻": "大傻",
    },
    "signature_songs": {
        "回春丹": ["初恋", "艾蜜莉", "正义", "鲜花"],
        "陈婧霏": ["人间指南", "深蓝", "爱人", "生活倒影", "清醒梦"],
        "任素汐": ["我要你", "胡广生", "王招君", "再见青春"],
        "草东没有派对": ["山海", "大风吹", "烂泥", "丑奴儿"],
        "新裤子": ["你要跳舞吗", "没有理想的人不伤心", "生活因你而火热"],
        "刺猬": ["火车驶向云外，梦安魂于九霄", "生之响往", "白日梦蓝"],
        "痛仰乐队": ["西湖", "再见杰克", "不要停止我的音乐"],
        "二手玫瑰": ["仙儿", "命运", "我要开花"],
        "五条人": ["道山靓仔", "阿珍爱上了阿强", "问题出现我再告诉大家"],
        "九连真人": ["莫欺少年穷", "夜游神", "凡人歌"],
        "海龟先生": ["男孩别哭", "Where Are You Going", "玛卡瑞纳"],
        "旅行团乐队": ["逝去的歌", "于是我不再唱歌", "永远都会在"],
        "马思唯": ["R&B All Night", "崂山道士", "花花公子", "黑马王子", "Promise"],
        "KnowKnow": ["R&B All Night", "Mr. Bentley", "Mafia Cashier"],
        "Melo": ["Born Like This", "我不想改变世界我只想不被世界改变"],
        "Psy.P": ["Bad Habits", "街头霸王"],
        "Higher Brothers": ["Made In China", "Young Master", "WeChat", "Empire", "Open It Up"],
        "谢帝": ["明天不上班", "老子明天不上班", "堵起"],
        "GAI": ["沧海一声笑", "华夏", "虎山行", "烈火战马"],
        "VaVa": ["我的新衣", "Life's a Struggle", "Queen Is Back"],
        "Jony J": ["不用去猜", "My Man", "套路"],
        "Tizzy T": ["头文字T", "020", "几乎成名"],
        "王以太": ["目不转睛", "危险派对", "阿司匹林"],
        "艾热": ["千里万里", "乌云中", "星球坠落"],
        "派克特": ["Y.O.U.N.G.", "长安少年", "午夜伤心电台"],
        "功夫胖": ["莫欺少年穷", "湘江词王", "冠军情歌"],
        "杨和苏": ["命不由天", "都走了", "小丑女"],
        "早安": ["麒麟", "临时抱佛脚", "早安"],
        "小青龙": ["Time", "新光巷", "不想睡"],
        "满舒克": ["做我的猫", "慢热", "失眠夜"],
        "黄旭": ["天堂来信", "如果真的是比说唱真的强你好几倍"],
        "宝石Gem": ["野狼disco", "电梯战神", "送情郎"],
        "刘聪": ["Hey KONG", "经济舱", "长沙HOOD"],
        "Capper": ["雪 Distance", "无人区玫瑰", "衔尾蛇"],
    },
}

ARTIST_ALIASES.update(DEMO_MUSIC_ENTITY_MEMORY["artist_aliases"])
for _artist, _songs in DEMO_MUSIC_ENTITY_MEMORY["signature_songs"].items():
    ARTIST_SIGNATURE_SONGS.setdefault(_artist, _songs)

SIMILAR_ARTIST_SONGS = {
    "马思唯": [
        ("Higher Brothers", "Made In China"),
        ("KnowKnow", "R&B All Night"),
        ("Psy.P", "Bad Habits"),
        ("Melo", "Born Like This"),
        ("王以太", "目不转睛"),
        ("谢帝", "明天不上班"),
    ],
    "Higher Brothers": [
        ("马思唯", "R&B All Night"),
        ("KnowKnow", "Mr. Bentley"),
        ("Psy.P", "Bad Habits"),
        ("Melo", "Born Like This"),
        ("谢帝", "明天不上班"),
    ],
    "回春丹": [
        ("新裤子", "你要跳舞吗"),
        ("刺猬", "火车驶向云外，梦安魂于九霄"),
        ("痛仰乐队", "西湖"),
        ("二手玫瑰", "仙儿"),
        ("五条人", "道山靓仔"),
    ],
    "草东没有派对": [
        ("康士坦的变化球", "搁浅的人"),
        ("刺猬", "火车驶向云外，梦安魂于九霄"),
        ("八仙饭店", "吞吐"),
        ("白皮书乐队", "清河"),
        ("回春丹", "正义"),
    ],
    "周深": [
        ("毛不易", "消愁"),
        ("霍尊", "卷珠帘"),
        ("李健", "贝加尔湖畔"),
        ("张碧晨", "年轮"),
        ("周深", "大鱼"),
    ],
}

ARTIST_SIMILARITY_PROFILES = {
    "张悬": {
        "priority": ["台湾独立", "台湾创作女声", "独立民谣"],
        "songs": [
            ("陈绮贞", "旅行的意义"),
            ("魏如萱", "你啊你啊"),
            ("陈珊妮", "情歌"),
            ("苏打绿", "无与伦比的美丽"),
            ("929", "也许像星星"),
        ],
    },
    "麻园诗人": {
        "priority": ["云南", "西南摇滚", "乐队的夏天", "地域表达"],
        "songs": [
            ("山人乐队", "三十年"),
            ("KAWA乐队", "出云南记"),
            ("马帮乐队", "赶摆路上"),
            ("九连真人", "莫欺少年穷"),
            ("五条人", "道山靓仔"),
        ],
    },
}

SIMILAR_SONG_MEMORY = {
    ("麻园诗人", "泸沽湖"): {
        "traits": ["西南摇滚", "云南", "公路感", "辽阔", "粗粝"],
        "songs": [
            ("麻园诗人", "晚安", "同乐队里更内收的一首，保留麻园诗人的粗粝和民谣摇滚底色。"),
            ("麻园诗人", "昆明", "同样有云南地域气息，适合先沿着本地色彩延展。"),
            ("九连真人", "莫欺少年穷", "同属乐夏圈层，地方语言和乐队冲劲都比较明显。"),
            ("五条人", "道山靓仔", "南方地方感很强，和《泸沽湖》的地域画面能接上。"),
            ("痛仰乐队", "西湖", "同样是带地名和公路感的乐队作品，情绪更开阔。"),
            ("寸铁", "在这颗行星所有的酒馆", "乐夏同圈层，后半段有更明显的爆发。"),
        ],
    },
    ("Higher Brothers", "Made In China"): {
        "traits": ["中文说唱", "厂牌圈层", "高能", "国际化", "hook"],
        "songs": [
            ("马思唯", "R&B All Night", "同属 CDC/Higher Brothers 圈层，旋律性更强。"),
            ("KnowKnow", "Mr. Bentley", "同团成员个人作品，保留潮流说唱的松弛感。"),
            ("谢帝", "明天不上班", "成都说唱代表作，地域标签和态度都清楚。"),
            ("王以太", "目不转睛", "同属四川说唱圈层，更偏旋律和律动。"),
            ("Psy.P", "Bad Habits", "同圈层，适合从 Higher Brothers 往成员个人作品延展。"),
        ],
    },
    ("马思唯", "R&B All Night"): {
        "traits": ["中文说唱", "R&B", "旋律说唱", "夜晚", "松弛"],
        "songs": [
            ("马思唯", "Promise", "同艺人里旋律性和夜晚感都比较接近。"),
            ("KnowKnow", "R&B All Night", "同圈层版本，保留 R&B 和说唱之间的顺滑听感。"),
            ("王以太", "目不转睛", "旋律说唱代表，律动和流行度都更稳。"),
            ("艾热", "千里万里", "偏旋律和情绪表达，适合从 R&B 说唱延展。"),
            ("满舒克", "慢热", "更轻松的旋律说唱，适合保持夜晚氛围。"),
        ],
    },
    ("陈婧霏", "深蓝"): {
        "traits": ["复古", "女声", "梦幻", "都市", "松弛"],
        "songs": [
            ("陈婧霏", "人间指南", "同艺人里复古和都市感都更稳定。"),
            ("椅子乐团", "Rollin' On", "复古、轻盈、都市感接近，但换成乐团表达。"),
            ("椅子乐团", "Maybe Maybe", "同样是轻盈复古的都市流行，颗粒更细、更松弛。"),
            ("告五人", "披星戴月的想你", "保留复古流行和夜晚感，旋律更外放一些。"),
            ("陈绮贞", "小船", "独立女声里更轻、更漂浮的一侧，适合接住《深蓝》的梦幻感。"),
        ],
    },
    ("回春丹", "初恋"): {
        "traits": ["复古摇滚", "暧昧", "乐夏", "旋律", "热烈"],
        "songs": [
            ("回春丹", "艾蜜莉", "同乐队代表作，复古和暧昧感最接近。"),
            ("新裤子", "你要跳舞吗", "乐夏圈层里更直接的复古舞曲感。"),
            ("海龟先生", "男孩别哭", "复古、浪漫和乐队律动都比较近。"),
            ("马赛克乐队", "霓虹甜心", "复古流行摇滚，适合接住回春丹的明亮面。"),
            ("刺猬", "白日梦蓝", "乐夏圈层里更青春、更躁的一侧。"),
        ],
    },
}

DJ_MUSIC_KNOWLEDGE = {
    ("张悬", "宝贝"): "《宝贝》很像一封很短的小纸条，张悬唱得特别近，听起来不像舞台表演，更像有人在旁边轻轻哼给你听。",
    ("张悬", "喜欢"): "《喜欢》没有把情绪喊出来，反而像一句憋了很久才说出口的话，所以很多人会觉得它特别私人。",
    ("张悬", "关于我爱你"): "这首歌像是在认真整理一段关系，话说得不重，但每一句都像真的想过很久。",
    ("麻园诗人", "泸沽湖"): "《泸沽湖》一听就有画面，湖水、山路和云南的空气都在里面；它不是单纯安静，后面会慢慢把人带起来。",
    ("麻园诗人", "晚安"): "麻园诗人的歌经常有一种“粗糙但真诚”的劲儿，《晚安》听起来像热闹散场后，一个人把灯慢慢关上。",
    ("万青", "杀死那个石家庄人"): "这首歌厉害在它像一部城市短片：名字很扎眼，唱的却是很多普通人说不出口的疲惫。",
    ("万青", "秦皇岛"): "《秦皇岛》不急着煽情，像坐在一座北方城市的海边发呆，风很大，但人不太说话。",
    ("周杰伦", "晴天"): "《晴天》一响起来，很多人会直接回到学生时代：操场、课桌、没说出口的话，全都被那把吉他带出来。",
    ("周杰伦", "七里香"): "《七里香》像一张很有夏天味道的明信片，旋律一出来就很容易跟风、稻田和白衬衫连在一起。",
    ("周杰伦", "夜曲"): "《夜曲》是周杰伦暗色系里很有代表性的一首，像把夜晚、钢琴和一点点孤独装进同一个房间。",
    ("Billie Eilish", "bad guy"): "《bad guy》有意思的是它不靠大喊大叫，反而用很轻、很近的声音唱出一点坏坏的表情。",
    ("Billie Eilish", "Ocean Eyes"): "《Ocean Eyes》听起来像一盏蓝色的小夜灯，声音很轻，但画面一下就亮了。",
    ("赵雷", "南方姑娘"): "赵雷很会写那种像在路边听来的故事，《南方姑娘》也是这样，一个人、一座城市，几句就站住了。",
    ("陈粒", "走马"): "《走马》像一边走路一边想事情，旋律不复杂，但越听越像在替你把心里的话说出来。",
    ("李宗盛", "山丘"): "《山丘》像一个过来人坐下来聊天，不急着劝你，只是把很多年后的回头看唱出来。",
    ("伍佰", "晚风"): "伍佰的浪漫很直接，《晚风》像夏天晚上骑车经过一条老街，风一吹，人就有点想唱歌。",
}


def normalize(text: str) -> str:
    return re.sub(r"[\s\-_/·,.!?'\"，。！？、《》]", "", text.lower())


def canonical_artist_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    compact = normalize(text)
    for alias, artist in ARTIST_ALIASES.items():
        if text.lower() == alias.lower() or compact == normalize(alias):
            return artist
    return text


def canonicalize_music_query(query: str) -> str:
    text = str(query or "")
    if not text:
        return text
    normalized = text
    for alias, artist in sorted(ARTIST_ALIASES.items(), key=lambda item: len(normalize(item[0])), reverse=True):
        if normalize(alias) == normalize(artist):
            continue
        if re.search(r"[A-Za-z]", alias):
            normalized = re.sub(rf"\b{re.escape(alias)}\b", artist, normalized, flags=re.I)
        elif alias in normalized:
            normalized = normalized.replace(alias, artist)
    return normalized


def music_task_context(query: str) -> bool:
    return contains_any(
        query,
        [
            "播放", "放", "听", "想听", "来点", "来几首", "推荐", "找", "搜索", "查", "歌曲",
            "歌", "音乐", "作品", "专辑", "歌手", "艺人", "乐队", "相似", "类似", "音色",
            "风格", "曲库", "节目", "综艺", "现场",
        ],
    )


def linked_music_entities(query: str) -> list[dict[str, str]]:
    if not music_task_context(query):
        return []
    text = str(query or "")
    compact = normalize(text)
    links: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    def add(raw: str, canonical: str, entity_type: str) -> None:
        raw = str(raw or "").strip()
        canonical = str(canonical or "").strip()
        if not raw or not canonical:
            return
        key = (normalize(raw), normalize(canonical), entity_type)
        if key in seen:
            return
        seen.add(key)
        links.append({"raw": raw, "canonical": canonical, "type": entity_type})

    for alias, artist in sorted(ARTIST_ALIASES.items(), key=lambda item: len(normalize(item[0])), reverse=True):
        alias_key = normalize(alias)
        if not alias_key:
            continue
        if re.search(r"[A-Za-z]", alias):
            if re.search(rf"\b{re.escape(alias)}\b", text, flags=re.I):
                add(alias, artist, "artist")
        elif alias in text or alias_key in compact:
            add(alias, artist, "artist")
    for song in SONGS:
        artist = str(song.get("artist") or "")
        if artist and (artist.lower() in text.lower() or normalize(artist) in compact):
            add(artist, artist, "artist")
        for alias in song.get("aliases", []):
            alias_text = str(alias or "")
            if alias_text and (alias_text.lower() in text.lower() or normalize(alias_text) in compact):
                add(alias_text, artist, "artist")
    for alias, collection in sorted(MUSIC_COLLECTION_ALIASES.items(), key=lambda item: len(normalize(item[0])), reverse=True):
        alias_key = normalize(alias)
        if alias and (alias in text or alias_key in compact):
            add(alias, collection, "collection")
    return links[:6]


def entity_link_hint_text(query: str) -> str:
    links = linked_music_entities(query)
    if not links:
        return ""
    lines = [
        f"- 原词「{item['raw']}」在音乐语境下优先联想到 {item['type']}「{item['canonical']}」。"
        for item in links
    ]
    return "音乐实体联想提示：\n" + "\n".join(lines)


def normalize_song_match_text(text: str) -> str:
    cleaned = re.sub(r"[\(（\[].*?[\)）\]]", "", text or "")
    cleaned = re.sub(r"(?:live|现场|伴奏|纯音乐|remix|版|版本|mv|试听|cover|翻唱)", "", cleaned, flags=re.I)
    return normalize(cleaned)


def song_main_title(text: str) -> str:
    return re.sub(r"[\(（\[].*?[\)）\]]", "", text or "").strip()


def song_version_text(text: str) -> str:
    return " ".join(re.findall(r"[\(（\[]([^)\]）]+)[\)）\]]", text or "")).strip()


def netease_search_queries(title: str, artist: str) -> list[str]:
    title = title.strip()
    artist = artist.strip()
    main = song_main_title(title)
    queries = [
        f"{title} {artist}".strip(),
        f"{main} {artist}".strip(),
        title,
        main,
    ]
    seen: set[str] = set()
    unique: list[str] = []
    for query in queries:
        key = normalize(query)
        if query and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique


def apple_music_search_url(query: str) -> str:
    return f"https://music.apple.com/search?term={quote_plus(query.strip())}"


def song_external_url(title: str, artist: str = "") -> str:
    return apple_music_search_url(f"{title} {artist}".strip())


def apple_artwork_600(url: str) -> str:
    if not url:
        return ""
    return re.sub(r"/\d+x\d+bb\.(jpg|png|webp)$", r"/600x600bb.\1", url)


def fetch_apple_music_track(title: str, artist: str) -> dict[str, Any]:
    title = title.strip()
    artist = artist.strip()
    if not title:
        return {"ok": False, "provider": "apple_music", "error": "缺少歌曲名。"}
    key = (normalize(title), normalize(artist))
    cached = _apple_music_cache.get(key)
    if cached and time.time() - cached[0] < APPLE_MUSIC_CACHE_TTL_SECONDS:
        data = json.loads(json.dumps(cached[1], ensure_ascii=False))
        data["cached"] = True
        return data

    title_queries = [title]
    title_aliases = {
        "未来へ": "Mirai e",
    }
    if title in title_aliases:
        title_queries.append(title_aliases[title])
    artist_queries = [artist]
    if artist:
        parts = [
            part.strip()
            for part in re.split(r"[/／,，、&]| feat\.? | ft\.? | and |、", artist, flags=re.I)
            if part.strip()
        ]
        artist_queries.extend(parts[:3])
    artist_queries = list(dict.fromkeys(artist_queries))

    best = None
    best_score = -1
    best_query = f"{title} {artist}".strip()
    last_error = ""
    for title_query in title_queries:
        for artist_query in artist_queries:
            query = f"{title_query} {artist_query}".strip()
            url = "https://itunes.apple.com/search?" + urlencode({
                "term": query,
                "media": "music",
                "entity": "song",
                "limit": 10,
                "country": "CN",
            })
            try:
                with urlopen(Request(url, headers={"User-Agent": "MelodioDemo/1.0"}), timeout=8) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except Exception as exc:
                last_error = f"Apple Music 查询失败：{exc}"
                continue
            for item in payload.get("results") or []:
                if not isinstance(item, dict):
                    continue
                track_name = str(item.get("trackName") or "")
                artist_name = str(item.get("artistName") or "")
                if not track_name:
                    continue
                artist_score = artist_match_score(artist_query, artist_name)
                if artist_query and artist_score <= 0:
                    continue
                title_score = title_match_score(title_query, track_name)
                if title and title_score <= 0:
                    continue
                score = title_score + artist_score
                if not artist_query:
                    score += 1
                if score > best_score:
                    best = item
                    best_score = score
                    best_query = query

    threshold = 7 if artist else 5
    if not best or best_score < threshold:
        data = {
            "ok": False,
            "provider": "apple_music",
            "error": last_error or "未找到 Apple Music 曲目。",
            "query": best_query,
            "search_url": apple_music_search_url(best_query),
            "match_score": best_score,
        }
        _apple_music_cache[key] = (time.time(), data)
        return data

    preview_url = str(best.get("previewUrl") or "")
    track_url = str(best.get("trackViewUrl") or apple_music_search_url(best_query))
    artwork_url = apple_artwork_600(str(best.get("artworkUrl100") or ""))
    data = {
        "ok": bool(preview_url),
        "provider": "apple_music",
        "source": "Apple Music",
        "title": str(best.get("trackName") or title),
        "artist": str(best.get("artistName") or artist),
        "album": str(best.get("collectionName") or ""),
        "track_id": str(best.get("trackId") or ""),
        "song_url": track_url,
        "search_url": track_url,
        "url": track_url,
        "image_url": artwork_url,
        "cover_url": artwork_url,
        "stream_url": preview_url,
        "preview_url": preview_url,
        "duration_ms": int(best.get("trackTimeMillis") or 30000),
        "match_score": best_score,
        "error": "" if preview_url else "Apple Music 未返回 previewUrl。",
    }
    _apple_music_cache[key] = (time.time(), data)
    return json.loads(json.dumps(data, ensure_ascii=False))


def apple_music_artist_songs(artist: str, limit: int = 8) -> list[dict[str, Any]]:
    artist = canonical_artist_name(artist)
    if not artist:
        return []
    url = "https://itunes.apple.com/search?" + urlencode({
        "term": artist,
        "media": "music",
        "entity": "song",
        "limit": max(10, limit * 3),
        "country": "CN",
    })
    try:
        with urlopen(Request(url, headers={"User-Agent": "MelodioDemo/1.0"}), timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return []
    songs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    candidates: list[tuple[int, dict[str, Any]]] = []
    signature_titles = {normalize(title) for title in ARTIST_SIGNATURE_SONGS.get(artist, [])}
    for item in payload.get("results") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("trackName") or "").strip()
        artist_name = str(item.get("artistName") or "").strip()
        if not title or artist_match_score(artist, artist_name) <= 0:
            continue
        score = artist_match_score(artist, artist_name)
        if normalize(title) in signature_titles:
            score += 10
        if normalize(artist_name) == normalize(artist):
            score += 8
        elif normalize(artist) in normalize(artist_name):
            score += 4
        candidates.append((score, item))
    for _, item in sorted(candidates, key=lambda row: row[0], reverse=True):
        title = str(item.get("trackName") or "").strip()
        artist_name = str(item.get("artistName") or "").strip()
        key = (normalize(title), normalize(artist_name))
        if key in seen:
            continue
        seen.add(key)
        track_url = str(item.get("trackViewUrl") or song_external_url(title, artist_name))
        artwork_url = apple_artwork_600(str(item.get("artworkUrl100") or ""))
        songs.append(
            {
                "title": title,
                "artist": artist_name,
                "reason": f"Apple Music 搜索命中 {artist} 的真实歌曲。",
                "verified": True,
                "source": "apple_music_search",
                "url": track_url,
                "search_url": track_url,
                "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + artist_name)}",
                "image_url": artwork_url,
                "cover_url": artwork_url,
            }
        )
        if len(songs) >= limit:
            break
    return songs


def artist_match_score(expected_artist: str, candidate_artist: str) -> int:
    expected_artist = expected_artist.strip()
    candidate_artist = candidate_artist.strip()
    expected = normalize(expected_artist)
    if not expected_artist:
        return 1
    canonical = identify_artist(expected_artist) or expected_artist
    canonical_key = normalize(canonical)
    expected_aliases = {normalize(alias) for alias, artist in ARTIST_ALIASES.items() if artist == canonical}
    expected_aliases.add(canonical_key)
    expected_aliases.add(expected)
    candidate_names = [
        name.strip()
        for name in re.split(r"[/／,，、&]| feat\\.? | ft\\.? | and ", candidate_artist, flags=re.I)
        if name.strip()
    ]
    for name in candidate_names or [candidate_artist]:
        name_key = normalize(name)
        if name_key in expected_aliases:
            return 7
    candidate_key = normalize(candidate_artist)
    if candidate_key in expected_aliases:
        return 7
    return 0


def title_match_score(expected_title: str, candidate_title: str) -> int:
    expected = normalize(expected_title)
    candidate = normalize(candidate_title)
    expected_main = normalize_song_match_text(expected_title)
    candidate_main = normalize_song_match_text(candidate_title)
    expected_version = normalize(song_version_text(expected_title))
    candidate_version = normalize(song_version_text(candidate_title))
    score = 0
    if expected and expected == candidate:
        score += 9
    elif expected and (expected in candidate or candidate in expected):
        score += 7
    elif expected_main and expected_main == candidate_main:
        score += 8
    elif expected_main and (expected_main in candidate_main or candidate_main in expected_main):
        score += 5
    if expected_version and candidate_version:
        if expected_version == candidate_version:
            score += 3
        elif expected_version in candidate_version or candidate_version in expected_version:
            score += 2
    return score


def contains_any(query: str, words: list[str]) -> bool:
    q = query.lower()
    return any(word.lower() in q for word in words)


def identify_artist(query: str) -> str | None:
    query_text = str(query or "").strip()
    query_key = normalize(query_text)
    for alias, artist in ARTIST_ALIASES.items():
        if query_text.lower() == alias.lower() or query_key == normalize(alias):
            return artist
    canonical = canonical_artist_name(query)
    if canonical and canonical != query.strip():
        return canonical
    for item in linked_music_entities(query):
        if item.get("type") == "artist":
            return item.get("canonical") or None
    q = query.lower()
    compact = normalize(query)
    if not music_task_context(query):
        for song in SONGS:
            if normalize(song["artist"]) == query_key:
                return song["artist"]
            for alias in song.get("aliases", []):
                if normalize(alias) == query_key:
                    return song["artist"]
        return None
    for alias, artist in ARTIST_ALIASES.items():
        if alias.lower() in q or normalize(alias) in compact:
            return artist
    for song in SONGS:
        if song["artist"].lower() in q or normalize(song["artist"]) in compact:
            return song["artist"]
        for alias in song.get("aliases", []):
            if alias.lower() in q or normalize(alias) in compact:
                return song["artist"]
    return None


def excluded_artists_from_query(query: str) -> set[str]:
    if not contains_any(query, ["不要", "别", "排除", "不想听"]):
        return set()
    compact = normalize(query)
    excluded: set[str] = set()
    for alias, artist in ARTIST_ALIASES.items():
        if normalize(alias) and normalize(alias) in compact:
            excluded.add(normalize(canonical_artist_name(artist) or artist))
    for song in SONGS:
        artist = str(song.get("artist") or "")
        if normalize(artist) and normalize(artist) in compact:
            excluded.add(normalize(canonical_artist_name(artist) or artist))
    return excluded


def artist_signature_song_items(artist: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for title in ARTIST_SIGNATURE_SONGS.get(artist, []):
        local = next(
            (song for song in SONGS if song["artist"] == artist and normalize(song["title"]) == normalize(title)),
            None,
        )
        if local:
            traits = "、".join(local.get("traits", [])[:3])
            reason = f"这是 {artist} 的高认知代表作，{traits} 的特征很突出，适合优先展示。"
        else:
            reason = f"这是 {artist} 的高认知代表作，适合在艺人搜索里优先展示。"
        items.append(
            {
                "title": title,
                "artist": artist,
                "reason": reason,
                "verified": True,
                "source": "signature",
                "url": song_external_url(title, artist),
                "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + artist)}",
            }
        )
    return items


def is_hot_artist_search(query: str) -> bool:
    return not contains_any(query, ["冷门", "小众", "不火", "少人听", "宝藏", "其他"])


def prioritize_artist_signature_songs(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if analysis.get("intent") != "entity_search" or analysis.get("entity_type") != "artist":
        return groups
    artist = identify_artist(
        " ".join(
            [
                query,
                str(analysis.get("reference") or ""),
                str((analysis.get("target_entity") or {}).get("artist") or ""),
                str((analysis.get("target_entity") or {}).get("name") or ""),
            ]
        )
    )
    if not artist or not is_hot_artist_search(query):
        return groups

    signatures = artist_signature_song_items(artist)
    if not signatures:
        return groups

    ordered: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for song in signatures:
        key = (normalize(song["title"]), normalize(song["artist"]))
        ordered.append(song)
        seen.add(key)
        if len(ordered) >= 6:
            break

    for group in groups:
        for song in group.get("songs") or []:
            title = str(song.get("title") or "").strip()
            song_artist = str(song.get("artist") or "").strip()
            if not title or not song_artist:
                continue
            if artist.lower() not in song_artist.lower() and normalize(artist) not in normalize(song_artist):
                continue
            key = (normalize(title), normalize(song_artist))
            if key in seen:
                continue
            ordered.append(song)
            seen.add(key)
            if len(ordered) >= 8:
                break
        if len(ordered) >= 8:
            break

    return [{"title": f"{artist} · 代表作品", "songs": ordered}]


def flatten_group_songs(groups: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    songs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups or []:
        group_title = str(group.get("title") or "").strip()
        for song in group.get("songs") or []:
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            if not title:
                continue
            key = (normalize(title), normalize(artist))
            if key in seen:
                continue
            seen.add(key)
            songs.append(
                {
                    "title": title,
                    "artist": artist,
                    "reason": str(song.get("reason") or "").strip(),
                    "group": group_title,
                    "source": str(song.get("source") or "").strip(),
                }
            )
            if len(songs) >= limit:
                return songs
    return songs


def infer_program_title(query: str, analysis: dict[str, Any]) -> str:
    traits = analysis.get("traits") or []
    text = " ".join([query, str(analysis.get("reference") or ""), *[str(item) for item in traits]])
    candidates = [
        (["深夜", "夜晚", "凌晨", "半夜"], "夜半频率"),
        (["雨天", "下雨", "阴天"], "雨落窗边"),
        (["开车", "驾驶", "公路"], "公路夜航"),
        (["睡前", "助眠", "睡觉"], "入睡之前"),
        (["生日", "庆祝", "派对"], "今天值得庆祝"),
        (["浪漫", "情歌", "心动", "爱情"], "心动频道"),
        (["Dream Pop", "梦幻流行", "迷幻"], "梦境回声"),
        (["健身", "跑步", "训练", "热血"], "心跳加速"),
        (["相似", "类似", "像", "这种", "那种"], "相邻回声"),
    ]
    for words, title in candidates:
        if contains_any(text, words):
            return title
    if analysis.get("intent") == "entity_search":
        ref = str(analysis.get("reference") or "").strip()
        return f"{ref} 时间" if ref else "点歌时间"
    if analysis.get("intent") == "general_reco":
        return "随手调频"
    return "Melodio 片刻"


def song_line(song: dict[str, str]) -> str:
    return f"{song.get('title', '')} - {song.get('artist', '')}".strip(" -")


def dj_knowledge_key(title: str, artist: str) -> str:
    return f"{normalize(artist)}::{normalize(title)}"


def load_dj_knowledge_cache() -> dict[str, Any]:
    global _dj_knowledge_cache
    if _dj_knowledge_cache is not None:
        return _dj_knowledge_cache
    if DJ_KNOWLEDGE_CACHE_FILE.exists():
        try:
            data = json.loads(DJ_KNOWLEDGE_CACHE_FILE.read_text(encoding="utf-8"))
            _dj_knowledge_cache = data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            _dj_knowledge_cache = {}
    else:
        _dj_knowledge_cache = {}
    return _dj_knowledge_cache


def save_dj_knowledge_cache() -> None:
    cache = load_dj_knowledge_cache()
    try:
        DJ_KNOWLEDGE_CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.info("dj_knowledge_cache_save_failed error=%s", exc)


def cached_dj_knowledge(song: dict[str, Any]) -> dict[str, Any]:
    title = str(song.get("title") or "").strip()
    artist = str(song.get("artist") or "").strip()
    if not title or not artist:
        return {}
    cache = load_dj_knowledge_cache()
    value = cache.get(dj_knowledge_key(title, artist))
    return value if isinstance(value, dict) else {}


def wikipedia_summary(title: str, lang: str = "zh") -> str:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
    request = Request(url, headers={"User-Agent": "MelodioDemo/1.0"})
    with urlopen(request, timeout=DJ_KNOWLEDGE_FETCH_TIMEOUT_SEC) as response:
        data = json.loads(response.read().decode("utf-8"))
    extract = str(data.get("extract") or "").strip()
    return re.sub(r"\s+", " ", extract)


def build_dynamic_knowledge_from_summary(song: dict[str, Any], artist_summary: str, song_summary: str = "") -> dict[str, Any]:
    title = str(song.get("title") or "").strip()
    artist = str(song.get("artist") or "").strip()
    facts: list[str] = []
    for text in [song_summary, artist_summary]:
        if not text:
            continue
        for sentence in re.split(r"[。.!?？]", text):
            sentence = sentence.strip()
            if 12 <= len(sentence) <= 90:
                facts.append(sentence)
            if len(facts) >= 2:
                break
        if len(facts) >= 2:
            break
    if not facts:
        return {}
    first_fact = facts[0]
    return {
        "artist_profile": facts[1] if len(facts) > 1 else "",
        "song_background": first_fact,
        "mood_hook": "",
        "safe_to_say_facts": facts,
        "avoid_claims": ["不要编造发行年份、专辑、制作人、奖项或幕后故事"],
        "source": "wikipedia_summary",
        "title": title,
        "artist": artist,
        "updated_at": int(time.time()),
    }


def fetch_netease_hot_comments_for_song(title: str, artist: str, limit: int = DJ_KNOWLEDGE_COMMENT_LIMIT) -> list[str]:
    if limit <= 0:
        return []
    found = find_netease_song(title, artist)
    song_id = str(found.get("song_id") or "")
    if not song_id:
        return []
    payload, _ = netease_api_service_json("/comment/hot", {"id": song_id, "type": 0, "limit": limit})
    comments = payload.get("hotComments") if isinstance(payload.get("hotComments"), list) else []
    texts: list[str] = []
    for item in comments[:limit]:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        content = re.sub(r"\s+", " ", content)
        if 8 <= len(content) <= 90:
            texts.append(content)
    return texts


def summarize_comment_resonance(comments: list[str], song: dict[str, Any]) -> dict[str, Any]:
    if not comments:
        return {}
    joined = " ".join(comments)
    themes = [
        (["青春", "学生", "高中", "初中", "毕业", "校园", "同桌"], "它最容易把人带回学生时代：课桌、操场，还有那些当时没说出口的话"),
        (["前任", "分手", "喜欢的人", "暗恋", "遗憾", "错过", "想你"], "它接住的是想念和错过，像一段已经不再打扰、但偶尔还会想起的关系"),
        (["开车", "夜", "凌晨", "路上", "高速", "车窗"], "它适合一个人在夜路上听，车窗外很安静，心里也不用急着回答谁"),
        (["雨", "下雨", "阴天", "窗"], "不少人会把它放进雨天，像把话先交给窗外"),
        (["家", "妈妈", "爸爸", "父亲", "母亲", "故乡"], "它会让人想起家和故乡，像走了很远以后突然回头看了一眼"),
        (["孤独", "一个人", "失眠", "难过", "哭", "撑不住"], "它陪的是那种不想热闹、只想安静待一会儿的心情"),
        (["旅行", "远方", "云南", "湖", "山", "风"], "它像一个想去很久但还没出发的地方，先在歌里见过一次"),
    ]
    resonance: list[str] = []
    for keys, summary in themes:
        if contains_any(joined, keys) and summary not in resonance:
            resonance.append(summary)
        if len(resonance) >= 2:
            break
    if not resonance:
        sample = deterministic_choice(
            f"{song.get('title')}|{song.get('artist')}|comments",
            comments[: min(len(comments), 5)],
        )
        resonance.append(f"它像是在替一些人说这句话：{sample}")
    return {
        "comment_resonance": resonance,
        "audience_mood": resonance[0] if resonance else "",
        "comment_samples": comments[:3],
        "source": "netease_hot_comments",
    }


def fetch_and_cache_dj_knowledge(song: dict[str, Any], *, already_marked: bool = False) -> None:
    if not DJ_KNOWLEDGE_DYNAMIC_ENABLED:
        return
    title = str(song.get("title") or "").strip()
    artist = str(song.get("artist") or "").strip()
    if not title or not artist:
        return
    key = dj_knowledge_key(title, artist)
    cache = load_dj_knowledge_cache()
    if key in cache:
        return
    if not already_marked:
        _dj_knowledge_fetching.add(key)
    try:
        artist_summary = ""
        song_summary = ""
        for lang in ("zh", "en"):
            if not artist_summary:
                try:
                    artist_summary = wikipedia_summary(artist, lang)
                except Exception:
                    artist_summary = ""
            if not song_summary:
                try:
                    song_summary = wikipedia_summary(f"{title} ({artist})", lang)
                except Exception:
                    song_summary = ""
        knowledge = build_dynamic_knowledge_from_summary(song, artist_summary, song_summary)
        try:
            comment_knowledge = summarize_comment_resonance(fetch_netease_hot_comments_for_song(title, artist), song)
        except Exception as exc:
            logger.info("dj_knowledge_comment_fetch_failed artist=%r title=%r error=%s", artist, title, exc)
            comment_knowledge = {}
        if comment_knowledge:
            knowledge = {**knowledge, **comment_knowledge} if knowledge else {
                "artist_profile": "",
                "song_background": "",
                "mood_hook": "",
                "safe_to_say_facts": [],
                "avoid_claims": ["不要编造发行年份、专辑、制作人、奖项或幕后故事"],
                "title": title,
                "artist": artist,
                "updated_at": int(time.time()),
                **comment_knowledge,
            }
        if knowledge:
            cache[key] = knowledge
            save_dj_knowledge_cache()
            logger.info("dj_knowledge_cached artist=%r title=%r source=%s", artist, title, knowledge.get("source"))
    except Exception as exc:
        logger.info("dj_knowledge_fetch_failed artist=%r title=%r error=%s", artist, title, exc)
    finally:
        _dj_knowledge_fetching.discard(key)


def schedule_dj_knowledge_fetch(songs: list[dict[str, Any]]) -> None:
    if not DJ_KNOWLEDGE_DYNAMIC_ENABLED or DJ_KNOWLEDGE_LOOKUP_LIMIT <= 0:
        return
    try:
        get_running_loop()
    except RuntimeError:
        return
    for song in songs[:DJ_KNOWLEDGE_LOOKUP_LIMIT]:
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        if not title or not artist:
            continue
        key = dj_knowledge_key(title, artist)
        if key in _dj_knowledge_fetching or key in load_dj_knowledge_cache():
            continue
        _dj_knowledge_fetching.add(key)
        create_task(run_in_threadpool(fetch_and_cache_dj_knowledge, song, already_marked=True))


def segment_tag(segment_type: str) -> str:
    return {
        "cold_open": "COLD OPEN",
        "bridge": "BRIDGE",
        "quick_touch": "QUICK TOUCH",
        "back_announce": "BACK ANNOUNCE",
        "silence": "SILENCE",
    }.get(segment_type, "DJ")


def make_segment(
    segment_type: str,
    text: str,
    *,
    part: str = "",
    position: str = "immediate",
    track_index: int | None = None,
    after_track_index: int | None = None,
    before_track_index: int | None = None,
    reason: str = "",
) -> dict[str, Any]:
    if segment_type == "cold_open":
        text = compact_dj_speech(text, 70)
    elif segment_type == "bridge":
        text = compact_dj_speech(text, 45)
    elif segment_type in {"quick_touch", "back_announce"}:
        text = compact_dj_speech(text, 30)
    segment: dict[str, Any] = {
        "type": segment_type,
        "tag": segment_tag(segment_type),
        "position": position,
        "part": part,
        "text": text,
        "speech_text": text,
        "should_speak": bool(text),
        "audio": "",
        "reason": reason,
    }
    if track_index is not None:
        segment["trackIndex"] = track_index
    if after_track_index is not None:
        segment["afterTrackIndex"] = after_track_index
    if before_track_index is not None:
        segment["beforeTrackIndex"] = before_track_index
    if after_track_index is not None and before_track_index is not None:
        segment["route"] = f"{after_track_index + 1} → {before_track_index + 1}"
    return segment


def deterministic_choice(seed: str, options: list[str]) -> str:
    if not options:
        return ""
    index = random.Random(seed).randrange(len(options))
    return options[index]


def dj_context_traits(query: str, analysis: dict[str, Any]) -> list[str]:
    return [str(item) for item in (analysis.get("traits") or []) if str(item).strip()] or query_traits(query)


def dj_strategy_profile(query: str, analysis: dict[str, Any], songs_count: int = 0) -> dict[str, Any]:
    intent = str(analysis.get("intent") or "")
    entity_type = str(analysis.get("entity_type") or "")
    action = str(analysis.get("action") or "")
    text = " ".join(
        [
            query,
            str(analysis.get("reference") or ""),
            *[str(item) for item in (analysis.get("traits") or [])],
        ]
    )
    companion = contains_any(
        text,
        ["深夜", "凌晨", "夜晚", "一个人", "开车", "公路", "下雨", "雨天", "生日", "庆祝", "睡前", "助眠", "浪漫", "情歌", "失眠", "通勤"],
    )
    if intent == "entity_search" and (action == "play" or entity_type == "song"):
        return {
            "mode": "direct",
            "label": "精确点歌",
            "opening_segments": 1,
            "opening_chars": "15-30",
            "bridge_max": 0,
            "bridge_probability": 0.0,
            "allow_back_announce": False,
        }
    if intent == "entity_search":
        return {
            "mode": "catalog",
            "label": "艺人/作品搜索",
            "opening_segments": 1,
            "opening_chars": "25-40",
            "bridge_max": 0,
            "bridge_probability": 0.0,
            "allow_back_announce": False,
        }
    if intent == "similar_reco":
        return {
            "mode": "similar",
            "label": "相似推荐",
            "opening_segments": 1,
            "opening_chars": "40-70",
            "bridge_max": 1,
            "bridge_probability": 0.35,
            "allow_back_announce": False,
        }
    if intent == "filtered_reco":
        return {
            "mode": "companion" if companion else "curated",
            "label": "场景/情绪推荐" if companion else "限定推荐",
            "opening_segments": 1,
            "opening_chars": "40-70",
            "bridge_max": 1,
            "bridge_probability": 0.25 if companion else 0.12,
            "allow_back_announce": False,
        }
    if intent == "general_reco":
        return {
            "mode": "open",
            "label": "泛推荐",
            "opening_segments": 1,
            "opening_chars": "35-55",
            "bridge_max": 0,
            "bridge_probability": 0.0,
            "allow_back_announce": False,
        }
    return {
        "mode": "light",
        "label": "轻回应",
        "opening_segments": 1,
        "opening_chars": "20-35",
        "bridge_max": 0,
        "bridge_probability": 0.0,
        "allow_back_announce": False,
    }


def compact_song_reason(song: dict[str, Any]) -> str:
    reason = str(song.get("reason") or "").strip()
    if not reason:
        return ""
    reason = re.sub(r"\s+", " ", reason).strip("。")
    if len(reason) < 12 and not re.search(r"[，。；;,.]", reason):
        return ""
    if contains_any(reason, ["代表", "氛围", "风格", "标签", "匹配"]) and len(reason) < 16:
        return ""
    return reason[:56]


def song_knowledge_note(song: dict[str, Any]) -> str:
    title = str(song.get("title") or "").strip()
    artist = str(song.get("artist") or "").strip()
    if not title or not artist:
        return ""
    exact = DJ_MUSIC_KNOWLEDGE.get((artist, title))
    if exact:
        return exact
    title_key = normalize(title)
    artist_key = normalize(artist)
    for (known_artist, known_title), note in DJ_MUSIC_KNOWLEDGE.items():
        if normalize(known_artist) == artist_key and normalize(known_title) == title_key:
            return note
    cached = cached_dj_knowledge(song)
    if cached:
        background = str(cached.get("song_background") or "").strip()
        facts = cached.get("safe_to_say_facts") if isinstance(cached.get("safe_to_say_facts"), list) else []
        fact = str(facts[0]).strip() if facts else ""
        note = background or fact
        if note:
            return note[:120].rstrip("，。；; ") + "。"
    return ""


def song_comment_resonance(song: dict[str, Any]) -> str:
    cached = cached_dj_knowledge(song)
    audience_mood = str(cached.get("audience_mood") or "").strip()
    if audience_mood:
        return audience_mood[:90].rstrip("，。；; ") + "。"
    resonance = cached.get("comment_resonance") if isinstance(cached.get("comment_resonance"), list) else []
    if not resonance:
        return ""
    note = str(resonance[0]).strip()
    note = re.sub(r"^(评论里|高赞评论里|很多评论|不少评论|很多人会|很多人把)", "", note).strip("，, ")
    return note[:90].rstrip("，。；; ") + "。" if note else ""


def song_dj_detail(song: dict[str, Any]) -> str:
    return song_knowledge_note(song) or compact_song_reason(song) or song_sound_hint(song)


def song_mood_note(song: dict[str, Any], query: str = "", analysis: dict[str, Any] | None = None) -> str:
    text = " ".join(
        [
            query,
            str((analysis or {}).get("reference") or ""),
            *[str(item) for item in ((analysis or {}).get("traits") or [])],
            str(song.get("title") or ""),
            str(song.get("artist") or ""),
            str(song.get("group") or ""),
            str(song.get("reason") or ""),
        ]
    )
    patterns = [
        (["晴天", "青春", "学生", "校园", "遗憾"], ["有些歌不是让人回到过去，是提醒你：那时候没说出口的话，也算真的存在过。", "它适合那些想起某个人、但已经不用再打扰对方的时刻。"]),
        (["深夜", "凌晨", "夜晚", "开车", "公路"], ["夜路上最需要的不是热闹，是有人在旁边不多问。", "一个人开车的时候，歌不用太懂事，只要陪你把这段路走完。"]),
        (["下雨", "雨天", "阴天"], ["雨天适合听这种歌，因为它不会催你开心，只是陪你把心情放慢。", "有些潮湿的心事，不用急着晒干，先让它在歌里待一会儿。"]),
        (["睡前", "助眠", "失眠"], ["睡前听它，像把今天没整理完的事先放到床边，明天再说。", "它不会把你拽进情绪里，更像帮你把灯慢慢关小。"]),
        (["生日", "庆祝", "派对"], ["生日歌不一定都要很吵，有时候只是提醒你：今天可以对自己宽容一点。", "庆祝不一定是人很多，也可以是给自己留一首亮一点的歌。"]),
        (["浪漫", "情歌", "心动", "爱情"], ["心动最好的地方，是话还没说满的时候。", "这种歌适合那些不想讲大道理，只想把一个人想一会儿的时刻。"]),
        (["丧", "伤感", "难过", "emo"], ["难过的时候，歌不一定要把你拉起来，有时候先承认它在就够了。", "它适合那种不想解释、只想有人懂一下的心情。"]),
        (["泸沽湖", "云南", "地方", "山", "湖", "土地"], ["有些地方不是风景，是人心里一个可以暂时躲进去的角落。", "这种带着地方气味的歌，会让人想起路、风，还有一些没完全说完的故事。"]),
        (["张悬", "焦安溥", "宝贝", "喜欢"], ["她的歌常常像在很近的地方说话，轻轻一句，反而更容易让人心软。", "这种亲密不是热闹，是你突然觉得自己被温柔地看见了一下。"]),
    ]
    for keys, notes in patterns:
        if contains_any(text, keys):
            return deterministic_choice(text + "|mood", notes)
    return deterministic_choice(
        text + "|mood-default",
        ["有些歌的好处，是不用解释太多，第一句出来就知道它在陪哪一种心情。", "先让它进来，很多话不用说满，歌自己会把位置留出来。"],
    )


def performer_human_note(song: dict[str, Any]) -> str:
    artist = str(song.get("artist") or "").strip()
    title = str(song.get("title") or "").strip()
    text = f"{artist} {title}"
    notes = [
        (["周杰伦"], ["周杰伦最动人的地方，是他常把很普通的青春小事唱得像一部电影。", "他唱这种歌的时候不太像在告白，更像把旧照片递到你手里。"]),
        (["张悬", "焦安溥"], ["张悬的声音一直有种很近的距离感，好像不是唱给很多人，是刚好唱到你旁边。", "焦安溥写歌常常不急着给答案，她更像把一句话放在你手里，让你自己慢慢懂。"]),
        (["麻园诗人"], ["麻园诗人的歌里有一种云南乐队的真，不精致到发亮，但很容易让人相信。", "他们最动人的地方，是把山路、湖水和年轻人的心事唱在一起。"]),
        (["万青", "万能青年旅店"], ["万青像是在替一些城市里沉默的人说话，不大声，但后劲很长。", "他们的歌常常不是安慰人，而是让你知道：原来疲惫也可以被唱出来。"]),
        (["伍佰"], ["伍佰的浪漫很直，像一个不太会拐弯的人，偏偏唱出了很多人的心软。", "他唱情绪的时候不精致，但那种粗粝反而很像真实生活。"]),
        (["陈粒"], ["陈粒的歌常常像一个人在路上边走边想，锋利一点，也自由一点。", "她的声音里有一种不太讨好的坦白，所以很容易唱到心里的角落。"]),
        (["李宗盛"], ["李宗盛像一个坐下来陪你聊天的过来人，不急着劝，只是把很多话唱得很明白。", "他厉害的地方，是把成年人的难堪唱得不丢脸。"]),
        (["Billie Eilish"], ["Billie Eilish 常把声音放得很轻，但那种轻不是软，是有自己的态度。", "她像是在很小的房间里唱歌，却能让全世界的人听见自己的孤独。"]),
        (["赵雷"], ["赵雷很会写普通人的路和城市，像把路边听来的故事认真收好。", "他的歌不太急，像一个愿意听你把话说完的人。"]),
    ]
    for keys, options in notes:
        if contains_any(text, keys):
            return deterministic_choice(text + "|performer", options)
    if artist:
        return deterministic_choice(
            text + "|performer-default",
            [f"{artist} 的声音先不用被解释，听第一句就能知道它要把人带到哪里。", f"先听 {artist} 怎么开口，有时候唱歌的人一出声，气氛就已经定了。"],
        )
    return ""


def should_include_performer_note(query: str, analysis: dict[str, Any], song: dict[str, Any]) -> bool:
    intent = str(analysis.get("intent") or "")
    if intent == "entity_search":
        return True
    text = " ".join([query, str(analysis.get("reference") or ""), str(song.get("artist") or ""), str(song.get("reason") or "")])
    if contains_any(text, ["歌手", "声音", "音色", "唱腔", "声线", "张悬", "焦安溥", "周杰伦", "伍佰", "李宗盛", "Billie"]):
        return True
    return random.Random(f"{query}|{song.get('title')}|performer").random() < 0.45


def should_include_listener_aside(query: str, analysis: dict[str, Any], song: dict[str, Any]) -> bool:
    intent = str(analysis.get("intent") or "")
    action = str(analysis.get("action") or "")
    if intent == "entity_search" and action == "play":
        return True
    text = " ".join([query, str(analysis.get("reference") or ""), *[str(item) for item in (analysis.get("traits") or [])]])
    if contains_any(text, ["深夜", "凌晨", "夜晚", "一个人", "开车", "下雨", "雨天", "生日", "睡前", "失眠", "伤感", "难过", "浪漫", "心动", "想念"]):
        return True
    return random.Random(f"{query}|{song.get('title')}|aside").random() < 0.35


def join_dj_sentences(*parts: str) -> str:
    cleaned: list[str] = []
    for part in parts:
        text = re.sub(r"\s+", " ", str(part or "")).strip()
        if not text:
            continue
        text_key = normalize(text)
        if any(text_key and (text_key in normalize(existing) or normalize(existing) in text_key) for existing in cleaned):
            continue
        if text in cleaned:
            continue
        if text[-1] not in "。！？!?":
            text += "。"
        cleaned.append(text)
    return "".join(cleaned)


def overlapping_mood(a: str, b: str) -> bool:
    joined = f"{a} {b}"
    overlap_sets = [
        ["学生", "课桌", "操场", "青春", "没说出口"],
        ["夜路", "车窗", "一个人", "不急着回答"],
        ["云南", "山路", "湖", "远方"],
        ["雨", "窗外", "下雨"],
        ["想念", "错过", "遗憾"],
    ]
    return any(sum(1 for word in words if word in joined) >= 2 and contains_any(a, words) and contains_any(b, words) for words in overlap_sets)


def listener_aside(song: dict[str, Any], query: str = "", analysis: dict[str, Any] | None = None) -> str:
    text = " ".join(
        [
            query,
            str((analysis or {}).get("reference") or ""),
            *[str(item) for item in ((analysis or {}).get("traits") or [])],
            str(song.get("title") or ""),
            str(song.get("artist") or ""),
            str(song.get("reason") or ""),
        ]
    )
    options = [
        (["晴天", "青春", "学生", "校园", "遗憾"], ["你心里那个人，现在过得还好吗？", "有些名字很久不提，但一听到前奏，还是会在心里亮一下吧。"]),
        (["张悬", "焦安溥", "宝贝", "喜欢"], ["你有没有也遇到过那种人，没说很多话，却让你一直记得？", "如果今天有点累，就先把自己交给这句轻轻的声音。"]),
        (["深夜", "凌晨", "夜晚", "开车", "公路"], ["如果你现在也在路上，就别急着回答任何人。", "今晚先不用逞强，车窗外的风会陪你一会儿。"]),
        (["下雨", "雨天", "阴天"], ["你那边也在下雨吗？如果是，就让这首歌先替你把心情放慢。", "有些话不适合雨停以后再说，先放在歌里也可以。"]),
        (["睡前", "助眠", "失眠"], ["如果你还睡不着，先别怪自己，今天已经够长了。", "把手机放远一点也行，这首歌会轻一点。"]),
        (["生日", "庆祝"], ["今天是你的日子，哪怕只是一小会儿，也要站在自己这边。", "这一首先送给今天的你，不用很隆重，但要被好好对待。"]),
        (["浪漫", "情歌", "心动", "爱情"], ["你现在想到的那个人，是让你笑了一下，还是安静了一下？", "有些心动不用马上有答案，先让歌替你多停一秒。"]),
        (["丧", "伤感", "难过", "emo"], ["如果今天不太好，也不用急着变好。", "有些难过不用解释给所有人听，歌懂一点就够了。"]),
        (["泸沽湖", "云南", "地方", "山", "湖", "土地"], ["你有没有一个想去很久、但一直没出发的地方？", "有些地方还没去过，也会先在歌里见过。"]),
    ]
    for keys, asides in options:
        if contains_any(text, keys):
            return deterministic_choice(text + "|aside", asides)
    return deterministic_choice(
        text + "|aside-default",
        ["你先不用想太多，让这一首把现在的心情接住。", "如果刚好说中了你，就让它多停一会儿。"],
    )


def short_dj_detail(song: dict[str, Any], limit: int = 46) -> str:
    detail = song_dj_detail(song)
    detail = re.sub(r"\s+", " ", detail).strip("。；; ")
    if len(detail) <= limit:
        return detail
    cut = re.split(r"[，；;。]", detail)[0].strip()
    if 8 <= len(cut) <= limit:
        return cut
    return detail[:limit].rstrip("，；;、 ") + "..."


def song_sound_hint(song: dict[str, Any]) -> str:
    text = " ".join(
        [
            str(song.get("title") or ""),
            str(song.get("artist") or ""),
            str(song.get("group") or ""),
            str(song.get("reason") or ""),
        ]
    )
    patterns = [
        (["深夜", "夜", "睡前", "安静", "失眠"], ["声音不会太吵，像把灯调暗一点", "人声靠得很近，适合夜里听", "留了很多空白，不会打扰你"]),
        (["开车", "公路", "驾驶", "路上"], ["节奏很稳，适合跟着路灯往前走", "不会太抢，但会一直把车往前带", "像贴着车窗吹过来的一阵风"]),
        (["雨", "下雨", "阴天"], ["听起来有一点湿湿的雨天味道", "吉他和人声都很柔，像靠在窗边", "旋律像贴着玻璃慢慢滑下来"]),
        (["生日", "庆祝", "开心", "派对"], ["一进来就能把空气点亮", "副歌很容易跟着笑起来", "节奏会把人轻轻推到热闹里"]),
        (["浪漫", "情歌", "心动", "爱情"], ["人声很近，像把话说到耳边", "不急着推进，适合把心情放软", "旋律很细，像一句没说完的话"]),
        (["丧", "伤感", "难过", "emo"], ["不会把难过喊得太满", "有一点往下沉的感觉，但不压人", "像有人替你把那口气叹出来"]),
        (["爆发", "热血", "摇滚", "乐队"], ["鼓和吉他会把人慢慢推起来", "副歌一来，情绪会有个出口", "听着听着会想把音量开大一点"]),
        (["梦幻", "Dream Pop", "dream pop", "迷幻"], ["声音像蒙了一层雾", "人声轻轻浮在上面", "听起来像走进一盏蓝色小灯里"]),
        (["民谣", "地方", "云南", "土地", "方言"], ["有一点土地和山路的味道", "木吉他和人声都很近", "旋律里带着一点地方的风"],
        ),
    ]
    for keys, hints in patterns:
        if contains_any(text, keys):
            return deterministic_choice(text + "|sound", hints)
    return deterministic_choice(
        text + "|sound-default",
        ["人声一进来就很容易抓住心情", "旋律入口很清楚，第一句就能记住", "声音不急，留了点呼吸", "节奏会轻轻把人带起来"],
    )


def query_scene_action(query: str, analysis: dict[str, Any]) -> str:
    text = " ".join([query, str(analysis.get("reference") or ""), *[str(item) for item in (analysis.get("traits") or [])]])
    options = [
        (["深夜", "凌晨", "夜晚"], "把音量留在夜里"),
        (["开车", "驾驶", "公路"], "让歌贴着车窗往前走"),
        (["下雨", "雨天", "阴天"], "让节奏慢一点贴住窗外"),
        (["睡前", "助眠", "睡觉"], "把声音放轻，不打扰睡意"),
        (["生日", "庆祝"], "先把空气点亮"),
        (["浪漫", "情歌", "心动"], "把人声靠近一点"),
        (["丧", "伤感", "难过"], "让情绪沉下去，但不塌掉"),
        (["通勤", "上班", "路上"], "给路上的节奏留一点弹性"),
    ]
    for keys, action in options:
        if contains_any(text, keys):
            return action
    return "先给耳朵一个清楚的入口"


def dj_opening_segments(
    query: str,
    analysis: dict[str, Any],
    songs: list[dict[str, Any]],
    program_title: str,
) -> list[dict[str, Any]]:
    first = songs[0]
    intent = analysis.get("intent")
    profile = dj_strategy_profile(query, analysis, len(songs))
    traits = dj_context_traits(query, analysis)
    trait_text = "、".join(traits[:2])
    reason_text = compact_song_reason(first)
    group_text = str(first.get("group") or "").strip()
    sound_hint = song_sound_hint(first)
    knowledge_text = song_knowledge_note(first)
    comment_text = song_comment_resonance(first)
    detail_text = knowledge_text or comment_text or reason_text or sound_hint
    performer_text = performer_human_note(first) if should_include_performer_note(query, analysis, first) else ""
    base_mood_text = song_mood_note(first, query, analysis)
    if comment_text and not overlapping_mood(detail_text, comment_text):
        mood_text = comment_text
    elif comment_text and not knowledge_text:
        mood_text = comment_text
    else:
        mood_text = "" if overlapping_mood(detail_text, base_mood_text) else base_mood_text
    aside_text = listener_aside(first, query, analysis) if should_include_listener_aside(query, analysis, first) else ""
    scene_action = query_scene_action(query, analysis)
    fallback_first_reason = f"{sound_hint}。"
    seed = f"{query}|{first.get('title')}|{first.get('artist')}"
    if profile["mode"] in {"direct", "catalog"}:
        if intent == "entity_search" and analysis.get("action") == "play":
            text = deterministic_choice(
                seed + "|direct",
                [
                    f"收到，直接播《{first['title']}》。",
                    f"好，先听《{first['title']}》。",
                ],
            )
        else:
            text = deterministic_choice(
                seed + "|catalog",
                [
                    f"先听 {first['artist']}，从《{first['title']}》开始。",
                    f"开头放《{first['title']}》，先听声音本身。",
                ],
            )
        return [make_segment("cold_open", text, part="anchor", position="before_track", track_index=0)]
    scene_line = deterministic_choice(
        seed + "|scene",
        [
            f"{scene_action}。第一首放《{first['title']}》，让它先把气氛带起来。",
            f"从《{first['title']}》开始，贴着「{trait_text or analysis.get('reference') or query}」的颜色往里走。",
            f"这一轮不急着堆歌。先听《{first['title']}》，把空气慢慢调亮。",
        ],
    )
    opening_text = scene_line
    lines = [("anchor", opening_text)]
    return [
        make_segment("cold_open", text, part=part, position="before_track", track_index=0)
        for part, text in lines
        if text
    ]


def should_dj_bridge(query: str, current: dict[str, Any], nxt: dict[str, Any], idx: int, analysis: dict[str, Any]) -> bool:
    profile = dj_strategy_profile(query, analysis)
    if profile["bridge_max"] <= 0 or idx >= profile["bridge_max"]:
        return False
    if current.get("artist") == nxt.get("artist") and analysis.get("intent") == "entity_search":
        return False
    current_group = str(current.get("group") or "")
    next_group = str(nxt.get("group") or "")
    if current_group and next_group and current_group != next_group:
        return True
    if analysis.get("intent") in {"similar_reco", "filtered_reco"} and idx == 0:
        return True
    seed = f"{query}|{idx}|{current.get('title')}|{nxt.get('title')}|bridge"
    return random.Random(seed).random() < float(profile["bridge_probability"])


def dj_bridge_segment(query: str, current: dict[str, Any], nxt: dict[str, Any], idx: int, analysis: dict[str, Any]) -> dict[str, Any]:
    seed = f"{query}|{idx}|{current.get('title')}|{nxt.get('title')}"
    if not should_dj_bridge(query, current, nxt, idx, analysis):
        return make_segment(
            "silence",
            "",
            position="between_tracks",
            after_track_index=idx,
            before_track_index=idx + 1,
            reason=deterministic_choice(
                seed + "|reason",
                ["这两首歌的情绪可以直接贴上", "这里不需要解释，留一段呼吸", "让音乐自己完成转场"],
            ),
        )
    current_reason = compact_song_reason(current)
    next_reason = compact_song_reason(nxt)
    current_detail = short_dj_detail(current)
    next_detail = short_dj_detail(nxt)
    next_mood = song_mood_note(nxt, query, analysis)
    text = deterministic_choice(
        seed + "|bridge",
        [
            f"《{current['title']}》留下的是{current_detail or current_reason or '一个已经成形的情绪'}。下一首《{nxt['title']}》接得更近一点：{next_detail or next_reason or '让画面往前挪一步'}。{next_mood}",
            f"从《{current['title']}》到《{nxt['title']}》，不用讲太复杂。前一首把人带进来，后一首把心情往前放一小步。{next_mood}",
            f"刚才那首像把人放进一个场景，接下来《{nxt['title']}》会换一种说话方式。{next_mood}",
        ],
    )
    return make_segment(
        "bridge",
        text,
        part="handoff",
        position="between_tracks",
        after_track_index=idx,
        before_track_index=idx + 1,
    )


def apply_dj_strategy_to_segments(
    segments: list[dict[str, Any]],
    query: str,
    analysis: dict[str, Any],
    songs_count: int,
) -> list[dict[str, Any]]:
    profile = dj_strategy_profile(query, analysis, songs_count)
    max_opening = max(1, int(profile["opening_segments"]))
    max_bridge = max(0, int(profile["bridge_max"]))
    allow_back = bool(profile["allow_back_announce"])
    filtered: list[dict[str, Any]] = []
    opening_count = 0
    bridge_count = 0
    silence_keys: set[tuple[int, int]] = set()

    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_type = str(segment.get("type") or "")
        if segment_type == "cold_open":
            if opening_count >= max_opening:
                continue
            segment["position"] = "before_track"
            segment["trackIndex"] = 0
            filtered.append(segment)
            opening_count += 1
            continue
        if segment_type == "bridge":
            if bridge_count >= max_bridge:
                after_index = int(segment.get("afterTrackIndex") or bridge_count)
                before_index = int(segment.get("beforeTrackIndex") or after_index + 1)
                silence_keys.add((after_index, before_index))
                filtered.append(
                    make_segment(
                        "silence",
                        "",
                        position="between_tracks",
                        after_track_index=after_index,
                        before_track_index=before_index,
                        reason="DJ strategy keeps this transition silent",
                    )
                )
                continue
            filtered.append(segment)
            bridge_count += 1
            continue
        if segment_type == "back_announce":
            if allow_back:
                filtered.append(segment)
            continue
        if segment_type == "silence":
            after_index = int(segment.get("afterTrackIndex") or 0)
            before_index = int(segment.get("beforeTrackIndex") or after_index + 1)
            if (after_index, before_index) in silence_keys:
                continue
            silence_keys.add((after_index, before_index))
            filtered.append(segment)
            continue
        if segment_type == "quick_touch":
            filtered.append(segment)

    if not any(segment.get("type") == "cold_open" for segment in filtered) and songs_count > 0:
        return []
    return filtered


def build_claudio_style_dj_response(
    query: str,
    analysis: dict[str, Any],
    groups: list[dict[str, Any]],
    error: str = "",
) -> dict[str, Any]:
    songs = flatten_group_songs(groups, limit=5)
    intent = analysis.get("intent")
    reference = str(analysis.get("reference") or query)
    program_title = infer_program_title(query, analysis)
    profile = dj_strategy_profile(query, analysis, len(songs))
    if not songs:
        speech = deterministic_choice(
            f"{query}|empty",
            [
                "我先听到了，这一轮不动播放队列。",
                "收到，这个更像一句话，不需要硬塞进歌单。",
                "我先把这句话记下，音乐先不换。",
            ],
        )
        segments = [
            make_segment("quick_touch", speech, position="immediate", reason="speech-only or no playable songs"),
        ]
    else:
        segments = dj_opening_segments(query, analysis, songs, program_title)
        for idx in range(min(len(songs) - 1, max(1, int(profile["bridge_max"]) + 1))):
            segments.append(dj_bridge_segment(query, songs[idx], songs[idx + 1], idx, analysis))
        segments = apply_dj_strategy_to_segments(segments, query, analysis, len(songs)) or segments[:1]
        speech = " ".join(segment["speech_text"] for segment in segments if segment.get("speech_text"))
    return {
        "speech": speech,
        "display_text": speech,
        "tts_text": speech,
        "audio_url": "",
        "program_title": program_title,
        "play": [song_line(song) for song in songs[:3]],
        "segments": segments,
        "source": "internal_claudio_style",
        "error": error,
    }


def build_llm_dj_prompt(query: str, analysis: dict[str, Any], songs: list[dict[str, Any]], context: dict[str, Any] | None) -> str:
    ctx = context if isinstance(context, dict) else {}
    profile = dj_strategy_profile(query, analysis, len(songs))
    schedule_dj_knowledge_fetch(songs)
    song_text = "\n".join(
        "\n".join(
            [
                f"{idx}. {song['title']} - {song['artist']}",
                f"   分组: {song.get('group') or '无'}",
                f"   推荐理由: {song.get('reason') or '无'}",
                f"   可用轻背景/趣味说法: {song_knowledge_note(song) or '无；不要硬编故事，简单说听感即可'}",
                f"   缓存安全事实: {'；'.join(str(item) for item in (cached_dj_knowledge(song).get('safe_to_say_facts') or [])[:2]) or '无'}",
                f"   群体心境线索: {song_comment_resonance(song) or '无；不要为了共鸣硬编'}",
            ]
        )
        for idx, song in enumerate(songs)
    )
    recent_history = ctx.get("history") if isinstance(ctx.get("history"), list) else []
    history_text = "\n".join(
        f"- {str(item.get('role') or '')}: {str(item.get('content') or '')[:120]}"
        for item in recent_history[-4:]
        if isinstance(item, dict)
    )
    return f"""
你是 Melodio 的私人电台 DJ。你像一个会听歌、会聊天的朋友，不像乐评人。

你不是客服，不是推荐解释器，也不是另一个搜推模型。
上一阶段已经完成意图识别、实体抽取和歌曲召回；你接手的是第二阶段：把已确认歌曲自然地串成一小段可以听的电台。

你的职责：
- 给这段节目起一个短标题。
- 先判断入口是什么，情绪怎么走，哪一首负责转向，哪一段应该完全不说话。
- 再决定开场说什么：必须具体回应用户此刻的请求；如果有可靠的小背景或趣闻，可以轻轻带一句。
- 再决定哪些歌之间需要串场，哪些地方应该沉默：只有当串场能解释一次真实转向时才说。
- 让用户感觉是在和一个懂音乐但不卖弄的人聊天：文艺但不掉书袋，老少皆宜，能唤起一点共鸣，也有一点亲密互动感。
- 不要只聊歌本身。合适的时候可以照顾三件事：这首歌是什么感觉，唱歌的人像在怎么开口，正在听的人可能处在什么心情里。不合适就不要硬聊。

硬边界：
- 不要新增、删除、替换歌曲。
- 不要重新推荐歌曲。
- 不要输出不在“已确认歌曲列表”里的歌名或歌手。
- 不要解释意图分类，不要解释推荐系统，不要说“根据你的需求/为你推荐/以下是歌单”。
- 不要编造发行年份、专辑、制作人、奖项、幕后故事或歌手经历；只有“可用轻背景/趣味说法”里给出的内容，或常识性且确定的信息，才可以当事实说。
- 如果没有可靠趣闻，不要硬加；简单说这首歌给人的画面、心情或最容易听到的特点即可。
- 如果有“群体心境线索”，只能把它当作理解材料，用自然口吻说出来；不要说“评论里/高赞评论/大家都说/很多人评论”。
- 避免专业术语堆叠。可以说“像夏天晚风”“像城市短片”“声音很近”，少说“混响空间、低频、声压、叙事视角”。
- 每段最好落到一种普通人能懂的心境：想念、遗憾、松一口气、夜路、雨天、生日、告别、重新出发、一个人待一会儿。
- 不要把话说得像散文朗诵或哲学摘抄；句子短一点，像真人 DJ 在歌开始前轻轻说两句。
- 可以偶尔对听众说一句很轻的互动话，比如“你心里那个人，现在过得还好吗？”“如果你也在路上，就别急着回答任何人。”
- 互动不要太频繁，不要审问用户，不要连续问多个问题；一段里最多一个问句，语气要温柔、克制、像朋友。
- 可以聊唱歌的人，但不要像百科介绍。要说“这个人唱歌给人的感觉”，比如“他像把旧照片递给你”“她像在旁边轻轻说话”，而不是列履历。

用户输入：
{query}

意图结果：
{json.dumps(analysis, ensure_ascii=False)}

已确认歌曲列表，索引从 0 开始：
{song_text or "（无歌曲）"}

最近对话，可用于避免重复口吻：
{history_text or "（无）"}

本轮 DJ 编排策略：
- 类型：{profile["label"]} / {profile["mode"]}
- 开场：{profile["opening_segments"]} 段，整体建议 {profile["opening_chars"]} 个中文字。
- 当前歌曲多为 30 秒试听片段，cold_open 可以 1-2 句话，总长度 40-70 个中文字符。
- 串场：最多 {profile["bridge_max"]} 段；bridge 最多一句，25-45 个中文字符。多数相邻歌曲应该直接播放，不需要解释。
- 收束：{"可以在最后加一句很短的 after_track" if profile["allow_back_announce"] else "不要加 after_track/back_announce"}。
- 如果这是精确点歌、艺人搜索或作品搜索，只做轻开场，不要在歌曲之间插话。

输出严格 JSON，不要 Markdown：
{{
  "title": "2-6 个中文字的节目名",
  "play": ["必须来自已确认歌曲列表，格式：歌名 - 歌手"],
  "segments": [
    {{"type":"cold_open","part":"anchor|heart|turn|image|invitation","position":"before_track","trackIndex":0,"text":"一句自然中文"}},
    {{"type":"bridge","part":"pivot|handoff|contrast","position":"between_tracks","afterTrackIndex":0,"beforeTrackIndex":1,"text":"一句自然中文"}},
    {{"type":"back_announce","part":"landing","position":"after_track","trackIndex":2,"text":"一句自然中文"}},
    {{"type":"silence","position":"between_tracks","afterTrackIndex":1,"beforeTrackIndex":2,"text":""}}
  ],
  "reason": "内部节目编排理由"
}}

编排规则：
- 正常音乐请求必须有 cold_open，但只要 1 段；可以 1-2 句话，不要拆成多个小段。
- cold_open 必须回应用户请求里的具体场景/对象，并自然引出第一首歌；可以有一点画面感或音乐判断，但不要完整介绍歌单，不要提前讲后续歌曲。
- cold_open 第一段最重要，因为测试环境通常优先生成第一段开场 TTS；第一段必须独立成立，但不能拖过歌曲主体。
- 句子可以有一点画面感，但必须落在具体音乐、场景、歌手声线或歌曲顺序上。
- bridge 不是报幕。只有出现以下情况才加 bridge：情绪明显换挡、地域/年代/语言切换、从同歌手到外部相似、从私密到开阔、从低能到高能或反向降落。
- bridge 数量服从“本轮 DJ 编排策略”。每段 25-45 个中文字。只说明一个转场点，不要展开。
- 大多数相邻歌曲应该 silence。尤其是同歌手连续作品、同一种声线/氛围自然延续、用户只是查歌手作品时，优先沉默。
- 如果是点歌/艺人搜索，DJ 少说，15-30 字即可；场景推荐、相似推荐、生日/深夜/开车/雨天等陪伴型请求控制在 40-70 字。
- 不要使用固定模板句式，比如“先让《歌名》把入口打开”“先把声音放到合适的位置”“这几首不急着堆情绪”。
- 也不要说“贴着某某颜色往里走”这类抽象模板；要说清楚一个具体听感，如夜路感、雾感、地方气味、人声距离、吉他空间。
- 相似推荐必须点出和参照对象相似的具体原因；例如《泸沽湖》相似歌要提地方色彩、山水/远方感、民谣气质或同乐队延续，而不是泛泛说“相似”。
- 不要加 after_track/back_announce，除非上游明确要求 DJ 收束。
- 先写出整段节目最值得说的 1-2 个时刻，其余位置宁可 silence。不要在每两首之间都说话。
- 语言要像私人电台主持人：自然、亲近、有一点故事感。可以有画面，但不要空泛抒情。
- 不要写营销文案，不要堆形容词，不要泛泛说“很适合你”。
- 不要使用这些空话：“慢慢听”“交给音乐”“把耳朵打开”“很适合这个氛围”，除非后面接了具体音乐判断。
- 不要使用这些掉书袋表达：“命运”“存在”“虚无”“灵魂深处”“时代切片”“精神内核”“诗性表达”。
- 少说“这组歌/这一段/节目/频道/歌单”，多说具体歌曲、歌手、生活画面和容易理解的小感受。
- 可以用“你”来靠近听众，但不要替用户下结论；多用“如果”“也许”“有没有”，少用“你一定”“你就是”。
- 每段都检查一下：是不是只在介绍歌？如果自然，可以补一句“唱的人”或“听的人”；如果会显得硬，就宁可不补。
- 如果提到歌曲或歌手，必须精确来自已确认歌曲列表。
- 如果没有歌曲，输出一个 immediate quick_touch，不要创造歌单。
- segments 可以少，但不能空。
- play 字段只能使用已确认歌曲列表里的歌曲，顺序保持一致，数量不超过已确认歌曲数。

好串场示例风格：
- 深夜开车：不要只说“适合深夜”，要说第一首如何把车窗、速度、孤独感建立起来，下一首如何把情绪从私密推到更开阔。
- 相似歌曲：不要说“风格相似”，要说相似点在哪里，比如声线颗粒、吉他空间、鼓组推进、地域气质、叙事视角。
- 艺人/歌曲搜索：不要长篇发挥，明确点到第一首，然后让音乐自己占主角。
""".strip()


def normalize_llm_dj_response(data: dict[str, Any], query: str, analysis: dict[str, Any], songs: list[dict[str, Any]]) -> dict[str, Any]:
    song_titles = {normalize(song["title"]) for song in songs}
    song_artists = {normalize(song["artist"]) for song in songs}
    allowed_song_lines = [song_line(song) for song in songs]
    allowed_song_keys = {normalize(line): line for line in allowed_song_lines}
    raw_play = data.get("play") if isinstance(data.get("play"), list) else []
    play = []
    for item in raw_play:
        key = normalize(str(item or ""))
        if key in allowed_song_keys and allowed_song_keys[key] not in play:
            play.append(allowed_song_keys[key])
    if not play:
        play = allowed_song_lines[:3]
    raw_segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    segments: list[dict[str, Any]] = []
    allowed_types = {"cold_open", "bridge", "quick_touch", "back_announce", "silence"}
    allowed_positions = {"before_track", "between_tracks", "after_track", "immediate"}
    for idx, item in enumerate(raw_segments[:8]):
        if not isinstance(item, dict):
            continue
        segment_type = str(item.get("type") or "quick_touch")
        if segment_type not in allowed_types:
            segment_type = "quick_touch"
        position = str(item.get("position") or ("between_tracks" if segment_type in {"bridge", "silence"} else "immediate"))
        if position not in allowed_positions:
            position = "immediate"
        text = str(item.get("text") or "").strip()
        if segment_type == "silence":
            text = ""
        if text and is_template_dj_text(text):
            continue
        if text:
            normalized_text = normalize(text)
            mentions_unknown_song = bool(re.findall(r"《([^》]+)》", text)) and not any(title in normalized_text for title in song_titles)
            mentions_unknown_artist = False
            if song_artists and re.search(r"[A-Za-z\u4e00-\u9fff]", text):
                mentioned_known_artist = any(artist and artist in normalized_text for artist in song_artists)
                # Do not reject general prose that mentions no artist; reject only obvious "by ..." is hard across languages.
                mentions_unknown_artist = False if mentioned_known_artist or "《" in text else False
            if mentions_unknown_song or mentions_unknown_artist:
                continue
        track_index = item.get("trackIndex")
        after_index = item.get("afterTrackIndex")
        before_index = item.get("beforeTrackIndex")
        if not isinstance(track_index, int):
            track_index = 0 if position == "before_track" else None
        if not isinstance(after_index, int):
            after_index = idx - 1 if position == "between_tracks" and idx > 0 else None
        if not isinstance(before_index, int):
            before_index = after_index + 1 if isinstance(after_index, int) else None
        max_index = max(0, len(songs) - 1)
        if isinstance(track_index, int):
            track_index = max(0, min(track_index, max_index))
        if isinstance(after_index, int):
            after_index = max(0, min(after_index, max_index))
        if isinstance(before_index, int):
            before_index = max(0, min(before_index, max_index))
        segments.append(
            make_segment(
                segment_type,
                text,
                part=str(item.get("part") or ""),
                position=position,
                track_index=track_index,
                after_track_index=after_index,
                before_track_index=before_index,
                reason=str(item.get("reason") or ""),
            )
        )
    if not segments:
        return build_claudio_style_dj_response(query, analysis, [{"title": "推荐结果", "songs": songs}])
    segments = apply_dj_strategy_to_segments(segments, query, analysis, len(songs))
    if not segments:
        return build_claudio_style_dj_response(query, analysis, [{"title": "推荐结果", "songs": songs}])
    if analysis.get("intent") == "entity_search" and analysis.get("action") == "play" and songs:
        segments = [
            make_segment(
                "cold_open",
                f"收到，直接播《{songs[0]['title']}》。",
                part="anchor",
                position="before_track",
                track_index=0,
            )
        ]
    speech = " ".join(segment["speech_text"] for segment in segments if segment.get("speech_text"))
    title = str(data.get("title") or "").strip() or infer_program_title(query, analysis)
    return {
        "speech": speech,
        "display_text": speech,
        "tts_text": speech,
        "audio_url": "",
        "program_title": title,
        "play": play,
        "segments": segments,
        "source": "llm_claudio_style",
        "reason": str(data.get("reason") or ""),
        "error": "",
    }


def dj_text_mentions_unlisted_music(text: str, allowed_songs: list[dict[str, Any]]) -> bool:
    normalized_text = normalize(text)
    if not normalized_text:
        return False
    allowed_titles = [normalize(str(song.get("title") or "")) for song in allowed_songs]
    allowed_artists = [normalize(str(song.get("artist") or "")) for song in allowed_songs]
    bracket_titles = [normalize(match) for match in re.findall(r"《([^》]+)》", text)]
    for title in bracket_titles:
        if title and not any(title == allowed or title in allowed or allowed in title for allowed in allowed_titles):
            return True
    known_artists = [artist for artist in ARTIST_ALIASES.keys() if len(normalize(artist)) >= 2]
    for artist in known_artists:
        normalized_artist = normalize(artist)
        if normalized_artist and normalized_artist in normalized_text:
            if not any(normalized_artist == allowed or normalized_artist in allowed or allowed in normalized_artist for allowed in allowed_artists):
                return True
    return False


def align_dj_to_groups(dj: dict[str, Any], groups: list[dict[str, Any]], query: str, analysis: dict[str, Any]) -> dict[str, Any]:
    songs = flatten_group_songs(groups, limit=5)
    if not songs:
        return dj
    allowed_lines = [song_line(song) for song in songs]
    allowed_line_keys = {normalize(line): line for line in allowed_lines}
    raw_play = dj.get("play") if isinstance(dj.get("play"), list) else []
    play = []
    for item in raw_play:
        key = normalize(str(item or ""))
        if key in allowed_line_keys and allowed_line_keys[key] not in play:
            play.append(allowed_line_keys[key])
    if not play:
        play = allowed_lines[:3]

    segments = []
    for segment in dj.get("segments") or []:
        if not isinstance(segment, dict):
            continue
        text = str(segment.get("speech_text") or segment.get("text") or "")
        if text and dj_text_mentions_unlisted_music(text, songs):
            continue
        segments.append(segment)
    if not segments:
        fallback = build_claudio_style_dj_response(query, analysis, groups, "DJ text realigned to playable songs")
        return fallback
    has_spoken_cold_open = any(
        segment.get("type") == "cold_open"
        and segment.get("position") == "before_track"
        and int(segment.get("trackIndex") or 0) == 0
        and str(segment.get("speech_text") or segment.get("text") or "").strip()
        for segment in segments
        if isinstance(segment, dict)
    )
    if not has_spoken_cold_open:
        first = songs[0]
        reference = str(analysis.get("reference") or query).strip()
        reason = compact_song_reason(first)
        opening = (
            f"先从《{first['title']}》进，{first['artist']} 的声音会把「{reference}」这条线立起来。"
            f"{reason or '这首歌适合当这一段的入口。'}"
        )
        segments = [make_segment("cold_open", opening, part="anchor", position="before_track", track_index=0)] + segments

    segments = apply_dj_strategy_to_segments(segments, query, analysis, len(songs)) or segments[:1]
    speech = " ".join(str(segment.get("speech_text") or "") for segment in segments if segment.get("speech_text"))
    return {
        **dj,
        "play": play,
        "segments": segments,
        "speech": speech,
        "display_text": speech,
        "tts_text": speech,
    }


async def call_llm_dj_service(
    query: str,
    analysis: dict[str, Any],
    groups: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
    provider: str = "",
) -> dict[str, Any]:
    songs = flatten_group_songs(groups, limit=5)
    provider_id = (DJ_LLM_PROVIDER or provider or DEFAULT_PROVIDER).strip().lower()
    if provider_id not in PROVIDERS or not PROVIDERS[provider_id].get("key"):
        return build_claudio_style_dj_response(query, analysis, groups, "DJ LLM provider unavailable")
    prompt = build_llm_dj_prompt(query, analysis, songs, context)
    try:
        client, model = get_client(provider_id)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 Melodio 私人电台 DJ。只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.85,
        )
        data = extract_json(response.choices[0].message.content or "{}")
        return normalize_llm_dj_response(data, query, analysis, songs)
    except Exception as exc:
        return build_claudio_style_dj_response(query, analysis, groups, str(exc))


def build_llm_dialogue_prompt(query: str, analysis: dict[str, Any], answer: str, context: dict[str, Any] | None) -> str:
    ctx = context if isinstance(context, dict) else {}
    recent_history = ctx.get("history") if isinstance(ctx.get("history"), list) else []
    current_song = ctx.get("current_song") if isinstance(ctx.get("current_song"), dict) else {}
    playback_active = bool(ctx.get("playback_active"))
    current_song_text = "（无）"
    if current_song.get("title"):
        current_song_text = f"《{current_song.get('title')}》{current_song.get('artist') or ''}".strip()
    history_text = "\n".join(
        f"- {str(item.get('role') or '')}: {str(item.get('content') or '')[:120]}"
        for item in recent_history[-4:]
        if isinstance(item, dict)
    )
    return f"""
你是 Melodio 的实时 DJ 对话模块。你不是搜推模型，不新增歌曲，不改变意图分类。

你的任务：把上游已经确认的 answer 改写成一段适合直接语音播出的自然回应。

要求：
- 只回应当前问题，不推荐新歌，除非 answer 已经明确引导听歌。
- 闲聊要像私人电台 DJ，一两句话，温和自然，不油腻。
- 如果当前正在播放音乐，闲聊/百科/状态回应只是压低音乐后的叠加说话；不要暗示音乐已停止，不要说“接下来播放/第一首/马上开始”。
- 如果当前意图不是播放、切歌或新推荐，不要承诺会改变播放队列。
- 音乐百科要直接回答用户问题，可以使用你的通用音乐知识；不确定的事实要说“不确定/我不乱讲”，不要编造年份、成员、奖项或专辑细节。
- 音乐百科不要只说“我识别为百科问题”，要给出有信息量的介绍或解释。
- 播控指令不要发挥，保持“好的，现在为你...”这种固定执行感。
- 不要说“根据意图识别/系统判断/模型认为”。
- 不要说“播控指令、上下文引用、意图结果、上游答复”等系统词。
- 如果 answer 只是占位或能力说明，就把它自然说出来，不要扩写成百科结论。
- 不要输出 Markdown。

用户输入：
{query}

意图结果：
{json.dumps(analysis, ensure_ascii=False)}

上游答复：
{answer or "（无）"}

当前播放状态：
{"正在播放" if playback_active else "未检测到正在播放"}

当前歌曲：
{current_song_text}

最近对话：
{history_text or "（无）"}

输出严格 JSON：
{{
  "title": "2-6 个中文字标题",
  "text": "适合直接 TTS 播放的一段中文，30-120字"
}}
""".strip()


async def call_llm_dialogue_service(
    query: str,
    analysis: dict[str, Any],
    answer: str,
    context: dict[str, Any] | None = None,
    provider: str = "",
) -> dict[str, Any]:
    provider_id = (DJ_LLM_PROVIDER or provider or DEFAULT_PROVIDER).strip().lower()
    fallback_title = "Melodio 音乐百科" if analysis.get("intent") == "music_qa" else "Melodio"
    if analysis.get("domain") == "function" or analysis.get("intent") in {"control", "favorite"}:
        return speech_only_dj_response(answer or function_reply(query, str(analysis.get("intent") or "control")), program_title="Melodio 播控")
    if provider_id not in PROVIDERS or not PROVIDERS[provider_id].get("key"):
        return speech_only_dj_response(answer or chitchat_reply(query), program_title=fallback_title)
    prompt = build_llm_dialogue_prompt(query, analysis, answer, context)
    try:
        client, model = get_client(provider_id)
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是 Melodio 的实时 DJ 对话模块。只输出严格 JSON。"},
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.75,
        )
        data = extract_json(response.choices[0].message.content or "{}")
        text = safe_text(data.get("text") or answer or chitchat_reply(query), 700)
        title = safe_text(data.get("title") or fallback_title, 80)
        return speech_only_dj_response(text, program_title=title)
    except Exception as exc:
        logger.info("dj_dialogue_fallback provider=%s query=%r error=%s", provider_id, query, exc)
        return speech_only_dj_response(answer or chitchat_reply(query), program_title=fallback_title)


def fallback_dj_response(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]], error: str = "") -> dict[str, Any]:
    if os.getenv("DJ_STYLE", "claudio").strip().lower() == "claudio":
        return build_claudio_style_dj_response(query, analysis, groups, error)
    songs = flatten_group_songs(groups, limit=3)
    intent = analysis.get("intent")
    reference = str(analysis.get("reference") or query)
    if intent == "entity_search" and songs:
        speech = f"我先按代表作给你排好，从《{songs[0]['title']}》开始。"
    elif intent == "similar_reco" and songs:
        speech = f"我先沿着「{reference}」的气质排一组，第一首从《{songs[0]['title']}》进。"
    elif songs:
        speech = f"这组先给你排 {len(songs)} 首，第一首从《{songs[0]['title']}》开始。"
    else:
        speech = "我先把结果整理好了。"
    return {
        "speech": speech,
        "display_text": speech,
        "tts_text": speech,
        "audio_url": "",
        "program_title": "",
        "segments": [],
        "source": "fallback",
        "error": error,
    }


def pending_dj_response(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> dict[str, Any]:
    songs = flatten_group_songs(groups, limit=3)
    program_title = infer_program_title(query, analysis) if groups else "Melodio DJ"
    speech = "DJ 正在编排这一段。"
    if songs:
        speech = f"先从《{songs[0]['title']}》开始，DJ 串场稍后接入。"
    return {
        "speech": speech,
        "display_text": speech,
        "tts_text": "",
        "audio_url": "",
        "program_title": program_title,
        "play": [song_line(song) for song in songs],
        "segments": [],
        "source": "pending_async_dj",
        "pending": True,
        "error": "",
    }


def empty_dj_response() -> dict[str, Any]:
    return {
        "speech": "",
        "display_text": "",
        "tts_text": "",
        "audio_url": "",
        "program_title": "",
        "play": [],
        "segments": [],
        "source": "none",
        "pending": False,
        "error": "",
    }


def speech_only_dj_response(text: str, *, program_title: str = "Melodio", pending: bool = False) -> dict[str, Any]:
    speech = safe_text(text, 600)
    if not speech:
        return empty_dj_response()
    return {
        "speech": speech,
        "display_text": speech,
        "tts_text": speech,
        "audio_url": "",
        "program_title": program_title,
        "play": [],
        "segments": [
            make_segment("quick_touch", speech, position="immediate", reason="speech-only response"),
        ],
        "source": "speech_only",
        "pending": pending,
        "error": "",
    }


def attach_pending_dj(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("dj"):
        return result
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    answer = safe_text(result.get("answer"), 600)
    if analysis.get("domain") == "function" or analysis.get("intent") in {"control", "favorite"}:
        title = "Melodio 播控"
        speech = answer or function_reply(str(result.get("query") or ""), str(analysis.get("intent") or "control"))
        return {**result, "dj": speech_only_dj_response(speech, program_title=title)}
    if not groups and answer:
        title = "Melodio 回应"
        if analysis.get("intent") == "music_qa":
            title = "Melodio 音乐百科"
        elif analysis.get("domain") == "chitchat" or analysis.get("intent") in {"chitchat", "general_qa"}:
            title = "Melodio"
        return {**result, "dj": speech_only_dj_response(answer, program_title=title, pending=True)}
    return {**result, "dj": pending_dj_response(str(result.get("query") or ""), analysis, groups)}


def build_dj_context(query: str, analysis: dict[str, Any], context: dict[str, Any] | None) -> dict[str, str]:
    ctx = context if isinstance(context, dict) else {}
    return {
        "instruction": query,
        "weather": str(ctx.get("weather") or ""),
        "time": str(ctx.get("time") or ""),
        "location": str(ctx.get("location") or ""),
        "heartRate": str(ctx.get("heartRate") or ""),
        "scene": str(ctx.get("scene") or ""),
        "mood": str(ctx.get("mood") or ""),
        "language": "zh-CN",
    }


def parse_dj_service_response(data: dict[str, Any]) -> dict[str, Any]:
    segments = data.get("segments") if isinstance(data.get("segments"), list) else []
    opening = next((seg for seg in segments if isinstance(seg, dict) and seg.get("tag") == "OPENING"), None)
    spoken = opening or next(
        (seg for seg in segments if isinstance(seg, dict) and seg.get("should_speak") and seg.get("speech_text")),
        None,
    )
    speech = str((spoken or {}).get("speech_text") or "").strip()
    audio = str((spoken or {}).get("audio") or "").strip()
    return {
        "speech": speech,
        "display_text": speech,
        "tts_text": speech,
        "audio_url": audio,
        "program_title": str(data.get("programTitle") or ""),
        "segments": segments,
        "source": "external_dj_demo",
        "provider": str(data.get("provider") or ""),
        "model": str(data.get("model") or ""),
        "tts": str(data.get("tts") or ""),
    }


def tts_cache_path(text: str, voice_id: str, emotion: str = "", model: str | None = None) -> Path:
    key = hashlib.md5(
        json.dumps(
            {
                "provider": "minimax",
                "model": model or MINIMAX_TTS_MODEL,
                "voice": voice_id,
                "speed": MINIMAX_TTS_SPEED,
                "volume": MINIMAX_TTS_VOLUME,
                "pitch": MINIMAX_TTS_PITCH,
                "emotion": emotion,
                "text": text,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return TTS_CACHE_DIR / f"{key}.mp3"


def tts_public_url(path: Path) -> str:
    return f"/tts-cache/{quote_plus(path.name)}"


def minimax_emotion_for_segment(segment: dict[str, Any]) -> str:
    segment_type = str(segment.get("type") or "")
    text = str(segment.get("speech_text") or segment.get("text") or "")
    if contains_any(text, ["生日", "庆祝", "开心", "派对"]):
        return "happy"
    if contains_any(text, ["雨", "夜", "睡", "安静", "慢慢", "留白"]):
        return "calm"
    if segment_type == "bridge":
        return "calm"
    return os.getenv("MINIMAX_TTS_EMOTION", "calm").strip()


def extract_minimax_audio_bytes(payload: dict[str, Any]) -> bytes:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    audio_value = None
    for key in ("audio", "audio_file", "audio_base64", "audio_hex"):
        if isinstance(data, dict) and data.get(key):
            audio_value = data.get(key)
            break
    if not audio_value:
        extra_info = payload.get("extra_info") if isinstance(payload.get("extra_info"), dict) else {}
        if extra_info.get("audio"):
            audio_value = extra_info.get("audio")
    if not isinstance(audio_value, str) or not audio_value:
        raise RuntimeError("MiniMax TTS 未返回音频数据。")
    audio_text = audio_value.strip()
    try:
        return bytes.fromhex(audio_text)
    except ValueError:
        pass
    try:
        return base64.b64decode(audio_text)
    except binascii.Error as exc:
        raise RuntimeError("MiniMax TTS 音频格式无法解析。") from exc


def looks_like_audio_file(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1024:
        return False
    header = path.read_bytes()[:12]
    return header.startswith(b"ID3") or header.startswith(b"\xff\xfb") or header.startswith(b"\xff\xf3") or header.startswith(b"RIFF")


def synthesize_minimax_tts(text: str, segment: dict[str, Any] | None = None, *, voice_id_override: str = "") -> str:
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if not clean_text:
        return ""
    if not DJ_TTS_ENABLED or not MINIMAX_API_KEY:
        return ""
    voice_id = voice_id_override.strip() or os.getenv("MINIMAX_TTS_VOICE_ID", MINIMAX_TTS_VOICE_ID).strip() or MINIMAX_TTS_VOICE_ID
    emotion = minimax_emotion_for_segment(segment or {})
    out_path = tts_cache_path(clean_text, voice_id, emotion)
    if looks_like_audio_file(out_path):
        return tts_public_url(out_path)
    if out_path.exists():
        out_path.unlink(missing_ok=True)
    payload: dict[str, Any] = {
        "model": MINIMAX_TTS_MODEL,
        "text": clean_text,
        "stream": False,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": MINIMAX_TTS_SPEED,
            "vol": MINIMAX_TTS_VOLUME,
            "pitch": MINIMAX_TTS_PITCH,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
        "language_boost": MINIMAX_TTS_LANGUAGE_BOOST,
    }
    if emotion:
        payload["voice_setting"]["emotion"] = emotion
    endpoint = MINIMAX_TTS_ENDPOINT
    if MINIMAX_GROUP_ID and "GroupId=" not in endpoint:
        separator = "&" if "?" in endpoint else "?"
        endpoint = f"{endpoint}{separator}GroupId={quote_plus(MINIMAX_GROUP_ID)}"
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        content_type = response.headers.get("content-type", "")
        raw = response.read()
    if "audio" in content_type:
        out_path.write_bytes(raw)
        return tts_public_url(out_path)
    data = json.loads(raw.decode("utf-8"))
    if isinstance(data, dict) and data.get("base_resp", {}).get("status_code") not in (None, 0):
        raise RuntimeError(f"MiniMax TTS 错误：{data.get('base_resp')}")
    out_path.write_bytes(extract_minimax_audio_bytes(data))
    return tts_public_url(out_path)


def minimax_tts_configured() -> bool:
    return bool(MINIMAX_API_KEY and MINIMAX_TTS_WS_ENDPOINT)


def minimax_tts_ws_endpoint() -> str:
    endpoint = MINIMAX_TTS_WS_ENDPOINT
    if MINIMAX_GROUP_ID and "GroupId=" not in endpoint:
        separator = "&" if "?" in endpoint else "?"
        endpoint = f"{endpoint}{separator}GroupId={quote_plus(MINIMAX_GROUP_ID)}"
    return endpoint


def minimax_tts_ws_payload(event: str, text: str = "", voice_id: str = "", emotion: str = "") -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event": event,
    }
    if event == "task_start":
        payload.update({
            "model": MINIMAX_TTS_MODEL,
            "voice_setting": {
                "voice_id": voice_id or MINIMAX_TTS_VOICE_ID,
                "speed": MINIMAX_TTS_SPEED,
                "vol": MINIMAX_TTS_VOLUME,
                "pitch": MINIMAX_TTS_PITCH,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
            "language_boost": MINIMAX_TTS_LANGUAGE_BOOST,
        })
        if emotion:
            payload["voice_setting"]["emotion"] = emotion
    elif event == "task_continue":
        payload["text"] = text
    return payload


def minimax_tts_audio_from_ws_message(message: str | bytes) -> tuple[bytes, dict[str, Any]]:
    if isinstance(message, bytes):
        return message, {"event": "binary_audio"}
    data = json.loads(message)
    audio_value = ""
    if isinstance(data.get("data"), dict):
        audio_value = str(data["data"].get("audio") or "")
    if not audio_value:
        audio_value = str(data.get("audio") or "")
    if not audio_value:
        return b"", data
    try:
        return bytes.fromhex(audio_value), data
    except ValueError:
        try:
            return base64.b64decode(audio_value), data
        except binascii.Error:
            return b"", data


async def stream_minimax_tts_ws(text: str, voice_id: str | None = None):
    clean_text = safe_text(text, 1000)
    clean_voice = safe_text(voice_id or MINIMAX_TTS_VOICE_ID, 160) or MINIMAX_TTS_VOICE_ID
    if not clean_text:
        return
    if not minimax_tts_configured():
        raise RuntimeError("MiniMax TTS WebSocket 尚未配置 key。")
    try:
        import websockets
    except Exception as exc:
        raise RuntimeError(f"缺少 websockets 依赖：{exc}") from exc

    headers = {"Authorization": f"Bearer {MINIMAX_API_KEY}"}
    endpoint = minimax_tts_ws_endpoint()
    started_at = time.time()
    first_audio_at = 0.0
    async with websockets.connect(
        endpoint,
        additional_headers=headers,
        max_size=8 * 1024 * 1024,
        ping_interval=15,
    ) as ws:
        await ws.send(json.dumps(
            minimax_tts_ws_payload(
                "task_start",
                voice_id=clean_voice,
                emotion=os.getenv("MINIMAX_TTS_EMOTION", "calm").strip(),
            ),
            ensure_ascii=False,
        ))
        task_started = False
        while not task_started:
            message = await asyncio.wait_for(ws.recv(), timeout=12)
            audio, data = minimax_tts_audio_from_ws_message(message)
            event = str(data.get("event") or data.get("type") or "")
            if audio:
                first_audio_at = first_audio_at or time.time()
                yield audio
            if event in {"task_started", "task_start"} or data.get("task_id"):
                task_started = True
            if data.get("base_resp", {}).get("status_code") not in (None, 0):
                raise RuntimeError(f"MiniMax WS TTS 错误：{data.get('base_resp')}")

        await ws.send(json.dumps(minimax_tts_ws_payload("task_continue", text=clean_text), ensure_ascii=False))
        await ws.send(json.dumps(minimax_tts_ws_payload("task_finish"), ensure_ascii=False))

        while True:
            message = await asyncio.wait_for(ws.recv(), timeout=30)
            audio, data = minimax_tts_audio_from_ws_message(message)
            if audio:
                first_audio_at = first_audio_at or time.time()
                yield audio
                continue
            if data.get("base_resp", {}).get("status_code") not in (None, 0):
                raise RuntimeError(f"MiniMax WS TTS 错误：{data.get('base_resp')}")
            event = str(data.get("event") or data.get("type") or "")
            if event in {"task_finished", "task_finish", "task_closed"} or data.get("is_final") is True:
                break
    logger.info(
        "minimax_tts_ws_done chars=%s first_audio=%.3f total=%.3f voice=%s",
        len(clean_text),
        (first_audio_at - started_at) if first_audio_at else -1,
        time.time() - started_at,
        clean_voice,
    )


def doubao_tts_configured() -> bool:
    return bool((DOUBAO_TTS_API_KEY or (DOUBAO_TTS_APP_ID and DOUBAO_TTS_ACCESS_KEY)) and DOUBAO_TTS_ENDPOINT)


def doubao_tts_headers(req_id: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
        "X-Api-Resource-Id": DOUBAO_TTS_RESOURCE_ID,
        "X-Api-Request-Id": req_id,
    }
    if DOUBAO_TTS_API_KEY:
        headers["Authorization"] = f"Bearer {DOUBAO_TTS_API_KEY}"
        headers["X-Api-Key"] = DOUBAO_TTS_API_KEY
    if DOUBAO_TTS_APP_ID:
        headers["X-Api-App-Key"] = DOUBAO_TTS_APP_ID
    if DOUBAO_TTS_ACCESS_KEY:
        headers["X-Api-Access-Key"] = DOUBAO_TTS_ACCESS_KEY
    return headers


def clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def doubao_tts_payload(
    text: str,
    speaker: str | None = None,
    *,
    speech_rate: int | None = None,
    loudness_rate: int | None = None,
    emotion: str | None = None,
) -> dict[str, Any]:
    audio_params: dict[str, Any] = {
        "format": DOUBAO_TTS_FORMAT,
        "sample_rate": DOUBAO_TTS_SAMPLE_RATE,
        "speech_rate": clamp_int(
            DOUBAO_TTS_SPEECH_RATE if speech_rate is None else speech_rate,
            DOUBAO_TTS_SPEECH_RATE,
            -50,
            100,
        ),
        "loudness_rate": clamp_int(
            DOUBAO_TTS_LOUDNESS_RATE if loudness_rate is None else loudness_rate,
            DOUBAO_TTS_LOUDNESS_RATE,
            -50,
            100,
        ),
    }
    clean_emotion = safe_text(DOUBAO_TTS_EMOTION if emotion is None else emotion, 80)
    if clean_emotion:
        audio_params["emotion"] = clean_emotion
    return {
        "user": {
            "uid": "melodio-demo",
        },
        "req_params": {
            "text": text,
            "speaker": (speaker or DOUBAO_TTS_SPEAKER).strip() or DOUBAO_TTS_SPEAKER,
            "audio_params": audio_params,
        },
    }


def stream_doubao_tts(
    text: str,
    speaker: str | None = None,
    *,
    speech_rate: int | None = None,
    loudness_rate: int | None = None,
    emotion: str | None = None,
):
    clean_text = re.sub(r"\s+", " ", text or "").strip()
    if not clean_text:
        raise RuntimeError("请输入要合成的文本。")
    if not doubao_tts_configured():
        raise RuntimeError("豆包 TTS 尚未配置 key。")
    req_id = uuid.uuid4().hex
    payload = doubao_tts_payload(
        clean_text,
        speaker,
        speech_rate=speech_rate,
        loudness_rate=loudness_rate,
        emotion=emotion,
    )
    request = Request(
        DOUBAO_TTS_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=doubao_tts_headers(req_id),
        method="POST",
    )
    with urlopen(request, timeout=45) as response:
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            data = json.loads(response.read().decode("utf-8"))
            raise RuntimeError(f"豆包 TTS 返回异常：{data}")
        pending = b""
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    payload_line = json.loads(line.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"豆包 TTS 流数据无法解析：{line[:120]!r}") from exc
                code = int(payload_line.get("code") or 0)
                if code not in (0, 20000000):
                    raise RuntimeError(f"豆包 TTS 错误：{payload_line}")
                audio_data = str(payload_line.get("data") or "").strip()
                if audio_data:
                    yield base64.b64decode(audio_data)
                if payload_line.get("done") or code == 20000000:
                    return
        line = pending.strip()
        if line:
            payload_line = json.loads(line.decode("utf-8"))
            code = int(payload_line.get("code") or 0)
            if code not in (0, 20000000):
                raise RuntimeError(f"豆包 TTS 错误：{payload_line}")
            audio_data = str(payload_line.get("data") or "").strip()
            if audio_data:
                yield base64.b64decode(audio_data)


def doubao_tts_stream_url(text: str, speaker: str = "") -> str:
    clean_text = safe_text(text, 500)
    if not clean_text or not doubao_tts_configured():
        return ""
    params = {
        "text": clean_text,
        "speaker": safe_text(speaker or DOUBAO_TTS_SPEAKER, 120),
        "speech_rate": str(DOUBAO_TTS_SPEECH_RATE),
        "loudness_rate": str(DOUBAO_TTS_LOUDNESS_RATE),
    }
    if DOUBAO_TTS_EMOTION:
        params["emotion"] = DOUBAO_TTS_EMOTION
    return f"/doubao-tts/stream?{urlencode(params)}"


def attach_doubao_stream_tts(dj: dict[str, Any], *, all_segments: bool = False) -> bool:
    if not DJ_DOUBAO_TTS_OPENING_ENABLED or not doubao_tts_configured():
        return False
    segments = dj.get("segments") if isinstance(dj.get("segments"), list) else []
    attached = 0
    for segment in segments:
        if not isinstance(segment, dict) or segment.get("type") == "silence":
            continue
        text = str(segment.get("speech_text") or segment.get("text") or "").strip()
        if not text:
            continue
        audio_url = doubao_tts_stream_url(text)
        if not audio_url:
            return False
        segment["audio"] = audio_url
        segment["tts"] = "doubao_stream"
        segment.pop("tts_skipped", None)
        segment.pop("tts_error", None)
        if not dj.get("audio_url"):
            dj["audio_url"] = audio_url
        attached += 1
        if not all_segments:
            break
    if attached:
        dj["tts"] = "doubao_stream"
        dj["tts_generated_segments"] = attached
        dj["tts_max_segments"] = attached
        return True
    return False


def attach_doubao_opening_tts(dj: dict[str, Any]) -> bool:
    return attach_doubao_stream_tts(dj, all_segments=False)


def attach_tts_to_dj(dj: dict[str, Any]) -> dict[str, Any]:
    if attach_doubao_stream_tts(dj, all_segments=True):
        return dj
    doubao_opening_attached = False
    if not DJ_TTS_ENABLED or not MINIMAX_API_KEY or DJ_TTS_MAX_SEGMENTS <= 0:
        return dj
    segments = dj.get("segments") if isinstance(dj.get("segments"), list) else []
    first_audio = ""
    generated_count = 0
    eligible_segments: list[dict[str, Any]] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        if segment.get("type") == "silence":
            continue
        text = str(segment.get("speech_text") or segment.get("text") or "").strip()
        if not text:
            continue
        eligible_segments.append(segment)

    selected_segments: list[dict[str, Any]] = []
    opening = next((seg for seg in eligible_segments if seg.get("type") == "cold_open"), None)
    if opening:
        selected_segments.append(opening)
    if DJ_TTS_MAX_SEGMENTS > len(selected_segments):
        first_transition = next(
            (seg for seg in eligible_segments if seg not in selected_segments and seg.get("type") in {"bridge", "back_announce"}),
            None,
        )
        if first_transition:
            selected_segments.append(first_transition)
    if DJ_TTS_MAX_SEGMENTS > len(selected_segments):
        for segment in eligible_segments:
            if segment not in selected_segments:
                selected_segments.append(segment)
            if len(selected_segments) >= DJ_TTS_MAX_SEGMENTS:
                break

    selected_ids = {id(segment) for segment in selected_segments[:DJ_TTS_MAX_SEGMENTS]}
    for segment in eligible_segments:
        if segment.get("audio"):
            generated_count += 1
            if not first_audio:
                first_audio = str(segment.get("audio") or "")
            continue
        if generated_count >= DJ_TTS_MAX_SEGMENTS:
            segment["tts_skipped"] = "segment_limit"
            continue
        if id(segment) not in selected_ids:
            segment["tts_skipped"] = "deprioritized"
            continue
        text = str(segment.get("speech_text") or segment.get("text") or "").strip()
        try:
            audio_url = synthesize_minimax_tts(text, segment)
        except Exception as exc:
            segment["tts_error"] = str(exc)
            continue
        if audio_url:
            segment["audio"] = audio_url
            generated_count += 1
            if not first_audio:
                first_audio = audio_url
    if first_audio:
        dj["audio_url"] = first_audio
        if not doubao_opening_attached:
            dj["tts"] = "minimax"
        dj["tts_generated_segments"] = generated_count
        dj["tts_max_segments"] = DJ_TTS_MAX_SEGMENTS
    return dj


def call_dj_service(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]], context: dict[str, Any] | None = None) -> dict[str, Any]:
    if DJ_SERVICE_MODE != "external":
        return attach_tts_to_dj(build_claudio_style_dj_response(query, analysis, groups))
    if not DJ_SERVICE_ENABLED or not DJ_SERVICE_URL:
        return fallback_dj_response(query, analysis, groups)
    songs = flatten_group_songs(groups, limit=5)
    if not songs:
        return fallback_dj_response(query, analysis, groups)
    payload = {
        "songs": songs,
        "context": build_dj_context(query, analysis, context),
        "model": DJ_MODEL,
        "ttsVoice": DJ_TTS_VOICE,
    }
    request = Request(
        DJ_SERVICE_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=DJ_SERVICE_TIMEOUT_SEC) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return fallback_dj_response(query, analysis, groups, str(exc))
    if not isinstance(data, dict) or data.get("error"):
        return fallback_dj_response(query, analysis, groups, str(data.get("error") if isinstance(data, dict) else "DJ 服务返回异常"))
    dj = parse_dj_service_response(data)
    if not dj.get("speech"):
        fallback = fallback_dj_response(query, analysis, groups)
        dj["speech"] = fallback["speech"]
        dj["display_text"] = fallback["display_text"]
        dj["tts_text"] = fallback["tts_text"]
    return attach_tts_to_dj(dj)


async def attach_dj_response(
    result: dict[str, Any],
    context: dict[str, Any] | None = None,
    *,
    include_tts: bool = True,
) -> dict[str, Any]:
    if result.get("dj"):
        return result
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    if analysis.get("intent") not in SONG_INTENTS or not groups:
        if DJ_SERVICE_MODE == "llm":
            dj = await call_llm_dialogue_service(
                str(result.get("query") or ""),
                analysis,
                str(result.get("answer") or ""),
                context,
                str(result.get("provider") or ""),
            )
        else:
            dj = speech_only_dj_response(
                str(result.get("answer") or "") or chitchat_reply(str(result.get("query") or "")),
                program_title="Melodio",
            )
        return {**result, "dj": attach_tts_to_dj(dj) if include_tts else dj}
    if DJ_SERVICE_MODE == "llm":
        dj = await call_llm_dj_service(
            str(result.get("query") or ""),
            analysis,
            groups,
            context,
            str(result.get("provider") or ""),
        )
        dj = align_dj_to_groups(dj, groups, str(result.get("query") or ""), analysis)
        if include_tts:
            dj = await run_in_threadpool(attach_tts_to_dj, dj)
        return {**result, "dj": dj}
    dj = await run_in_threadpool(call_dj_service, str(result.get("query") or ""), analysis, groups, context)
    dj = align_dj_to_groups(dj, groups, str(result.get("query") or ""), analysis)
    if include_tts:
        dj = await run_in_threadpool(attach_tts_to_dj, dj)
    return {**result, "dj": dj}


async def dialogue_result_payload(query: str, provider: str, analysis: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    result = await attach_dj_response(
        {
            "query": query,
            "provider": provider,
            "analysis": analysis,
            "answer": "",
            "entities": [],
            "groups": [],
        },
        context,
        include_tts=True,
    )
    result["answer"] = safe_text(result.get("dj", {}).get("speech") or result.get("answer"), 700)
    result["mentioned_songs"] = extract_mentioned_songs_from_answer(result.get("answer") or "")
    return result


async def dialogue_payload_with_known_answer(query: str, provider: str, analysis: dict[str, Any], context: dict[str, Any] | None) -> dict[str, Any]:
    known_answer = answer_qa(query) if analysis.get("intent") == "music_qa" else ""
    if not known_answer:
        return await dialogue_result_payload(query, provider, analysis, context)
    mentioned_songs = extract_mentioned_songs_from_answer(known_answer)
    result = await attach_dj_response(
        {
            "query": query,
            "provider": provider,
            "analysis": analysis,
            "answer": known_answer,
            "entities": [],
            "groups": [],
            "mentioned_songs": mentioned_songs,
        },
        context,
        include_tts=True,
    )
    result["answer"] = safe_text(result.get("dj", {}).get("speech") or result.get("answer"), 700)
    result["mentioned_songs"] = mentioned_songs or extract_mentioned_songs_from_answer(result.get("answer") or "")
    return result


def extract_artist_song(query: str) -> tuple[str, str] | None:
    variety = re.search(
        r"(?:里|中)\s*(?P<artist>[\u4e00-\u9fffA-Za-z0-9· ._-]{1,24})\s*的\s*(?P<title>[^《》]{1,80}?)(?:这首歌|这首|歌曲|歌)?\s*$",
        query,
    )
    if variety:
        artist_raw = variety.group("artist").strip(" ，,。?？")
        title = variety.group("title").strip(" 《》。.，,?？")
        if "里" in artist_raw:
            artist_raw = artist_raw.rsplit("里", 1)[-1].strip(" ，,。?？")
        generic_artist_words = ["适合", "限定", "那种", "相关", "曲库", "舞台", "现场", "复古", "港乐", "摇滚", "说唱"]
        generic_title_words = ["歌", "歌曲", "作品", "老歌", "舞台", "曲库", "摇滚", "民谣", "舞曲", "情歌", "说唱", "港乐"]
        if (
            title
            and artist_raw
            and not contains_any(artist_raw, generic_artist_words)
            and not contains_any(title, generic_title_words)
        ):
            return identify_artist(artist_raw) or artist_raw, title

    possessive = re.match(r"^\s*(?P<artist>[^《》]{1,32})\s*的\s*《(?P<title>[^》]{1,80})》\s*$", query)
    if possessive:
        artist_raw = possessive.group("artist").strip()
        title = possessive.group("title").strip()
        artist = identify_artist(artist_raw) or artist_raw
        if title and artist:
            return artist, title

    dash = re.match(r"^\s*(?P<left>[^-–—]{1,80})\s*[-–—]\s*(?P<right>[^-–—]{1,80})\s*$", query)
    if dash:
        left = dash.group("left").strip()
        right = dash.group("right").strip()
        left_artist = identify_artist(left)
        right_artist = identify_artist(right)
        if left_artist and not right_artist:
            return left_artist, right
        if right_artist and not left_artist:
            return right_artist, left
        artist_raw, title = left, right
        artist = identify_artist(artist_raw) or artist_raw
        if title and artist:
            return artist, title
    return None


def provider_status() -> list[dict[str, Any]]:
    rows = [{"id": "local", "label": "本地复刻模型", "configured": True}]
    for provider_id, cfg in PROVIDERS.items():
        rows.append(
            {
                "id": provider_id,
                "label": cfg["label"],
                "configured": bool(cfg.get("key")),
                "model": cfg.get("model"),
            }
        )
    return rows


def default_provider_id(statuses: list[dict[str, Any]]) -> str:
    if DEFAULT_PROVIDER != "local" and any(
        item["id"] == DEFAULT_PROVIDER and item.get("configured") for item in statuses
    ):
        return DEFAULT_PROVIDER
    for provider_id in ("doubao", "deepseek", "gemini"):
        if any(item["id"] == provider_id and item.get("configured") for item in statuses):
            return provider_id
    return "local"


def get_client(provider: str) -> tuple[AsyncOpenAI, str]:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise RuntimeError(f"未知模型：{provider}")
    if not cfg.get("key"):
        label = cfg.get("label") or provider
        raise RuntimeError(f"{label} 未配置 API key，请在 melodio_demo_clone/.env 中填写。")
    if provider not in _clients:
        _clients[provider] = AsyncOpenAI(
            api_key=str(cfg["key"]),
            base_url=str(cfg["base_url"]) if cfg.get("base_url") else None,
        )
    return _clients[provider], str(cfg["model"])


def extract_json(text: str) -> dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_analysis_payload(data: dict[str, Any], query: str) -> dict[str, Any]:
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else data
    if not isinstance(analysis, dict):
        analysis = {}
    domain = analysis.get("domain") or "chitchat"
    intent = analysis.get("intent") or "general_qa"
    entity_type = analysis.get("entity_type") or "unknown"
    action = analysis.get("action") or ("answer" if intent in {"music_qa", "chitchat", "general_qa"} or domain == "chitchat" else "classify")
    if domain not in {"info_retrieval", "content_reco", "function", "creation", "chitchat"}:
        domain = "chitchat"
    if intent not in L2_INTENTS:
        intent = "general_qa"
    if entity_type not in {"song", "artist", "album", "playlist", "unknown"}:
        entity_type = "unknown"
    if action not in {"search", "play", "recommend", "answer", "classify"}:
        action = "classify"
    target_entity = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
    reference = canonical_artist_name(str(analysis.get("reference") or "")) or str(analysis.get("reference") or query)
    target_name = canonical_artist_name(str(target_entity.get("name") or "")) or str(target_entity.get("name") or "")
    target_artist = canonical_artist_name(str(target_entity.get("artist") or "")) or str(target_entity.get("artist") or "")
    if entity_type == "artist":
        reference = canonical_artist_name(reference) or reference
        target_name = canonical_artist_name(target_name or reference) or target_name or reference
        target_artist = canonical_artist_name(target_artist or reference) or target_artist or reference
    return {
        "domain": domain,
        "intent": intent,
        "entity_type": entity_type,
        "action": action,
        "identified": bool(analysis.get("identified", True)),
        "reference": reference,
        "target_entity": {
            "name": target_name,
            "artist": target_artist,
            "album": str(target_entity.get("album") or ""),
        },
        "traits": [str(item) for item in (analysis.get("traits") or [])][:8],
    }


def payload_from_analysis(analysis: dict[str, Any], answer: str = "") -> dict[str, Any]:
    return {"analysis": analysis, "answer": answer, "entities": [], "groups": [], "mentioned_songs": extract_mentioned_songs_from_answer(answer)}


def clean_model_payload(data: dict[str, Any], query: str, *, prioritize_playable: bool = True) -> dict[str, Any]:
    analysis = data.get("analysis") if isinstance(data.get("analysis"), dict) else {}
    domain = analysis.get("domain") or "content_reco"
    intent = analysis.get("intent") or "filtered_reco"
    entity_type = analysis.get("entity_type") or "unknown"
    action = analysis.get("action") or ("answer" if intent in {"music_qa", "chitchat", "general_qa"} or domain == "chitchat" else "recommend")
    if domain not in {"info_retrieval", "content_reco", "function", "creation", "chitchat"}:
        domain = "content_reco"
    if intent not in L2_INTENTS:
        intent = "filtered_reco"
    if entity_type not in {"song", "artist", "album", "playlist", "unknown"}:
        entity_type = "unknown"
    if action not in {"search", "play", "recommend", "answer", "classify"}:
        action = "recommend"
    target_entity = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
    reference = canonical_artist_name(str(analysis.get("reference") or "")) or str(analysis.get("reference") or query)
    target_name = canonical_artist_name(str(target_entity.get("name") or "")) or str(target_entity.get("name") or "")
    target_artist = canonical_artist_name(str(target_entity.get("artist") or "")) or str(target_entity.get("artist") or "")
    if entity_type == "artist":
        reference = canonical_artist_name(reference) or reference
        target_name = canonical_artist_name(target_name or reference) or target_name or reference
        target_artist = canonical_artist_name(target_artist or reference) or target_artist or reference
    analysis = {
        "domain": domain,
        "intent": intent,
        "entity_type": entity_type,
        "action": action,
        "identified": bool(analysis.get("identified", True)),
        "reference": reference,
        "target_entity": {
            "name": target_name,
            "artist": target_artist,
            "album": str(target_entity.get("album") or ""),
        },
        "traits": [str(item) for item in (analysis.get("traits") or [])][:8],
    }
    answer = str(data.get("answer") or "")
    entities = normalize_entities(data.get("entities") if isinstance(data.get("entities"), list) else [])
    groups = data.get("groups") if isinstance(data.get("groups"), list) else []
    if intent not in SONG_INTENTS or analysis["identified"] is False:
        groups = []
    normalized_groups = normalize_groups(groups, intent)
    forced_answer = ""
    analysis, normalized_groups, forced_answer = force_non_song_intent(query, analysis, normalized_groups)
    analysis, normalized_groups = enforce_counted_general_reco(query, analysis, normalized_groups)
    analysis, normalized_groups = enforce_artist_song_search(query, analysis, normalized_groups)
    analysis, normalized_groups = enforce_similar_song_reco(query, analysis, normalized_groups)
    analysis, normalized_groups = enforce_similar_artist_reco(query, analysis, normalized_groups)
    analysis, normalized_groups = enforce_artist_search(query, analysis, normalized_groups)
    normalized_groups = enforce_single_play_target(query, analysis, normalized_groups)
    normalized_groups = fill_empty_entity_song_result(query, analysis, normalized_groups)
    if analysis.get("action") == "play" and analysis.get("entity_type") == "song":
        normalized_groups = single_play_target_group(analysis) or normalized_groups
    normalized_groups = enrich_same_artist_groups_from_search(query, analysis, normalized_groups)
    normalized_groups = prioritize_artist_signature_songs(query, analysis, normalized_groups)
    normalized_groups = limit_recommendation_groups(
        normalized_groups,
        analysis,
        max_count=STREAM_PROBE_CANDIDATE_LIMIT,
    )
    if prioritize_playable:
        normalized_groups = prioritize_playable_groups(normalized_groups, analysis, query=query)
    if forced_answer:
        answer = forced_answer
    elif analysis.get("domain") == "chitchat" and not answer:
        answer = "我在听。你可以继续说，也可以告诉我现在想听什么。"
    elif analysis.get("intent") == "control":
        answer = function_reply(query, "control")
        normalized_groups = []
    elif analysis.get("intent") == "favorite":
        answer = function_reply(query, "favorite")
        normalized_groups = []
    return {
        "analysis": analysis,
        "answer": answer,
        "entities": entities,
        "groups": normalized_groups,
        "mentioned_songs": extract_mentioned_songs_from_answer(answer),
    }


def context_songs(context: dict[str, Any] | None, limit: int = 20) -> list[dict[str, str]]:
    if not isinstance(context, dict):
        return []
    songs: list[dict[str, str]] = []
    for group in context.get("last_groups") or []:
        if not isinstance(group, dict):
            continue
        group_title = str(group.get("title") or "")
        for song in group.get("songs") or []:
            if not isinstance(song, dict):
                continue
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            if title and artist:
                songs.append({"title": title, "artist": artist, "group": group_title})
            if len(songs) >= limit:
                return songs
    return songs


def context_mentioned_songs(context: dict[str, Any] | None, limit: int = 5) -> list[dict[str, str]]:
    if not isinstance(context, dict):
        return []
    songs: list[dict[str, str]] = []
    for song in context.get("mentioned_songs") or []:
        if not isinstance(song, dict):
            continue
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        if title and artist:
            songs.append({"title": title, "artist": artist, "group": str(song.get("group") or "上一轮提及")})
        if len(songs) >= limit:
            return songs
    return songs


def context_artist(context: dict[str, Any] | None) -> str:
    if not isinstance(context, dict):
        return ""
    current = context.get("current_song") if isinstance(context.get("current_song"), dict) else {}
    artist = str(current.get("artist") or "").strip()
    if artist:
        return artist
    songs = context_songs(context, limit=8)
    counts: dict[str, int] = {}
    for song in songs:
        artist = str(song.get("artist") or "").strip()
        if artist:
            counts[artist] = counts.get(artist, 0) + 1
    if not counts:
        return ""
    return max(counts.items(), key=lambda item: item[1])[0]


def is_context_artist_song_query(query: str) -> bool:
    q = query.strip()
    return bool(
        contains_any(q, ["她的歌", "他的歌", "ta的歌", "TA的歌"])
        or re.search(r"(?:这个|这位)(?:歌手|艺人)(?:的)?(?:歌|歌曲|作品)", q)
    )


def parse_song_index(query: str) -> int | None:
    if contains_any(query, ["下一首", "上一首", "换一首"]):
        return None
    q = query.strip()
    index_prefix = r"(?:第|列表|歌单|上(?:一)?轮|刚才|刚刚|播放|放|选|切到|听)"
    if not re.search(index_prefix, q):
        return None
    number_map = {
        "一": 1, "1": 1, "第一": 1,
        "二": 2, "两": 2, "2": 2, "第二": 2,
        "三": 3, "3": 3, "第三": 3,
        "四": 4, "4": 4, "第四": 4,
        "五": 5, "5": 5, "第五": 5,
        "六": 6, "6": 6, "第六": 6,
        "七": 7, "7": 7, "第七": 7,
        "八": 8, "8": 8, "第八": 8,
        "九": 9, "9": 9, "第九": 9,
        "十": 10, "10": 10, "第十": 10,
    }
    for token, value in sorted(number_map.items(), key=lambda item: len(item[0]), reverse=True):
        if token.startswith("第"):
            pattern = rf"{re.escape(token)}\s*(?:首|个|条)"
        else:
            pattern = rf"{index_prefix}\s*(?:那|这)?\s*{re.escape(token)}\s*(?:首|个|条)"
        if re.search(pattern, q):
            return value
    match = re.search(rf"{index_prefix}\s*(?:那|这)?\s*(\d{{1,2}})\s*(?:首|个|条)", q)
    if match:
        return int(match.group(1))
    return None


def selected_context_song(query: str, context: dict[str, Any] | None) -> dict[str, str] | None:
    songs = context_songs(context)
    mentioned_songs = context_mentioned_songs(context)
    if not songs and not mentioned_songs:
        return None
    index = parse_song_index(query)
    if index and 1 <= index <= len(songs):
        return songs[index - 1]
    if contains_any(query, ["这首", "当前", "正在放", "现在这首", "刚才那首", "刚刚那首", "它", "这歌"]):
        current = (context or {}).get("current_song") if isinstance(context, dict) else None
        if isinstance(current, dict) and current.get("title") and current.get("artist"):
            return {"title": str(current["title"]), "artist": str(current["artist"]), "group": "当前歌曲"}
        if mentioned_songs:
            return mentioned_songs[0]
        return songs[0]
    return None


def playback_recommendation_traits(query: str) -> list[str]:
    traits = feedback_reco_traits(query) or topic_reco_traits(query) or modifier_reco_traits(query) or query_traits(query)
    if contains_any(query, ["类似", "相似", "像", "同款", "这种", "那种"]):
        traits = list(dict.fromkeys([*traits, "相似延展"]))[:6]
    if contains_any(query, ["换一批", "换点", "不要", "别", "不想听"]):
        traits = list(dict.fromkeys([*traits, "重新编排"]))[:6]
    if contains_any(query, ["女生", "女声"]):
        traits = list(dict.fromkeys([*traits, "女声"]))[:6]
    if contains_any(query, ["男生", "男声"]):
        traits = list(dict.fromkeys([*traits, "男声"]))[:6]
    if contains_any(query, ["同歌手", "这个歌手", "这个艺人"]):
        traits = list(dict.fromkeys([*traits, "同艺人"]))[:6]
    return traits


def is_playback_recommendation_query(query: str, context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict) or not context_songs(context):
        return False
    if is_playback_control(query) or is_favorite_request(query) or parse_song_index(query):
        return False
    q = query.strip()
    if contains_any(q, ["类似", "相似", "像", "同款", "这种", "那种", "还有吗"]):
        return True
    if contains_any(q, ["更", "一点", "换一批", "换点", "不要", "别", "不想听", "来点", "推荐", "想听"]):
        return bool(playback_recommendation_traits(q) or contains_any(q, ["欢快", "安静", "丧", "伤感", "燃", "女生", "男生", "同歌手"]))
    return False


def rewrite_playback_recommendation_query(query: str, context: dict[str, Any] | None) -> str:
    current = context.get("current_song") if isinstance(context, dict) and isinstance(context.get("current_song"), dict) else {}
    current_text = ""
    if current.get("title"):
        current_text = f"当前播放《{current.get('title')}》- {current.get('artist', '')}"
    songs = context_songs(context, limit=5)
    list_text = "；".join(f"{song['title']} - {song['artist']}" for song in songs[:5])
    parts = ["这是播放中的追问，请基于上下文继续推荐。"]
    if current_text:
        parts.append(current_text)
    if list_text:
        parts.append(f"上一轮歌单：{list_text}")
    parts.append(f"用户追问：{query}")
    parts.append("请不要当作全新无上下文请求；返回 3-5 首真实歌曲，并体现这次相对上一轮的变化。")
    return "\n".join(parts)


def conversation_context_text(context: dict[str, Any] | None, query: str) -> str:
    if not isinstance(context, dict):
        return ""
    lines: list[str] = []
    interaction_mode = str(context.get("interaction_mode") or "").strip()
    if interaction_mode:
        mode_labels = {
            "fuzzy_query": "模糊 query：用户用场景/情绪/风格/用途描述想听什么，优先做推荐。",
            "playback_dialogue": "播放中对话：用户在引用当前播放或上一轮列表，优先结合上下文处理。",
            "exact_search": "精确搜索：用户在查找/播放明确歌曲、艺人、专辑或实体。",
        }
        lines.append(f"本轮链路：{mode_labels.get(interaction_mode, interaction_mode)}")
        if interaction_mode == "fuzzy_query":
            lines.append("链路要求：不要把场景/情绪/风格词误判为实体；返回 3-5 首多样歌曲。")
        elif interaction_mode == "playback_dialogue":
            lines.append("链路要求：优先理解“这首/第几首/换一批/更.../类似...”等上下文指代；不要当作无上下文全新搜索。")
        elif interaction_mode == "exact_search":
            lines.append("链路要求：优先判断实体类型；单曲起播只返回目标歌曲，艺人搜索返回该艺人作品，专辑搜索返回专辑实体。")
    history = context.get("history") if isinstance(context.get("history"), list) else []
    if history:
        lines.append("最近对话：")
        for item in history[-6:]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if role and content:
                lines.append(f"- {role}: {content[:120]}")
    current = context.get("current_song") if isinstance(context.get("current_song"), dict) else None
    if current and current.get("title"):
        lines.append(f"当前/最近选中歌曲：{current.get('title')} - {current.get('artist', '')}")
    songs = context_songs(context, limit=12)
    if songs:
        lines.append("上一轮歌曲列表，用户可能用“第几首/这首/刚才那首/换一批/更欢快”等引用：")
        for idx, song in enumerate(songs, start=1):
            lines.append(f"{idx}. {song['title']} - {song['artist']}（{song.get('group', '')}）")
    picked = selected_context_song(query, context)
    if picked:
        lines.append(f"本轮 query 疑似引用的上下文歌曲：{picked['title']} - {picked['artist']}")
    if contains_any(query, ["更", "一点", "换一批", "换点", "不要", "别", "类似", "相似"]):
        lines.append("如果本轮是追问或调整，请基于上一轮结果继续处理，而不是当作全新无上下文 query。")
    if is_playback_recommendation_query(query, context):
        lines.append("本轮是播放中重新推荐：必须返回 content_reco/filtered_reco 或 content_reco/similar_reco，并生成新的歌曲列表。")
    return "\n".join(lines)


def song_result_payload(query: str, song: dict[str, str], intent: str = "entity_search", action: str = "play") -> dict[str, Any]:
    analysis = {
        "domain": "info_retrieval" if intent == "entity_search" else "content_reco",
        "intent": intent,
        "entity_type": "song",
        "action": action,
        "identified": True,
        "reference": f"{song['title']} - {song['artist']}",
        "target_entity": {"name": song["title"], "artist": song["artist"], "album": ""},
        "traits": ["上下文引用", "多轮对话"],
    }
    return {
        "analysis": analysis,
        "answer": "",
        "entities": [],
        "groups": [
            {
                "title": "上下文单曲",
                "songs": [
                    {
                        "title": song["title"],
                        "artist": song["artist"],
                        "reason": "根据上一轮结果中的序号或指代命中这首歌。",
                        "verified": True,
                        "source": "conversation_context",
                        "url": song_external_url(song['title'], song['artist']),
                        "spotify_search": f"https://open.spotify.com/search/{quote_plus(song['title'] + ' ' + song['artist'])}",
                    }
                ],
            }
        ],
    }


def control_type_for_query(query: str) -> str:
    if is_current_playback_status_query(query):
        return "status"
    if re.search(r"(?:换|跳过|切|下)\s*[二两三四五六七八九十2-9]\s*首", query):
        return "next"
    if contains_any(query, ["下一首", "换一首", "换首", "换歌", "切歌", "跳过", "不要这首", "这首不好听", "不好听"]):
        return "next"
    if contains_any(query, ["上一首", "回到上一首", "切回上一首"]):
        return "previous"
    if contains_any(query, ["暂停", "停一下", "暂停播放", "停"]):
        return "pause"
    if contains_any(query, ["继续", "接着放", "恢复播放", "开始播放", "开始"]):
        return "resume"
    if contains_any(query, ["大声", "音量大", "声音大", "调大", "太小声", "再大声"]):
        return "volume_up"
    if contains_any(query, ["小声", "音量小", "声音小", "调小", "太大声", "再小声"]):
        return "volume_down"
    return "control"


def control_step_count_for_query(query: str) -> int:
    match = re.search(r"(?:换|跳过|切|下)\s*([二两三四五六七八九十2-9])\s*首", query)
    if not match:
        return 1
    raw = match.group(1)
    value = {
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }.get(raw)
    if value is None:
        try:
            value = int(raw)
        except ValueError:
            value = 1
    return max(1, min(10, value))


def control_result_payload(query: str, control_type: str, song: dict[str, str] | None = None) -> dict[str, Any]:
    reference = query
    target_entity = {"name": "", "artist": "", "album": ""}
    groups: list[dict[str, Any]] = []
    control_song = song if control_type == "play_song" else None
    if control_song:
        reference = f"{control_song['title']} - {control_song['artist']}"
        target_entity = {"name": control_song["title"], "artist": control_song["artist"], "album": ""}
        groups = [
            {
                "title": "播控目标",
                "songs": [
                    {
                        "title": control_song["title"],
                        "artist": control_song["artist"],
                        "reason": "根据上一轮播放列表中的序号或指代命中这首歌。",
                        "verified": True,
                        "source": "conversation_context",
                        "url": song_external_url(control_song['title'], control_song['artist']),
                        "spotify_search": f"https://open.spotify.com/search/{quote_plus(control_song['title'] + ' ' + control_song['artist'])}",
                    }
                ],
            }
        ]
    return {
        "analysis": {
            "domain": "function",
            "intent": "control",
            "entity_type": "song" if control_song else "unknown",
            "action": "play" if control_type == "play_song" else "classify",
            "identified": True,
            "reference": reference,
            "target_entity": target_entity,
            "traits": ["播控指令"] + (["上下文引用"] if control_song else []),
        },
        "answer": function_reply(query, "control"),
        "entities": [],
        "groups": groups,
        "control": {
            "type": control_type,
            "song": control_song or {},
            "count": control_step_count_for_query(query) if control_type in {"next", "previous"} else 1,
        },
    }


def is_new_music_request(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if contains_any(q, ["这首", "这首歌", "当前", "正在放", "现在这首", "刚才那首", "刚刚那首", "它", "这歌"]):
        return False
    if extract_artist_song(q) or is_similar_artist_query(q) or recent_song_search_artist(q):
        return True
    if extract_artist_request(q) or is_artist_song_request(q):
        return True
    if is_topic_reco_query(q) or is_modifier_reco_query(q) or is_generic_reco_query(q):
        return True
    artist = identify_artist(q)
    if artist and contains_any(q, ["推荐", "来", "听", "播放", "放", "找", "挑", "歌", "歌曲", "作品"]):
        return True
    return False


def classify_context_control(query: str, context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    if is_new_music_request(query):
        return None
    picked = selected_context_song(query, context)
    if picked and (
        parse_song_index(query)
        or contains_any(query, ["播放", "放一下", "放这", "来这", "起播"])
        or re.fullmatch(r"(放|播放|听|来)\s*(这首|当前|现在这首|刚才那首|刚刚那首|它|这歌)", query.strip())
    ):
        return control_result_payload(query, "play_song", picked)
    if is_playback_control(query):
        return control_result_payload(query, control_type_for_query(query), picked)
    return None


def classify_context_reference(query: str, context: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(context, dict):
        return None
    if is_new_music_request(query):
        return None
    picked = selected_context_song(query, context)
    if not picked:
        return None
    if is_favorite_request(query):
        return {
            "analysis": {
                "domain": "function",
                "intent": "favorite",
                "entity_type": "song",
                "action": "classify",
                "identified": True,
                "reference": f"{picked['title']} - {picked['artist']}",
                "target_entity": {"name": picked["title"], "artist": picked["artist"], "album": ""},
                "traits": [],
            },
            "answer": f"好的，已为你收藏《{picked['title']}》。",
            "entities": [],
            "groups": [],
        }
    if is_music_qa_query(query):
        return {
            "analysis": {
                "domain": "info_retrieval",
                "intent": "music_qa",
                "entity_type": "song",
                "action": "answer",
                "identified": True,
                "reference": f"{picked['title']} - {picked['artist']}",
                "target_entity": {"name": picked["title"], "artist": picked["artist"], "album": ""},
                "traits": [],
            },
            "answer": f"你问的是《{picked['title']}》- {picked['artist']}。这类上下文百科问题线上模型会结合上下文继续回答。",
            "entities": [],
            "groups": [],
        }
    if contains_any(query, ["类似", "相似", "像", "同款", "这种", "那种"]):
        analysis = {
            "domain": "content_reco",
            "intent": "similar_reco",
            "entity_type": "song",
            "action": "recommend",
            "identified": True,
            "reference": f"{picked['title']} - {picked['artist']}",
            "target_entity": {"name": picked["title"], "artist": picked["artist"], "album": ""},
            "traits": playback_recommendation_traits(query) or ["上下文引用", "相似延展"],
        }
        rewritten_query = f"和《{picked['title']}》- {picked['artist']} 相似的歌曲"
        return {
            "analysis": analysis,
            "answer": "",
            "entities": [],
            "groups": build_groups(rewritten_query, analysis, 5),
        }
    if contains_any(query, ["播放", "放", "听", "来", "起播", "第"]):
        return song_result_payload(query, picked, "entity_search", "play")
    return None


def classify_context_artist_search(query: str, context: dict[str, Any] | None, n: int) -> dict[str, Any] | None:
    if not isinstance(context, dict) or not is_context_artist_song_query(query):
        return None
    artist = context_artist(context)
    if not artist:
        return None
    analysis = {
        "domain": "info_retrieval",
        "intent": "entity_search",
        "entity_type": "artist",
        "action": "search",
        "identified": True,
        "reference": artist,
        "target_entity": {"name": artist, "artist": artist, "album": ""},
        "traits": artist_traits(artist),
    }
    return {
        "analysis": analysis,
        "answer": "",
        "entities": [],
        "groups": prioritize_artist_signature_songs(query, analysis, build_groups(query, analysis, n)),
    }


def normalize_entities(entities: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        etype = str(entity.get("type") or "unknown")
        title = str(entity.get("title") or entity.get("name") or "").strip()
        artist = str(entity.get("artist") or "").strip()
        if etype not in {"album", "artist", "song", "playlist"} or not title:
            continue
        search_query = str(entity.get("search_query") or f"{title} {artist}".strip())
        normalized.append(
            {
                "type": etype,
                "title": title,
                "artist": artist,
                "reason": str(entity.get("reason") or ""),
                "search_query": search_query,
                "tracks": [str(item) for item in (entity.get("tracks") or [])][:30],
                "url": apple_music_search_url(search_query),
                "spotify_search": f"https://open.spotify.com/search/{quote_plus(search_query)}",
            }
        )
    return normalized


def extract_mentioned_songs_from_answer(answer: str) -> list[dict[str, str]]:
    text = safe_text(answer, 1000)
    if not text:
        return []
    songs: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(title: str, artist: str) -> None:
        title = safe_text(title.strip(" 《》“”\"'，,。"), 120)
        artist = safe_text(artist.strip(" 《》“”\"'，,。"), 160)
        artist = re.sub(r"^(?:日本|韩国|欧美|华语)?(?:组合|乐队|歌手|艺人)", "", artist).strip()
        if not title or not artist:
            return
        key = (normalize(title), normalize(artist))
        if key in seen:
            return
        seen.add(key)
        songs.append({"title": title, "artist": artist, "reason": "上一轮回答中提到的歌曲。"})

    for match in re.finditer(r"(?:原曲|原版|原唱)\s*(?:是|为|来自|源自)?[^。；;\n]{0,40}?(?P<artist>[\u4e00-\u9fffぁ-んァ-ヶーA-Za-z0-9· ._-]{1,60})\s*的\s*《(?P<title>[^》]{1,80})》", text):
        add(match.group("title"), match.group("artist"))
    for match in re.finditer(r"《(?P<title>[^》]{1,80})》\s*(?:-|—|–|/|，|,|由|是由)\s*(?P<artist>[^。；;，,\n]{1,120})", text):
        artist = re.split(r"(?:演唱|唱|发布|发行|合作|带来|的)", match.group("artist"), maxsplit=1)[0]
        artist = re.sub(r"^(?:由|是由)\s*", "", artist).strip()
        add(match.group("title"), artist)
    for match in re.finditer(r"(?P<artist>[\u4e00-\u9fffぁ-んァ-ヶーA-Za-z0-9· ._-]{1,60})\s*的\s*《(?P<title>[^》]{1,80})》", text):
        artist = match.group("artist").strip(" ，,。")
        artist = re.split(r"(?:源自|来自|是|为|由|和|、|，|,)", artist)[-1].strip()
        add(match.group("title"), artist)
    for match in re.finditer(r"(?P<title>[A-Za-z0-9][A-Za-z0-9 '().:&+-]{1,80})\s*(?:-|—|–)\s*(?P<artist>[^。；;\n]{1,120})", text):
        add(match.group("title"), match.group("artist"))
    return songs[:5]


def enforce_single_play_target(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if analysis.get("action") != "play" or analysis.get("entity_type") != "song":
        return groups
    target = analysis.get("target_entity") or {}
    target_name = normalize(target.get("name") or analysis.get("reference") or "")
    target_artist = normalize(target.get("artist") or "")
    for group in groups:
        for song in group.get("songs") or []:
            title_ok = target_name and (target_name in normalize(song.get("title", "")) or normalize(song.get("title", "")) in target_name)
            artist_ok = not target_artist or target_artist in normalize(song.get("artist", "")) or normalize(song.get("artist", "")) in target_artist
            if title_ok and artist_ok:
                return [{"title": "单曲起播", "songs": [song]}]
    if groups and groups[0].get("songs"):
        return [{"title": "单曲起播", "songs": [groups[0]["songs"][0]]}]
    return groups


def fill_empty_entity_song_result(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if any(group.get("songs") for group in groups or []):
        return groups
    if analysis.get("intent") != "entity_search" or analysis.get("entity_type") != "song":
        return groups
    target = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
    title = str(target.get("name") or analysis.get("reference") or "").strip(" 《》。.，,")
    artist = str(target.get("artist") or "").strip()
    if not title:
        return groups
    local = next((song for song in SONGS if normalize(song.get("title", "")) == normalize(title)), None)
    if local and not artist:
        artist = str(local.get("artist") or "")
    reason = "用户明确点播/搜索了这首歌，模型已识别为单曲精搜。"
    return [
        {
            "title": "单曲精搜",
            "songs": [
                {
                    "title": title,
                    "artist": artist,
                    "reason": reason,
                    "verified": bool(artist),
                    "source": "analysis_entity",
                    "url": song_external_url(title, artist),
                    "spotify_search": f"https://open.spotify.com/search/{quote_plus((title + ' ' + artist).strip())}",
                }
            ],
        }
    ]


def single_play_target_group(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    if analysis.get("intent") != "entity_search" or analysis.get("entity_type") != "song" or analysis.get("action") != "play":
        return []
    target = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
    title = str(target.get("name") or analysis.get("reference") or "").strip(" 《》。.，,")
    artist = str(target.get("artist") or "").strip()
    if not title:
        return []
    local = next((song for song in SONGS if normalize(song.get("title", "")) == normalize(title)), None)
    if local and not artist:
        artist = str(local.get("artist") or "")
    return [
        {
            "title": "单曲起播",
            "songs": [
                {
                    "title": title,
                    "artist": artist,
                    "reason": "用户明确点播这首歌，直接起播目标单曲。",
                    "verified": bool(artist),
                    "source": "analysis_entity",
                    "url": song_external_url(title, artist),
                    "spotify_search": f"https://open.spotify.com/search/{quote_plus((title + ' ' + artist).strip())}",
                }
            ],
        }
    ]


def enforce_artist_song_search(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if analysis.get("intent") != "entity_search":
        return analysis, groups
    artist_song = extract_artist_song(query)
    if not artist_song:
        return analysis, groups
    artist, title = artist_song
    analysis = {
        **analysis,
        "domain": "info_retrieval",
        "intent": "entity_search",
        "entity_type": "song",
        "action": "search",
        "identified": True,
        "reference": f"{title} - {artist}",
        "target_entity": {"name": title, "artist": artist, "album": ""},
        "traits": analysis.get("traits") or ["单曲精搜", "明确歌手", "明确歌名"],
    }
    target_key = (normalize(title), normalize(artist))
    for group in groups:
        for song in group.get("songs") or []:
            song_key = (normalize(song.get("title", "")), normalize(song.get("artist", "")))
            if song_key == target_key or (
                normalize(title) in normalize(song.get("title", ""))
                and normalize(artist) in normalize(song.get("artist", ""))
            ):
                return analysis, [{"title": "单曲精搜", "songs": [song]}]
    return analysis, [
        {
            "title": "单曲精搜",
            "songs": [
                {
                    "title": title,
                    "artist": artist,
                    "reason": "用户明确给出了歌手和歌名，按单曲精确搜索返回。",
                    "verified": True,
                    "source": "query_entity",
                    "url": song_external_url(title, artist),
                    "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + artist)}",
                }
            ],
        }
    ]


def extract_artist_request(query: str) -> str | None:
    q = query.strip()
    if not q:
        return None
    if is_similar_artist_query(q):
        return None
    known_artist = identify_artist(q)
    if known_artist and contains_any(q, ["的歌", "歌曲", "作品", "来点", "想听", "播放", "听"]):
        return known_artist
    if modifier_reco_traits(q):
        return None

    patterns = [
        r"^(?:给我)?(?:推荐|来点|放点|找点|想听|听点|播放)?(?:一首|两首|几首|[1-5]首)?(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})的(?:歌|歌曲|作品)$",
        r"^(?:给我)?(?:推荐|来点|放点|找点|想听|听点|播放)(?:一首|两首|几首|[1-5]首)?(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})(?:的)?(?:歌|歌曲|作品)$",
        r"^(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})(?:歌曲|作品)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, q)
        if not match:
            continue
        artist = match.group("artist").strip()
        if not artist:
            continue
        candidate_query = f"{artist}歌曲"
        if re.match(r"^(好听|随便|来点|放点|找点)?(歌|歌曲|音乐)$", candidate_query) or topic_reco_traits(candidate_query):
            continue
        if modifier_reco_traits(candidate_query):
            continue
        if contains_any(artist, ["好听", "随便", "一些", "一点", "适合", "推荐", "歌曲", "音乐", "男女", "对唱"]):
            continue
        return identify_artist(artist) or artist
    return None


def is_artist_song_request(query: str) -> str | None:
    return extract_artist_request(query)


def is_similar_song_query(query: str) -> str | None:
    q = query.strip()
    if not contains_any(q, ["类似", "相似", "像", "同款", "这种", "那种", "差不多"]):
        return None
    ref = reference_from_song(q)
    if ref:
        return ref
    quoted = re.search(r"《([^》]{1,80})》", q)
    if quoted:
        return quoted.group(1).strip()
    if contains_any(q, ["这首", "当前", "刚才那首", "刚刚那首"]):
        return "当前歌曲"
    if not contains_any(q, ["和", "跟", "与"]):
        return None
    return None


def is_similar_artist_query(query: str) -> str | None:
    q = query.strip()
    if not contains_any(q, ["类似", "相似", "像", "接近"]):
        return None
    if not contains_any(q, ["艺人", "歌手", "乐队", "声音", "音色", "嗓音", "唱腔", "声线", "风格", "女声", "男声", "歌", "歌曲", "作品", "说唱", "摇滚", "民谣", "流行"]):
        return None
    artist = identify_artist(q)
    if artist:
        return artist
    patterns = [
        r"(?:类似|相似|像)(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})的(?:声音|音色|嗓音|唱腔|声线|风格)",
        r"(?:类似|相似|像)(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})的(?:歌|歌曲|作品)",
        r"(?:类似|相似|像)(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})的(?:[\u4e00-\u9fffA-Za-z0-9 .'\-&]{0,16})(?:歌|歌曲|作品|说唱|摇滚|民谣|流行|女声|男声)",
        r"(?:类似|相似|像)(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})(?:这样|这种|那种)(?:[\u4e00-\u9fffA-Za-z0-9 .'\-&]{0,16})(?:艺人|歌手|乐队|说唱|摇滚|民谣|流行|女声|男声)",
        r"(?:类似|相似|像)(?P<artist>[\u4e00-\u9fffA-Za-z0-9 .'\-&]{1,32})(?:这样|这种|那种)?的?(?:艺人|歌手|乐队)",
    ]
    for pattern in patterns:
        match = re.search(pattern, q)
        if match:
            candidate = match.group("artist").strip()
            candidate = re.split(r"(?:这种|那种|这样|那样|的)", candidate)[0].strip()
            candidate = re.sub(r"(?:声音|音色|嗓音|唱腔|声线|风格|中文说唱|说唱|摇滚|民谣|流行)$", "", candidate).strip()
            if candidate:
                return identify_artist(candidate) or candidate
    return None


def similar_artist_groups(artist: str) -> list[dict[str, Any]]:
    canonical_artist = canonical_artist_name(artist)
    profile = ARTIST_SIMILARITY_PROFILES.get(canonical_artist) or {}
    rows = SIMILAR_ARTIST_SONGS.get(canonical_artist) or []
    source = "similar_artist_memory"
    if not rows:
        rows = profile.get("songs") or []
        source = "similar_artist_profile"
    if not rows:
        rows = inferred_similar_artist_rows(artist)
        source = "similar_artist_inferred"
    if not rows:
        return []
    songs = []
    for song_artist, title in rows:
        priority = "、".join((profile.get("priority") or [])[:2])
        reason = f"它和 {artist} 处在相近的音色、编曲或圈层里，但不是只重复推荐 {artist} 本人的歌。"
        if source == "similar_artist_profile" and priority:
            reason = f"先按 {artist} 的{priority}圈层延展，再兼顾风格和情绪相近。"
        songs.append(
            {
                "title": title,
                "artist": song_artist,
                "reason": reason,
                "verified": True,
                "source": source,
                "url": song_external_url(title, song_artist),
                "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + song_artist)}",
            }
        )
    return [{"title": f"类似 {artist} 的歌曲", "songs": songs}]


def inferred_similar_artist_rows(artist: str, limit: int = 5) -> list[tuple[str, str]]:
    reference_artist = canonical_artist_name(artist)
    if not reference_artist:
        return []
    reference_key = normalize(reference_artist)
    reference_terms: set[str] = set()
    for song in SONGS:
        if normalize(canonical_artist_name(str(song.get("artist") or ""))) != reference_key:
            continue
        for field in ("traits", "genres", "moods", "scenes"):
            reference_terms.update(normalize(str(item)) for item in song.get(field, []) if str(item).strip())
    if not reference_terms:
        return []

    ranked: list[tuple[int, str, str]] = []
    for song in SONGS:
        song_artist = canonical_artist_name(str(song.get("artist") or ""))
        if not song_artist or normalize(song_artist) == reference_key:
            continue
        song_terms: set[str] = set()
        for field in ("traits", "genres", "moods", "scenes"):
            song_terms.update(normalize(str(item)) for item in song.get(field, []) if str(item).strip())
        overlap = len(reference_terms & song_terms)
        if overlap:
            ranked.append((overlap, song_artist, str(song.get("title") or "")))
    ranked.sort(key=lambda item: (-item[0], normalize(item[1]), normalize(item[2])))
    rows: list[tuple[str, str]] = []
    used_artists: set[str] = set()
    for _, song_artist, title in ranked:
        if not title or normalize(song_artist) in used_artists:
            continue
        used_artists.add(normalize(song_artist))
        rows.append((song_artist, title))
        if len(rows) >= limit:
            break
    return rows


def filter_similar_artist_candidate_groups(query: str, artist: str, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reference_artist = canonical_artist_name(artist)
    if not reference_artist or not groups:
        return groups
    reference_key = normalize(reference_artist)
    non_reference: list[dict[str, Any]] = []
    reference_songs: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for group in groups or []:
        for song in group.get("songs") or []:
            if not isinstance(song, dict):
                continue
            title = str(song.get("title") or "").strip()
            song_artist = str(song.get("artist") or "").strip()
            if not title or not song_artist:
                continue
            key = (normalize(title), normalize(song_artist))
            if key in seen:
                continue
            seen.add(key)
            if normalize(canonical_artist_name(song_artist)) == reference_key:
                reference_songs.append(song)
            else:
                non_reference.append(song)
    if len(non_reference) < 3:
        return groups

    selected: list[dict[str, Any]] = []
    used_artists: set[str] = set()
    for song in non_reference:
        artist_key = normalize(canonical_artist_name(str(song.get("artist") or "")))
        if artist_key in used_artists:
            continue
        used_artists.add(artist_key)
        selected.append(song)
        if len(selected) >= 4:
            break
    for song in non_reference:
        if len(selected) >= 5:
            break
        key = (normalize(str(song.get("title") or "")), normalize(str(song.get("artist") or "")))
        if any((normalize(str(item.get("title") or "")), normalize(str(item.get("artist") or ""))) == key for item in selected):
            continue
        selected.append(song)
    if len(selected) < 5 and reference_songs:
        selected.append(reference_songs[0])
    return [{"title": f"类似 {reference_artist} 的歌曲", "songs": selected[:5]}]


def enforce_similar_artist_reco(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if similar_song_profile(query, analysis):
        return analysis, groups
    artist = is_similar_artist_query(query)
    if not artist:
        return analysis, groups
    analysis = {
        **analysis,
        "domain": "content_reco",
        "intent": "similar_reco",
        "entity_type": "artist",
        "action": "recommend",
        "identified": True,
        "reference": artist,
        "target_entity": {"name": artist, "artist": artist, "album": ""},
        "traits": analysis.get("traits") or ["相似艺人", "音色相近", "声线参考"],
    }
    memory_groups = similar_artist_groups(artist)
    if memory_groups:
        return analysis, memory_groups
    return analysis, filter_similar_artist_candidate_groups(query, artist, groups)



def enforce_similar_song_reco(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if analysis.get("action") == "play":
        return analysis, groups
    if not contains_any(query, ["类似", "相似", "像", "同款", "这种", "那种", "差不多"]):
        return analysis, groups
    profile = similar_song_profile(query, analysis)
    if not profile:
        return analysis, groups
    analysis = {
        **analysis,
        "domain": "content_reco",
        "intent": "similar_reco",
        "entity_type": "song",
        "action": "recommend",
        "identified": True,
        "reference": f"{profile['title']} - {profile['artist']}",
        "target_entity": {"name": profile["title"], "artist": profile["artist"], "album": ""},
        "traits": list(dict.fromkeys([*(analysis.get("traits") or []), *(profile.get("traits") or [])]))[:8],
    }
    return analysis, similar_song_groups(query, analysis) or groups


def enforce_counted_general_reco(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if is_collection_limited_song_request(query) or is_similar_song_query(query) or extract_artist_song(query):
        return analysis, groups
    if not is_counted_open_music_request(query):
        return analysis, groups
    count = requested_song_count(query)
    analysis = {
        **analysis,
        "domain": "content_reco",
        "intent": "general_reco",
        "entity_type": "unknown",
        "action": "play" if count else "recommend",
        "identified": True,
        "reference": query,
        "target_entity": {"name": "", "artist": "", "album": ""},
        "traits": analysis.get("traits") or ["多样", "好入口", "流派覆盖", "不过分头部"],
    }
    if count:
        analysis["count"] = count
    return analysis, groups


def enforce_artist_search(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if is_collection_limited_song_request(query) or is_similar_song_query(query) or extract_artist_song(query):
        return analysis, groups
    artist = is_artist_song_request(query)
    if not artist:
        return analysis, groups
    analysis = {
        **analysis,
        "domain": "info_retrieval",
        "intent": "entity_search",
        "entity_type": "artist",
        "action": "search",
        "identified": True,
        "reference": artist,
        "target_entity": {"name": artist, "artist": artist, "album": ""},
        "traits": analysis.get("traits") or artist_traits(artist),
    }
    return analysis, groups


def force_non_song_intent(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    if is_favorite_request(query):
        return (
            {
                **analysis,
                "domain": "function",
                "intent": "favorite",
                "entity_type": "unknown",
                "action": "classify",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            [],
            function_reply(query, "favorite"),
        )
    if is_playback_control(query):
        return (
            {
                **analysis,
                "domain": "function",
                "intent": "control",
                "entity_type": "unknown",
                "action": "classify",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            [],
            function_reply(query, "control"),
        )
    recent_song_artist = recent_song_search_artist(query)
    if recent_song_artist:
        return (
            {
                **analysis,
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "artist",
                "action": "search",
                "identified": True,
                "reference": recent_song_artist,
                "target_entity": {"name": recent_song_artist, "artist": recent_song_artist, "album": ""},
                "traits": ["新歌", "近期发行", "艺人歌曲"],
            },
            groups,
            "",
        )
    if is_lyric_fragment_search(query):
        return (
            {
                **analysis,
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "song",
                "action": "search",
                "identified": False,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": ["歌词片段找歌"],
            },
            groups,
            "",
        )
    if is_similar_song_query(query):
        reference = is_similar_song_query(query) or analysis.get("reference") or query
        return (
            {
                **analysis,
                "domain": "content_reco",
                "intent": "similar_reco",
                "entity_type": "song",
                "action": "recommend",
                "identified": True,
                "reference": reference,
                "target_entity": {"name": reference, "artist": "", "album": ""},
                "traits": (analysis.get("traits") or query_traits(query) or ["参照歌曲", "相似氛围"])[:6],
            },
            groups,
            "",
        )
    artist_song = extract_artist_song(query)
    if artist_song:
        song_artist, song_title = artist_song
        return (
            {
                **analysis,
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "song",
                "action": "play" if contains_any(query, ["播放", "放", "给我播", "听", "来几首", "推荐"]) else "search",
                "identified": True,
                "reference": f"{song_title} - {song_artist}",
                "target_entity": {"name": song_title, "artist": song_artist, "album": ""},
                "traits": ["单曲精搜", "明确歌手", "明确歌名"],
            },
            groups,
            "",
        )
    if is_modifier_reco_query(query) and (
        analysis.get("domain") == "content_reco"
        or contains_any(query, ["推荐", "来点", "想听", "听点", "听些", "播放", "放点", "找点", "挑", "配乐", "适合听"])
    ):
        traits = topic_reco_traits(query) or query_traits(query) or modifier_reco_traits(query)
        return (
            {
                **analysis,
                "domain": "content_reco",
                "intent": "filtered_reco",
                "entity_type": "unknown",
                "action": "recommend",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": traits[:6],
            },
            groups,
            "",
        )
    if is_collection_limited_song_request(query):
        traits = topic_reco_traits(query) or query_traits(query) or modifier_reco_traits(query)
        return (
            {
                **analysis,
                "domain": "content_reco",
                "intent": "filtered_reco",
                "entity_type": "unknown",
                "action": "recommend",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": traits[:6] or ["限定来源", "曲库推荐"],
            },
            groups,
            "",
        )
    if is_current_playback_status_query(query):
        return (
            {
                **analysis,
                "domain": "function",
                "intent": "control",
                "entity_type": "unknown",
                "action": "classify",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            [],
            function_reply(query, "control"),
        )
    if is_music_qa_query(query):
        return (
            {
                **analysis,
                "domain": "info_retrieval",
                "intent": "music_qa",
                "entity_type": "unknown",
                "action": "answer",
                "identified": True,
                "reference": query,
                "target_entity": analysis.get("target_entity") or {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            [],
            "",
        )
    if is_state_only_chitchat(query):
        return (
            {
                **analysis,
                "domain": "chitchat",
                "intent": "general_qa",
                "entity_type": "unknown",
                "action": "answer",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            [],
            "",
        )
    return analysis, groups, ""


def skeleton_payload(query: str, provider: str) -> dict[str, Any]:
    analysis, answer = classify(query)
    analysis.setdefault("entity_type", "unknown")
    analysis.setdefault("action", "recommend" if analysis.get("intent") in SONG_INTENTS else "answer")
    analysis.setdefault("target_entity", {"name": "", "artist": "", "album": ""})
    if provider in PROVIDERS and analysis["intent"] in SONG_INTENTS:
        answer = "已识别意图，正在由线上模型生成推荐结果。"
    return {
        "query": query,
        "provider": provider,
        "analysis": analysis,
        "answer": answer,
        "entities": [],
        "groups": [],
    }


def normalize_groups(groups: list[Any], intent: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen_songs: set[tuple[str, str]] = set()
    for group in groups:
        if not isinstance(group, dict):
            continue
        songs = []
        for song in group.get("songs") or []:
            if not isinstance(song, dict):
                continue
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            if not title or not artist:
                continue
            song_key = (normalize(title), normalize(artist))
            if song_key in seen_songs:
                continue
            seen_songs.add(song_key)
            songs.append(
                {
                    "title": title,
                    "artist": artist,
                    "reason": str(song.get("reason") or "匹配本次自然语言音乐需求。"),
                    "verified": True,
                    "source": "llm",
                    "url": song_external_url(title, artist),
                    "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + artist)}",
                }
            )
        if songs:
            normalized.append({"title": str(group.get("title") or "推荐结果"), "songs": songs})
    return normalized


def song_diversity_key(song: dict[str, Any]) -> str:
    for field in ("source", "group"):
        value = str(song.get(field) or "").strip()
        if value:
            return value
    for field in ("genres", "moods", "scenes", "traits"):
        values = song.get(field)
        if isinstance(values, list) and values:
            return str(values[0])
    return "unknown"


def limit_recommendation_groups(
    groups: list[dict[str, Any]],
    analysis: dict[str, Any],
    *,
    min_count: int = 3,
    max_count: int = 5,
) -> list[dict[str, Any]]:
    if analysis.get("intent") not in {"general_reco", "filtered_reco", "similar_reco"}:
        return groups
    buckets: list[dict[str, Any]] = []
    seen_song: set[tuple[str, str]] = set()
    for group_index, group in enumerate(groups or []):
        group_title = str(group.get("title") or "推荐结果")
        songs = []
        for song in group.get("songs") or []:
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            if not title or not artist:
                continue
            key = (normalize(title), normalize(artist))
            if key in seen_song:
                continue
            seen_song.add(key)
            songs.append(song)
        if songs:
            buckets.append({"index": group_index, "title": group_title, "songs": songs})
    total_candidates = sum(len(bucket["songs"]) for bucket in buckets)
    if total_candidates <= max_count:
        return groups

    selected: list[tuple[str, dict[str, Any]]] = []
    used_artists: set[str] = set()
    used_diversity_keys: set[str] = set()

    def add_candidate(group_title: str, song: dict[str, Any], *, strict: bool) -> bool:
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        if not title or not artist:
            return False
        song_key = (normalize(title), normalize(artist))
        if any((normalize(item.get("title", "")), normalize(item.get("artist", ""))) == song_key for _, item in selected):
            return False
        artist_key = normalize(artist)
        diversity_key = normalize(song_diversity_key(song))
        if strict and artist_key in used_artists:
            return False
        selected.append((group_title, song))
        used_artists.add(artist_key)
        used_diversity_keys.add(diversity_key)
        return True

    max_bucket_len = max(len(bucket["songs"]) for bucket in buckets) if buckets else 0
    round_robin: list[tuple[str, dict[str, Any]]] = []
    for song_index in range(max_bucket_len):
        for bucket in buckets:
            if song_index < len(bucket["songs"]):
                round_robin.append((bucket["title"], bucket["songs"][song_index]))

    for strict in (True, False):
        for group_title, song in round_robin:
            if len(selected) >= max_count:
                break
            add_candidate(group_title, song, strict=strict)
        if len(selected) >= max_count:
            break

    if len(selected) < min_count:
        return groups[:1] if groups else []

    regrouped: dict[str, list[dict[str, Any]]] = {}
    for group_title, song in selected[:max_count]:
        regrouped.setdefault(group_title, []).append(song)
    return [{"title": title, "songs": songs} for title, songs in regrouped.items()]


def netease_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://music.163.com/",
    }
    if NETEASE_COOKIE:
        headers["Cookie"] = NETEASE_COOKIE
    if extra:
        headers.update(extra)
    return headers


def netease_api_json(path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    query = urlencode({**(params or {}), "timestamp": int(time.time() * 1000)})
    request = Request(
        f"https://music.163.com{path}?{query}",
        headers=netease_headers(),
    )
    with urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
        cookies = response.headers.get_all("Set-Cookie") or []
    return payload, cookies


def merge_set_cookie_values(raw_cookies: list[str]) -> str:
    pairs: list[str] = []
    seen: set[str] = set()
    for raw in raw_cookies:
        pair = raw.split(";", 1)[0].strip()
        if not pair or "=" not in pair:
            continue
        name = pair.split("=", 1)[0]
        if name in seen:
            continue
        seen.add(name)
        pairs.append(pair)
    return "; ".join(pairs)


def save_netease_cookie(cookie: str) -> None:
    global NETEASE_COOKIE
    cleaned = cookie.strip()
    if not cleaned:
        return
    NETEASE_COOKIE_FILE.write_text(cleaned, encoding="utf-8")
    persist_env_value("NETEASE_COOKIE", cleaned)
    NETEASE_COOKIE = cleaned


def persist_env_value(key: str, value: str) -> None:
    escaped = value.replace('"', '\\"')
    line = f'{key}="{escaped}"'
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    else:
        lines = []
    replaced = False
    updated: list[str] = []
    for existing in lines:
        if existing.strip().startswith(f"{key}="):
            if not replaced:
                updated.append(line)
                replaced = True
            continue
        updated.append(existing)
    if not replaced:
        if updated and updated[-1].strip():
            updated.append("")
        updated.append(line)
    ENV_FILE.write_text("\n".join(updated) + "\n", encoding="utf-8")


def refresh_netease_cookie() -> dict[str, Any]:
    if not NETEASE_COOKIE:
        return {"ok": False, "error": "未配置网易云 Cookie。"}
    try:
        payload, cookies = netease_api_json("/api/login/token/refresh", {})
        merged = merge_set_cookie_values(cookies)
        if merged:
            save_netease_cookie(f"{NETEASE_COOKIE}; {merged}")
        return {"ok": int(payload.get("code") or 0) == 200, "code": payload.get("code")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def request_json_url(url: str, timeout: float = 8) -> tuple[dict[str, Any], list[str]]:
    request = Request(url, headers=netease_headers())
    with urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
        cookies = response.headers.get_all("Set-Cookie") or []
    return payload, cookies


def ensure_netease_api() -> None:
    global _netease_api_process
    try:
        request_json_url(f"{NETEASE_API_URL}/login/status?timestamp={int(time.time() * 1000)}", timeout=2)
        return
    except Exception:
        pass
    if _netease_api_process and _netease_api_process.poll() is None:
        return
    log_path = STATE_DIR / "netease_api.log"
    log_file = log_path.open("a", encoding="utf-8")
    _netease_api_process = subprocess.Popen(
        ["npx", "-y", "NeteaseCloudMusicApi"],
        cwd=str(BASE_DIR),
        stdout=log_file,
        stderr=log_file,
        start_new_session=True,
    )
    deadline = time.time() + 20
    last_error = ""
    while time.time() < deadline:
        try:
            request_json_url(f"{NETEASE_API_URL}/login/status?timestamp={int(time.time() * 1000)}", timeout=2)
            return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.8)
    raise RuntimeError(f"网易云登录服务启动失败：{last_error}。日志：{log_path}")


def netease_api_service_json(path: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], list[str]]:
    ensure_netease_api()
    query = urlencode({**(params or {}), "timestamp": int(time.time() * 1000)})
    return request_json_url(f"{NETEASE_API_URL}{path}?{query}", timeout=10)


def netease_search_songs(search_query: str, limit: int = 20) -> list[dict[str, str]]:
    params = urlencode({"s": search_query, "type": 1, "limit": limit})
    request = Request(
        f"https://music.163.com/api/search/get/web?{params}",
        headers=netease_headers(),
    )
    with urlopen(request, timeout=6) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = ((payload.get("result") or {}).get("songs") or [])
    songs: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("name") or "").strip()
        artists = row.get("artists") or []
        artist = " / ".join(str(item.get("name") or "") for item in artists if isinstance(item, dict)).strip()
        song_id = str(row.get("id") or "")
        if title and artist:
            songs.append({"title": title, "artist": artist, "song_id": song_id})
    return songs


def netease_candidate_rows(search_query: str, limit: int = 20) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def add_row(row: dict[str, Any], source: str) -> None:
        song_id = str(row.get("id") or "")
        title = str(row.get("name") or "").strip()
        raw_artists = row.get("ar") or row.get("artists") or []
        artist = " / ".join(str(item.get("name") or "") for item in raw_artists if isinstance(item, dict)).strip()
        album_obj = row.get("al") or row.get("album") or {}
        album = str(album_obj.get("name") or "").strip() if isinstance(album_obj, dict) else ""
        image_url = ""
        if isinstance(album_obj, dict):
            image_url = str(
                album_obj.get("picUrl")
                or album_obj.get("pic_url")
                or album_obj.get("img80x80")
                or album_obj.get("img1v1Url")
                or ""
            ).strip()
        if not song_id or not title or song_id in seen_ids:
            return
        seen_ids.add(song_id)
        rows.append(
            {
                "id": song_id,
                "name": title,
                "artists": [{"name": name.strip()} for name in artist.split("/") if name.strip()],
                "album": {"name": album, "picUrl": image_url},
                "_matched_query": search_query,
                "_search_source": source,
            }
        )

    try:
        payload, _ = netease_api_service_json("/cloudsearch", {"keywords": search_query, "type": 1, "limit": limit})
        for row in ((payload.get("result") or {}).get("songs") or []):
            if isinstance(row, dict):
                add_row(row, "cloudsearch")
    except Exception:
        pass

    try:
        params = urlencode({"s": search_query, "type": 1, "limit": limit})
        request = Request(
            f"https://music.163.com/api/search/get/web?{params}",
            headers=netease_headers(),
        )
        with urlopen(request, timeout=6) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for row in ((payload.get("result") or {}).get("songs") or []):
            if isinstance(row, dict):
                add_row(row, "legacy_search")
    except Exception:
        pass
    return rows


def enrich_same_artist_groups_from_search(query: str, analysis: dict[str, Any], groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if analysis.get("intent") == "entity_search" and analysis.get("entity_type") == "song" and analysis.get("action") == "play":
        return groups
    if analysis.get("intent") == "similar_reco" and any(
        str(song.get("source") or "").startswith("similar_song_")
        for group in groups or []
        for song in group.get("songs") or []
    ):
        return groups
    if analysis.get("intent") not in {"entity_search", "similar_reco"}:
        return groups
    reference = " ".join(
        [
            query,
            str(analysis.get("reference") or ""),
            str((analysis.get("target_entity") or {}).get("artist") or ""),
            str((analysis.get("target_entity") or {}).get("name") or ""),
        ]
    )
    artist = identify_artist(reference)
    if not artist:
        return groups
    try:
        search_results = netease_search_songs(artist, limit=30)
    except Exception:
        return groups
    same_artist_results = [
        song for song in search_results
        if artist.lower() in song["artist"].lower() or normalize(artist) in normalize(song["artist"])
    ]
    if not same_artist_results:
        return groups

    same_artist_markers = ("其他作品", "本人作品", "同歌手", "同乐队", artist)
    target_group = next(
        (group for group in groups if any(marker in str(group.get("title") or "") for marker in same_artist_markers)),
        None,
    )
    if target_group is None:
        target_group = {"title": f"{artist} 其他作品", "songs": []}
        groups.insert(0, target_group)

    seen = {(normalize(song.get("title", "")), normalize(song.get("artist", ""))) for song in target_group.get("songs", [])}
    for song in same_artist_results:
        song_key = (normalize(song["title"]), normalize(song["artist"]))
        if song_key in seen:
            continue
        target_group.setdefault("songs", []).append(
            {
                "title": song["title"],
                "artist": song["artist"],
                "reason": f"来自网易云对 {artist} 的搜索召回，适合先在同一歌手作品里延展。",
                "verified": True,
                "source": "netease_search",
                "url": song_external_url(song["title"], song["artist"]),
                "spotify_search": f"https://open.spotify.com/search/{quote_plus(song['title'] + ' ' + song['artist'])}",
            }
        )
        seen.add(song_key)
        if len(target_group["songs"]) >= 4:
            break
    return groups


def spotify_configured() -> bool:
    return bool(SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET)


def get_spotify_app_token() -> str:
    global _spotify_token_cache
    if _spotify_token_cache and time.time() < _spotify_token_cache[1] - 60:
        return _spotify_token_cache[0]
    if not spotify_configured():
        raise RuntimeError("Spotify 未配置 SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET。")
    credentials = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode("utf-8")
    request = Request(
        "https://accounts.spotify.com/api/token",
        data=urlencode({"grant_type": "client_credentials"}).encode("utf-8"),
        headers={
            "Authorization": "Basic " + base64.b64encode(credentials).decode("ascii"),
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = str(payload.get("access_token") or "")
    expires_in = int(payload.get("expires_in") or 3600)
    if not token:
        raise RuntimeError("Spotify token 获取失败。")
    _spotify_token_cache = (token, time.time() + expires_in)
    return token


def fetch_spotify_player(title: str, artist: str) -> dict[str, Any]:
    title = title.strip()
    artist = artist.strip()
    if not title:
        return {"ok": False, "provider": "spotify", "error": "缺少歌曲名。"}
    token = get_spotify_app_token()
    search_query = f'track:"{title}" artist:"{artist}"' if artist else title
    params = urlencode({"q": search_query, "type": "track", "limit": 10, "market": "US"})
    request = Request(
        f"https://api.spotify.com/v1/search?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))

    candidates = (((payload.get("tracks") or {}).get("items")) or [])
    title_key = normalize(title)
    artist_key = normalize(artist)
    best = None
    best_score = -1
    for item in candidates:
        track_name = str(item.get("name") or "")
        artists = item.get("artists") or []
        artist_name = " / ".join(str(row.get("name") or "") for row in artists if isinstance(row, dict))
        track_id = str(item.get("id") or "")
        if not track_name or not track_id:
            continue
        track_key = normalize(track_name)
        item_artist_key = normalize(artist_name)
        score = 0
        if title_key and (title_key == track_key or title_key in track_key or track_key in title_key):
            score += 6
        if artist_key and (artist_key == item_artist_key or artist_key in item_artist_key or item_artist_key in artist_key):
            score += 5
        if not artist_key:
            score += 1
        if score > best_score:
            best = item
            best_score = score

    if not best or best_score < 5:
        return {
            "ok": False,
            "provider": "spotify",
            "error": "未找到 Spotify 曲目。",
            "query": f"{title} {artist}".strip(),
            "search_url": f"https://open.spotify.com/search/{quote_plus(f'{title} {artist}'.strip())}",
        }

    track_id = str(best.get("id"))
    artists = best.get("artists") or []
    artist_name = " / ".join(str(row.get("name") or "") for row in artists if isinstance(row, dict))
    album = best.get("album") if isinstance(best.get("album"), dict) else {}
    images = album.get("images") if isinstance(album.get("images"), list) else []
    image_url = str((images[0] or {}).get("url") or "") if images else ""
    external_urls = best.get("external_urls") if isinstance(best.get("external_urls"), dict) else {}
    return {
        "ok": True,
        "provider": "spotify",
        "source": "Spotify",
        "title": str(best.get("name") or title),
        "artist": artist_name or artist,
        "album": str(album.get("name") or ""),
        "track_id": track_id,
        "player_url": f"https://open.spotify.com/embed/track/{quote_plus(track_id)}?utm_source=generator&theme=0&autoplay=1",
        "song_url": str(external_urls.get("spotify") or f"https://open.spotify.com/track/{track_id}"),
        "search_url": f"https://open.spotify.com/search/{quote_plus(f'{title} {artist}'.strip())}",
        "image_url": image_url,
    }


def find_netease_song(title: str, artist: str) -> dict[str, Any]:
    title = title.strip()
    artist = artist.strip()
    search_queries = netease_search_queries(title, artist)
    search_query = search_queries[0] if search_queries else f"{title} {artist}".strip()
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for query in search_queries:
        for item in netease_candidate_rows(query):
            song_id = str(item.get("id") or "")
            if not song_id or song_id in seen_ids:
                continue
            seen_ids.add(song_id)
            candidates.append(item)

    best = None
    best_score = -1
    scored_candidates: list[dict[str, Any]] = []
    for item in candidates:
        track_name = str(item.get("name") or "")
        artists = item.get("artists") or []
        artist_name = " / ".join(str(row.get("name") or "") for row in artists if isinstance(row, dict))
        song_id = item.get("id")
        if not track_name or not song_id:
            continue
        title_score = title_match_score(title, track_name)
        artist_score = artist_match_score(artist, artist_name)
        if artist and artist_score <= 0:
            continue
        score = title_score + artist_score
        if normalize(song_main_title(title)) and normalize(song_main_title(title)) == normalize_song_match_text(track_name):
            score += 2
        album = item.get("album") if isinstance(item.get("album"), dict) else {}
        scored_candidates.append(
            {
                "title": track_name,
                "artist": artist_name,
                "album": str(album.get("name") or ""),
                "image_url": str(album.get("picUrl") or album.get("pic_url") or ""),
                "song_id": str(song_id),
                "score": score,
                "matched_query": str(item.get("_matched_query") or ""),
                "search_source": str(item.get("_search_source") or ""),
            }
        )
        if score > best_score:
            best = item
            best_score = score
    top_candidates = sorted(scored_candidates, key=lambda row: row["score"], reverse=True)[:5]
    threshold = 9 if artist else 7
    if not best or best_score < threshold:
        return {
            "ok": False,
            "query": search_query,
            "search_queries": search_queries,
            "search_url": apple_music_search_url(search_query),
            "match_score": best_score,
            "match_candidates": top_candidates,
        }
    song_id = str(best.get("id"))
    artists = best.get("artists") or []
    artist_name = " / ".join(str(row.get("name") or "") for row in artists if isinstance(row, dict))
    album = best.get("album") if isinstance(best.get("album"), dict) else {}
    return {
        "ok": True,
        "title": str(best.get("name") or title),
        "artist": artist_name or artist,
        "album": str(album.get("name") or ""),
        "image_url": str(album.get("picUrl") or album.get("pic_url") or ""),
        "song_id": song_id,
        "song_url": f"https://music.163.com/#/song?id={quote_plus(song_id)}",
        "search_url": apple_music_search_url(search_query),
        "source": "网易云音乐",
        "match_score": best_score,
        "matched_query": str(best.get("_matched_query") or search_query),
    }


def fetch_netease_player(title: str, artist: str) -> dict[str, Any]:
    title = title.strip()
    artist = artist.strip()
    if not title:
        return {"ok": False, "error": "缺少歌曲名。"}

    cache_key = (PLAYER_CACHE_VERSION, normalize(title), normalize(artist))
    cached = _player_cache.get(cache_key)
    if cached and time.time() - cached[0] < PLAYER_CACHE_TTL_SECONDS:
        data = json.loads(json.dumps(cached[1], ensure_ascii=False))
        data["cached"] = True
        return data

    found = find_netease_song(title, artist)
    if not found.get("ok"):
        data = {
            "ok": False,
            "cached": False,
            "error": "未找到网易云歌曲 ID。",
            "query": found.get("query") or f"{title} {artist}".strip(),
            "search_url": found.get("search_url") or song_external_url(title, artist),
        }
    else:
        data = {
            "ok": True,
            "cached": False,
            **found,
            "player_url": f"https://music.163.com/outchain/player?type=2&id={quote_plus(str(found['song_id']))}&auto=1&height=66",
        }

    _player_cache[cache_key] = (time.time(), data)
    return data


def fetch_music_player(title: str, artist: str) -> dict[str, Any]:
    data = fetch_apple_music_track(title, artist)
    if data.get("ok"):
        return {
            **data,
            "player_url": data.get("song_url") or data.get("search_url") or song_external_url(title, artist),
            "player_type": "preview",
        }
    return data


def fetch_netease_stream(title: str, artist: str) -> dict[str, Any]:
    found = find_netease_song(title, artist)
    if not found.get("ok") or not found.get("song_id"):
        return {"ok": False, "provider": "netease", "title": title, "artist": artist, "error": "未找到网易云歌曲 ID。", **found}
    song_id = str(found["song_id"])
    params = urlencode({"id": song_id, "ids": f"[{song_id}]", "br": 128000})
    request = Request(
        f"https://music.163.com/api/song/enhance/player/url?{params}",
        headers=netease_headers(),
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    row = rows[0] if rows and isinstance(rows[0], dict) else {}
    stream_url = str(row.get("url") or "").strip()
    if not stream_url:
        return {
            "ok": False,
            "provider": "netease",
            **found,
            "error": "网易云未返回可控播放直链，可能是 VIP/版权/地区限制。",
            "code": row.get("code"),
            "fee": row.get("fee"),
            "payed": row.get("payed"),
        }
    return {
        "ok": True,
        "provider": "netease",
        **found,
        "stream_url": stream_url.replace("http://", "https://"),
        "bitrate": row.get("br"),
        "duration_ms": row.get("time"),
        "code": row.get("code"),
        "fee": row.get("fee"),
        "payed": row.get("payed"),
    }


def fetch_configured_music_stream(title: str, artist: str) -> dict[str, Any]:
    provider = MUSIC_PROVIDER if MUSIC_PROVIDER in {"netease", "apple", "apple_music", "auto"} else "apple"
    if provider == "netease":
        return fetch_netease_stream(title, artist)
    return fetch_apple_music_track(title, artist)


def fetch_music_streams(songs: list[dict[str, str]], offset: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    limited = songs[:8]

    def fetch_one(index: int, song: dict[str, str]) -> tuple[int, dict[str, Any]]:
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        if not title:
            return index, {}
        request_meta = {
            "requested_index": offset + index,
            "requested_title": title,
            "requested_artist": artist,
        }
        try:
            return index, {**fetch_configured_music_stream(title, artist), **request_meta}
        except Exception as exc:
            return index, {"ok": False, "provider": MUSIC_PROVIDER or "netease", "title": title, "artist": artist, "error": str(exc), **request_meta}

    if not limited:
        return rows
    with ThreadPoolExecutor(max_workers=min(STREAM_PROBE_MAX_WORKERS, len(limited))) as executor:
        futures = [executor.submit(fetch_one, index, song) for index, song in enumerate(limited)]
        for future in as_completed(futures):
            _, row = future.result()
            if row:
                rows.append(row)
    return sorted(rows, key=lambda item: int(item.get("requested_index") or 0))


def probe_song_stream(title: str, artist: str) -> dict[str, Any]:
    key = (normalize(title), normalize(artist))
    cached = _stream_probe_cache.get(key)
    if cached and time.time() - cached[0] < STREAM_PROBE_TTL_SECONDS:
        return json.loads(json.dumps(cached[1], ensure_ascii=False))
    try:
        data = fetch_configured_music_stream(title, artist)
    except Exception as exc:
        data = {"ok": False, "provider": MUSIC_PROVIDER or "netease", "title": title, "artist": artist, "error": str(exc)}
    _stream_probe_cache[key] = (time.time(), data)
    return json.loads(json.dumps(data, ensure_ascii=False))


def prioritize_playable_groups(groups: list[dict[str, Any]], analysis: dict[str, Any], *, max_count: int = 5, query: str = "") -> list[dict[str, Any]]:
    if analysis.get("intent") not in {"general_reco", "filtered_reco", "similar_reco"}:
        return groups
    candidates: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    excluded_artists = excluded_artists_from_query(query)
    for group in groups or []:
        group_title = str(group.get("title") or "推荐结果")
        for song in group.get("songs") or []:
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            if not title or not artist:
                continue
            artist_key = normalize(canonical_artist_name(artist) or artist)
            if artist_key in excluded_artists:
                continue
            key = (normalize(title), normalize(artist))
            if key in seen:
                continue
            seen.add(key)
            candidates.append((group_title, dict(song)))
            if len(candidates) >= STREAM_PROBE_CANDIDATE_LIMIT:
                break
        if len(candidates) >= STREAM_PROBE_CANDIDATE_LIMIT:
            break
    if not candidates:
        return groups
    candidates = backfill_similar_song_candidates(candidates, analysis, max_count=max_count, query=query)

    streams: dict[int, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(STREAM_PROBE_MAX_WORKERS, len(candidates))) as executor:
        future_to_index = {
            executor.submit(probe_song_stream, str(song.get("title") or ""), str(song.get("artist") or "")): index
            for index, (_, song) in enumerate(candidates)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                streams[index] = future.result()
            except Exception as exc:
                _, song = candidates[index]
                streams[index] = {
                    "ok": False,
                    "provider": "apple_music",
                    "title": str(song.get("title") or ""),
                    "artist": str(song.get("artist") or ""),
                    "error": str(exc),
                }

    enriched_candidates: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for index, (group_title, song) in enumerate(candidates):
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        stream = streams.get(index) or {}
        enriched = dict(song)
        if stream.get("ok") and stream.get("stream_url"):
            enriched["playable"] = True
            enriched["play_provider"] = "apple_music"
            enriched["title"] = stream.get("title") or title
            enriched["artist"] = stream.get("artist") or artist
            enriched["album"] = stream.get("album") or enriched.get("album") or ""
            enriched["image_url"] = stream.get("image_url") or enriched.get("image_url") or ""
            enriched["cover_url"] = stream.get("cover_url") or stream.get("image_url") or enriched.get("cover_url") or ""
            enriched["stream_song_id"] = stream.get("track_id") or ""
            enriched["matched_title"] = stream.get("title") or title
            enriched["matched_artist"] = stream.get("artist") or artist
            enriched["url"] = stream.get("song_url") or stream.get("url") or song_external_url(title, artist)
            enriched["preview_url"] = stream.get("preview_url") or stream.get("stream_url") or ""
        else:
            enriched["playable"] = False
            enriched["play_error"] = stream.get("error") or "暂时拿不到 Apple Music preview"
        enriched_candidates.append((group_title, enriched, stream))

    playable = [(group_title, song) for group_title, song, stream in enriched_candidates if stream.get("ok") and stream.get("stream_url")]
    fallback = [(group_title, song) for group_title, song, stream in enriched_candidates if not (stream.get("ok") and stream.get("stream_url"))]
    ordered = playable + fallback
    if not playable:
        return groups
    selected = ordered[:max_count]
    regrouped: dict[str, list[dict[str, Any]]] = {}
    for group_title, song in selected:
        regrouped.setdefault(group_title, []).append(song)
    return [{"title": title, "songs": songs} for title, songs in regrouped.items()]


def backfill_similar_song_candidates(
    candidates: list[tuple[str, dict[str, Any]]],
    analysis: dict[str, Any],
    *,
    max_count: int,
    query: str = "",
) -> list[tuple[str, dict[str, Any]]]:
    if analysis.get("intent") != "similar_reco" or analysis.get("entity_type") != "song":
        return candidates
    if len(candidates) >= max(max_count, STREAM_PROBE_CANDIDATE_LIMIT):
        return candidates
    existing = {
        (normalize(str(song.get("title") or "")), normalize(str(song.get("artist") or "")))
        for _, song in candidates
    }
    excluded_artists = excluded_artists_from_query(query)
    artist_counts: dict[str, int] = {}
    for _, song in candidates:
        artist_key = normalize(canonical_artist_name(str(song.get("artist") or "")) or str(song.get("artist") or ""))
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1

    target = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
    source_key = (
        normalize(str(target.get("name") or "")),
        normalize(str(target.get("artist") or "")),
    )
    traits = [normalize(str(item)) for item in analysis.get("traits", []) if str(item).strip()]
    reference_terms = set(traits)
    for _, song in candidates:
        for field in ("traits", "genres", "moods", "scenes"):
            reference_terms.update(normalize(str(item)) for item in song.get(field, []) if str(item).strip())
    if not reference_terms:
        reference_terms.update(["华语流行", "温柔", "旋律强"])
    if reference_terms == {normalize("相似延展")}:
        reference_terms.update(normalize(item) for item in ["华语流行", "温柔", "旋律强", "怀旧"])
    searchable_terms = {
        normalize(str(item))
        for song in SONGS
        for field in ("traits", "genres", "moods", "scenes")
        for item in song.get(field, [])
        if str(item).strip()
    }
    if not (reference_terms & searchable_terms):
        reference_terms.update(normalize(item) for item in ["华语流行", "温柔", "旋律强", "怀旧", "摇滚"])

    def rank_candidates(terms: set[str]) -> list[tuple[int, str, str, dict[str, Any]]]:
        rows: list[tuple[int, str, str, dict[str, Any]]] = []
        for song in SONGS:
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            artist_key = normalize(canonical_artist_name(artist) or artist)
            key = (normalize(title), normalize(artist))
            if not title or not artist or artist_key in excluded_artists or key in existing or key == source_key:
                continue
            song_terms = set()
            for field in ("traits", "genres", "moods", "scenes"):
                song_terms.update(normalize(str(item)) for item in song.get(field, []) if str(item).strip())
            overlap = len(terms & song_terms)
            if overlap:
                rows.append((overlap, normalize(artist), normalize(title), song))
        return rows

    ranked = rank_candidates(reference_terms)
    if len(ranked) < max_count:
        reference_terms.update(normalize(item) for item in ["华语流行", "温柔", "旋律强", "怀旧", "摇滚"])
        ranked = rank_candidates(reference_terms)
    ranked.sort(key=lambda item: (-item[0], item[1], item[2]))

    backfilled = list(candidates)
    group_title = f"类似《{target.get('name') or analysis.get('reference') or '参考歌曲'}》的歌曲"
    for _, _, _, song in ranked:
        if len(backfilled) >= STREAM_PROBE_CANDIDATE_LIMIT:
            break
        title = str(song.get("title") or "").strip()
        artist = str(song.get("artist") or "").strip()
        artist_key = normalize(canonical_artist_name(artist) or artist)
        if artist_counts.get(artist_key, 0) >= 2:
            continue
        artist_counts[artist_key] = artist_counts.get(artist_key, 0) + 1
        existing.add((normalize(title), normalize(artist)))
        backfilled.append(
            (
                group_title,
                {
                    "title": title,
                    "artist": artist,
                    "reason": reason_for(song, analysis),
                    "verified": True,
                    "source": "similar_song_backfill",
                    "url": song_external_url(title, artist),
                    "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + artist)}",
                },
            )
        )
    return backfilled


def finalize_song_groups_for_playback(result: dict[str, Any]) -> dict[str, Any]:
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    groups = result.get("groups") if isinstance(result.get("groups"), list) else []
    if analysis.get("intent") not in SONG_INTENTS or not groups:
        return result
    limited = limit_recommendation_groups(
        groups,
        analysis,
        max_count=STREAM_PROBE_CANDIDATE_LIMIT,
    )
    playable_first = prioritize_playable_groups(limited, analysis)
    if playable_first:
        return {**result, "groups": playable_first}
    return result


def song_identity(song: dict[str, Any]) -> tuple[str, str]:
    return (
        normalize(str(song.get("title") or "")),
        normalize(str(song.get("artist") or "")),
    )


def filter_excluded_groups(groups: list[dict[str, Any]], exclude: list[dict[str, str]], *, limit: int = 5) -> list[dict[str, Any]]:
    excluded = {
        song_identity(song)
        for song in exclude or []
        if isinstance(song, dict) and (song.get("title") or song.get("artist"))
    }
    seen: set[tuple[str, str]] = set()
    next_groups: list[dict[str, Any]] = []
    total = 0
    for group in groups or []:
        songs: list[dict[str, Any]] = []
        for song in group.get("songs") or []:
            key = song_identity(song)
            if not key[0] or key in excluded or key in seen:
                continue
            seen.add(key)
            songs.append(song)
            total += 1
            if total >= limit:
                break
        if songs:
            next_groups.append({"title": str(group.get("title") or "续播推荐"), "songs": songs})
        if total >= limit:
            break
    return next_groups


def continuation_query(base_query: str, analysis: dict[str, Any], groups: list[dict[str, Any]], exclude: list[dict[str, str]]) -> str:
    songs_text = "；".join(
        f"{song.get('title', '')} - {song.get('artist', '')}"
        for song in (exclude or [])[:12]
        if song.get("title")
    )
    traits = "、".join(str(item) for item in (analysis.get("traits") or [])[:6])
    reference = str(analysis.get("reference") or base_query or "").strip()
    return (
        f"继续为这个电台补充后续歌曲。原始需求：{base_query or reference or '泛推荐'}。"
        f"保持同一氛围/场景/风格，但不要重复已播歌曲。"
        f"{' 核心特征：' + traits + '。' if traits else ''}"
        f"{' 已播/已在队列：' + songs_text + '。' if songs_text else ''}"
        "返回新的 5 首真实歌曲。"
    )


ALLOWED_AUDIO_PROXY_HOSTS = (
    "music.126.net",
    "music.163.com",
    "m10.music.126.net",
    "m701.music.126.net",
    "m704.music.126.net",
    "m801.music.126.net",
    "m804.music.126.net",
    "audio-ssl.itunes.apple.com",
    "aod.itunes.apple.com",
)


def audio_proxy_allowed(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").lower()
    return (
        host.endswith(".music.126.net")
        or host.endswith(".music.163.com")
        or host.endswith(".itunes.apple.com")
        or host in ALLOWED_AUDIO_PROXY_HOSTS
    )


@app.get("/audio-proxy")
async def audio_proxy(url: str, request: FastAPIRequest):
    if not audio_proxy_allowed(url):
        return JSONResponse({"error": "不支持的音频来源。"}, status_code=403)

    def stream():
        headers = netease_headers()
        if request.headers.get("range"):
            headers["Range"] = request.headers["range"]
        upstream_request = Request(url, headers=headers)
        with urlopen(upstream_request, timeout=12) as response:
            while True:
                chunk = response.read(1024 * 128)
                if not chunk:
                    break
                yield chunk

    return StreamingResponse(
        stream(),
        media_type="audio/mpeg",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        },
    )


def context_cache_key(context: dict[str, Any] | None) -> str:
    if not context:
        return ""
    songs = context_songs(context, limit=6)
    history = context.get("history") if isinstance(context, dict) and isinstance(context.get("history"), list) else []
    compact = {
        "interaction_mode": str(context.get("interaction_mode") or "") if isinstance(context, dict) else "",
        "songs": [{"title": song["title"], "artist": song["artist"]} for song in songs],
        "history": [
            {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")[:80]}
            for item in history[-3:]
            if isinstance(item, dict)
        ],
    }
    return json.dumps(compact, ensure_ascii=False, sort_keys=True)


def stream_event(event_type: str, payload: dict[str, Any]) -> str:
    return f"data: {json.dumps({'type': event_type, **payload}, ensure_ascii=False)}\n\n"


def response_song_events(result: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    index = 0
    for group in result.get("groups") or []:
        group_title = str(group.get("title") or "")
        for song in group.get("songs") or []:
            title = str(song.get("title") or "").strip()
            artist = str(song.get("artist") or "").strip()
            if not title:
                continue
            events.append(
                {
                    "index": index,
                    "group": group_title,
                    "song": {
                        "title": title,
                        "artist": artist,
                        "reason": str(song.get("reason") or ""),
                        "spotify_search": song.get("spotify_search") or f"https://open.spotify.com/search/{quote_plus((title + ' ' + artist).strip())}",
                    },
                }
            )
            index += 1
    return events


async def get_online_recommendations(query: str, n: int, provider: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    started_at = time.time()
    cache_key = (provider, query.strip().lower(), n, context_cache_key(context))
    cached = _online_cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        data = json.loads(json.dumps(cached[1], ensure_ascii=False))
        data["cached"] = True
        logger.info("recommend_model_cache_hit provider=%s query=%r elapsed=%.3f", provider, query, time.time() - started_at)
        return data

    client, model = get_client(provider)
    context_text = conversation_context_text(context, query)
    entity_hint = entity_link_hint_text(query)
    user_content = f"需求：{query}\n只输出 analysis JSON，不要返回歌曲、实体列表或回答。"
    if entity_hint:
        user_content = f"{entity_hint}\n\n{user_content}"
    if context_text:
        user_content = f"{context_text}\n\n{entity_hint + chr(10) + chr(10) if entity_hint else ''}本轮需求：{query}\n请结合上下文只输出 analysis JSON，不要返回歌曲、实体列表或回答。"
    classify_response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    analysis = normalize_analysis_payload(extract_json(classify_response.choices[0].message.content or "{}"), query)

    if analysis.get("intent") not in SONG_INTENTS:
        data = clean_model_payload(payload_from_analysis(analysis), query, prioritize_playable=False)
        data["cached"] = False
        _online_cache[cache_key] = (time.time(), data)
        logger.info("recommend_classify_done provider=%s query=%r intent=%s elapsed=%.3f", provider, query, analysis.get("intent"), time.time() - started_at)
        return data

    recommend_user_content = (
        f"用户需求：{query}\n"
        f"{entity_hint + chr(10) if entity_hint else ''}"
        f"analysis：{json.dumps(analysis, ensure_ascii=False)}\n"
        "请严格服从 analysis 生成结果。推荐类返回 3-5 首真实歌曲；单曲播放只返回 1 首；不要重新分类。"
    )
    if context_text:
        recommend_user_content = f"{context_text}\n\n{recommend_user_content}"
    recommend_response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": RECOMMENDATION_PROMPT},
            {"role": "user", "content": recommend_user_content},
        ],
        response_format={"type": "json_object"},
        temperature=0.55,
    )
    recommendation = extract_json(recommend_response.choices[0].message.content or "{}")
    data = clean_model_payload({"analysis": analysis, **recommendation}, query, prioritize_playable=False)
    data["cached"] = False
    _online_cache[cache_key] = (time.time(), data)
    song_count = len(flatten_group_songs(data.get("groups") or [], limit=20))
    logger.info("recommend_model_done provider=%s query=%r songs=%s elapsed=%.3f", provider, query, song_count, time.time() - started_at)
    return data


async def run_online_job(job_id: str, query: str, n: int, provider: str, context: dict[str, Any] | None = None) -> None:
    started_at = time.time()
    try:
        data = await get_online_recommendations(query, n, provider, context)
        result = attach_pending_dj({"query": query, "provider": provider, **data})
        _jobs[job_id].update(
            {
                "status": "done",
                "result": result,
                "updated_at": time.time(),
            }
        )
        logger.info("recommend_job_done job_id=%s provider=%s query=%r elapsed=%.3f", job_id, provider, query, time.time() - started_at)
    except Exception as exc:
        _jobs[job_id].update(
            {
                "status": "error",
                "error": safe_error_message(exc),
                "updated_at": time.time(),
            }
        )
        logger.error(
            "recommend_job_error job_id=%s provider=%s query=%r elapsed=%.3f error=%s\n%s",
            job_id,
            provider,
            query,
            time.time() - started_at,
            exc,
            traceback.format_exc(),
        )


def looks_like_bare_music_entity_query(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    lower = q.lower()
    if re.search(
        r"\b(play|put on|throw on|listen|recommend|recommendations|queue|skip|next|pause|resume|louder|quieter|mute|save|heart|follow|share|download|make|create|write|remix|cover|edit|mix|master|similar|same|vibe|genre|music|songs?|playlist|beat|lyrics|track|bangers|chill|lo-?fi|hip-?hop|r&b|rock|jazz|edm|ambient|workout|party)\b",
        lower,
    ):
        return False
    if contains_any(q, ["?", "？", "吗", "怎么", "为什么", "什么", "推荐", "适合", "播放", "换一首", "写一首"]):
        return False
    if contains_any(q, ["想听", "听点", "听些", "来点", "放点", "找点", "关于", "那种", "这种", "一类", "类型"]):
        return False
    if is_generic_reco_query(q) or is_topic_reco_query(q):
        return False
    if query_traits(q):
        return False
    if contains_any(
        q,
        [
            "健身", "跑步", "训练", "运动", "开车", "驾驶", "通勤", "学习", "工作", "睡前",
            "深夜", "夜晚", "雨天", "派对", "热血", "燃", "伤感", "悲伤", "治愈", "放松",
            "电子", "节奏", "摇滚", "民谣", "说唱", "爵士", "古典", "钢琴", "纯音乐",
            "暗黑", "流行", "氛围", "适合", "让人", "听着", "来点", "放点", "找点",
            "梦想", "青春", "爱情", "孤独", "自由", "希望", "告别", "怀念", "城市", "夏天",
        ],
    ):
        return False
    if len(q) > 80:
        return False
    compact = normalize(q)
    if identify_artist(q):
        return True
    if any(normalize(song.get("title") or "") == compact for song in SONGS):
        return True
    if any(normalize(title) == compact for titles in ARTIST_SIGNATURE_SONGS.values() for title in titles):
        return True
    allowed_english_title_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'.,&!:;()[]- ")
    if q[0].isalpha() and all(char in allowed_english_title_chars for char in q):
        return True
    if re.fullmatch(r"《[^》]{1,40}》", q):
        return True
    if re.search(r"[-–—《》,，:：]", q) and re.fullmatch(r"[\u4e00-\u9fffA-Za-z0-9·& 《》,，:：'._()（）-]{2,40}", q):
        return True
    return False


def is_playback_control(query: str) -> bool:
    q = query.strip()
    if is_favorite_request(q):
        return False
    if re.search(
        r"\b(skip|next|previous|go back|pause|resume|continue|stop|start over|from the beginning|play that again|repeat|loop|shuffle|louder|quieter|mute|turn it up|turn this up|too loud|too quiet|queue|add this to the queue|remove this from the queue|follow|unfollow|share|download|rename|clear this playlist|delete .*playlist|sleep timer|high quality|bluetooth)\b",
        q.lower(),
    ):
        return True
    direct_control_words = [
        "换一首", "换首", "换歌", "切歌", "跳过", "不要这首", "这首不好听", "不好听",
        "暂停", "停一下", "继续播放", "继续放", "接着放", "恢复播放",
        "定时", "下一首", "上一首", "随机播放", "单曲循环", "列表循环",
        "太大声", "太小声", "大声点", "小声点", "再小声", "再大声", "音量大", "音量小",
        "声音大", "声音小", "调大", "调小",
    ]
    if contains_any(q, direct_control_words):
        return True
    if re.search(r"(?:换|跳过|切|下)\s*[二两三四五六七八九十2-9]\s*首", q):
        return True
    if re.fullmatch(r"(播放|放|继续|开始|开始播放|暂停播放|停)", q):
        return True
    if is_current_playback_status_query(q):
        return True
    return False


def is_current_playback_status_query(query: str) -> bool:
    q = query.strip()
    q_lower = q.lower()
    if contains_any(q, ["介绍", "赏析", "评价", "谁唱", "谁的歌", "哪一年", "哪年", "发行", "什么风格", "哪张专辑"]):
        return False
    if re.search(r"\b(what'?s|what is|whats)\s+(this|the current)\s+(song|track)\s+(called|name)\b", q_lower):
        return True
    if re.search(r"\bhow much time is left\b", q_lower):
        return True
    if contains_any(q, ["现在这首歌叫啥", "当前播放", "当前这首", "现在放的", "刚才那首", "这首歌叫什么", "这首歌叫啥", "还有多久"]):
        return True
    return False


def is_creation_request(query: str) -> bool:
    q = query.strip().lower()
    if re.search(r"\b(make|create|write|generate|compose|produce)\b", q):
        return True
    return contains_any(query, ["做", "写", "创作", "生成", "整一首", "编一首", "改编", "续写"])


def is_lyric_fragment_search(query: str) -> bool:
    q = query.strip()
    if contains_any(q, ["写歌词", "改歌词", "生成歌词", "歌词创作"]):
        return False
    if contains_any(q, ["适合", "推荐", "播放", "给我播", "放", "来一首", "来几首", "听什么", "想听"]):
        return False
    if contains_any(q, ["歌词里", "歌词中", "哪首歌", "什么歌", "歌叫什么"]):
        return contains_any(q, ["叫", "找", "查", "搜", "有", "那首", "这首", "歌词"])
    if len(q) >= 8 and not contains_any(q, ["推荐", "播放", "给我播", "放", "来一首", "来几首", "写", "生成", "创作"]):
        lyric_like = contains_any(q, ["为何", "最后", "老友", "知己", "爱", "梦", "风", "雨", "夜", "心"])
        return lyric_like and not contains_any(q, ["吗", "呢", "什么", "为什么", "适合", "介绍", "赏析"])
    return False


def is_favorite_request(query: str) -> bool:
    if re.search(r"\b(save it|save this|save this one|heart this|heart this one|like this song|like this track|add to my likes|add to my library)\b", query.lower()):
        return True
    return contains_any(
        query,
        ["收藏", "红心", "喜欢一下", "加入喜欢", "加入我喜欢", "加入收藏", "加到收藏", "存一下"],
    )


def function_reply(query: str, intent: str = "control") -> str:
    if intent == "favorite":
        return "好的，已为你收藏这首歌。"
    if contains_any(query, ["暂停", "停一下", "暂停播放", "停"]):
        return "好的，现在为你暂停播放。"
    if contains_any(query, ["继续", "接着放", "恢复播放", "开始播放", "开始"]):
        return "好的，现在继续为你播放。"
    if contains_any(query, ["下一首", "换一首", "切歌"]):
        return "好的，现在为你切到下一首。"
    if "上一首" in query:
        return "好的，现在为你切回上一首。"
    if contains_any(query, ["随机播放"]):
        return "好的，现在为你开启随机播放。"
    if contains_any(query, ["单曲循环"]):
        return "好的，现在为你开启单曲循环。"
    if contains_any(query, ["列表循环"]):
        return "好的，现在为你开启列表循环。"
    if contains_any(query, ["大声", "音量大", "声音大", "调大", "太小声", "再大声"]):
        return "好的，现在为你调大音量。"
    if contains_any(query, ["小声", "音量小", "声音小", "调小", "太大声", "再小声"]):
        return "好的，现在为你调小音量。"
    if contains_any(query, ["现在这首歌叫啥", "当前播放", "现在放的", "刚才那首"]):
        return "好的，现在为你查看当前播放歌曲。"
    return "好的，已收到你的播放控制指令。"


def is_music_qa_query(query: str) -> bool:
    if contains_any(query, ["推荐", "来点", "想听", "听点", "听些", "播放", "放点", "找点", "挑", "挑几首", "配乐"]):
        return False
    if recent_song_search_artist(query):
        return False
    if is_modifier_reco_query(query):
        return False
    if contains_any(query, ["主题曲", "主题歌", "官方歌", "anthem"]):
        return True
    return contains_any(
        query,
        [
            "谁唱", "谁的歌", "叫什么", "叫啥", "什么时候", "哪一年", "哪年", "发行",
            "生日", "出过几张专辑", "几张专辑", "多少张专辑", "曲作者", "作曲", "作词",
            "歌词", "介绍", "百科", "赏析", "评价", "什么风格", "什么年代", "哪张专辑",
        ],
    )


def recent_song_search_artist(query: str) -> str:
    q = query.strip()
    if not contains_any(q, ["新歌", "新专辑", "最近", "近期", "最新"]):
        return ""
    if not contains_any(q, ["歌", "歌曲", "单曲", "专辑"]):
        return ""
    artist = identify_artist(q)
    if artist:
        return artist
    match = re.search(r"(?:查一下|查查|看看|搜一下|搜索)?\s*(?P<artist>[\u4e00-\u9fffA-Za-z0-9· ._-]{2,24})\s*(?:有没有|有无|最近|近期|最新)", q)
    if match:
        candidate = match.group("artist").strip(" ，,。?？")
        if candidate and not contains_any(candidate, ["帮我", "一下", "最近", "近期", "最新"]):
            return candidate
    match = re.search(r"(?:最近|近期|最新)\s*(?P<artist>[\u4e00-\u9fffA-Za-z0-9· ._-]{2,24})\s*(?:有没有|有无|发|出)", q)
    if match:
        candidate = match.group("artist").strip(" ，,。?？")
        if candidate and not contains_any(candidate, ["帮我", "一下", "最近", "近期", "最新"]):
            return candidate
    return ""


def modifier_reco_traits(query: str) -> list[str]:
    buckets = [
        ("流行", ["流行", "pop"]),
        ("Dream Pop", ["dream pop", "dream-pop", "梦幻流行"]),
        ("轻音乐", ["轻音乐", "纯音乐", "器乐"]),
        ("粤语", ["粤语", "广东话"]),
        ("国语", ["中文", "国语", "华语"]),
        ("日语", ["日语", "jpop"]),
        ("韩语/Kpop", ["韩语", "kpop", "k-pop"]),
        ("英语", ["英文", "英语"]),
        ("年代", ["八十年代", "80年代", "90年代", "九十年代", "00年代", "零零年代"]),
        ("朋克", ["朋克", "punk"]),
        ("说唱", ["rap", "说唱", "嘻哈", "hiphop", "hip-hop"]),
        ("R&B", ["rnb", "r&b", "节奏布鲁斯"]),
        ("爵士", ["爵士", "jazz"]),
        ("对唱", ["对唱", "合唱", "男女对唱"]),
        ("睡前/助眠", ["睡前", "助眠", "睡觉"]),
        ("动感", ["动感", "跳舞", "律动", "节奏"]),
        ("庆祝", ["生日", "庆祝", "派对"]),
        ("浪漫", ["浪漫", "情歌", "甜蜜", "心动", "表白"]),
        ("雨天居家", ["下雨", "雨天", "窝着", "在家"]),
    ]
    return [label for label, words in buckets if contains_any(query, words)]


def is_modifier_reco_query(query: str) -> bool:
    q = query.strip()
    if not q or is_favorite_request(q):
        return False
    if recent_song_search_artist(q):
        return False
    if extract_artist_song(q) or is_similar_artist_query(q) or is_artist_song_request(q):
        return False
    has_music_object = contains_any(q, ["歌", "歌曲", "音乐", "曲子", "歌单", "的", "有吗", "来一首"])
    has_reco_action = contains_any(q, ["推荐", "来点", "想听", "听点", "听些", "播放", "放点", "找点", "要", "有没有", "有吗", "挑", "挑几首", "配乐"])
    return bool(modifier_reco_traits(q)) and (has_music_object or has_reco_action)


def is_state_only_chitchat(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if contains_any(q, ["推荐", "来点", "想听", "听点", "听些", "播放", "放点", "找点", "换一首", "适合", "有吗", "有没有", "歌", "歌曲", "音乐", "配乐", "挑"]):
        return False
    if is_modifier_reco_query(q):
        return False
    if is_music_qa_query(q) or is_favorite_request(q):
        return False
    state_words = [
        "你好", "hello", "hi", "嗨", "哈喽", "在吗", "你是谁", "你叫什么", "谢谢", "感谢",
        "早上好", "中午好", "晚上好", "晚安", "测试一下", "说句话",
        "太晚了", "困了", "累", "有点累", "有点烦", "烦", "想睡觉", "今天又下雨", "下雨了",
        "天气不错", "天气真好", "天终于放晴", "最近喜欢上了",
        "出去玩", "心情好", "心情不错", "想念", "想她", "想他", "想女朋友", "想男朋友",
        "女朋友", "男朋友", "前女友", "前男友", "难过", "伤心", "不开心", "孤单", "孤独",
        "哈哈", "哈哈哈", "推的歌还可以", "不错不错", "真不错", "挺厉害", "真厉害", "这首一般",
        "唱情歌不要太好听", "开车不听歌等于白开",
    ]
    return contains_any(q, state_words)

def chitchat_reply(query: str) -> str:
    q = query.strip().lower()
    if contains_any(q, ["你是谁", "你叫什么"]):
        return "我是 Melodio，像一个会听你说话的私人 DJ。你可以直接告诉我此刻的心情、场景，或者想找哪首歌。"
    if contains_any(q, ["谢谢", "感谢"]):
        return "不客气。我会在这里接住你的情绪，也把下一首歌放到合适的位置。"
    if contains_any(q, ["晚安"]):
        return "晚安。把声音放轻一点，剩下的就交给夜晚。"
    if contains_any(q, ["想念", "想她", "想他", "女朋友", "男朋友", "前女友", "前男友"]):
        return "想念一个人的时候，声音最好别太用力。我先陪你在这里停一下；要不要我给你放几首适合现在听的歌？"
    if contains_any(q, ["难过", "伤心", "不开心", "孤单", "孤独", "烦", "累", "失眠", "睡不着", "心情不好"]):
        return "我听到了。先不用急着把情绪整理好；如果你愿意，我可以给你放几首不吵、能慢慢接住你的歌。"
    if contains_any(q, ["你好", "hello", "hi", "嗨", "哈喽", "在吗", "早上好", "中午好", "晚上好"]):
        return "我在。今天想从哪种情绪开始听？"
    if contains_any(q, ["测试一下", "说句话"]):
        return "听得到。我会用这种声音陪你选歌、串场，也会在该安静的时候把空间留给音乐。"
    return "我在听。你可以继续说，也可以告诉我现在想听什么。"


def feedback_reco_traits(query: str) -> list[str]:
    buckets = [
        ("欢快", ["欢快", "轻快", "开心", "快乐", "愉快", "明亮"]),
        ("更燃", ["燃", "热血", "带劲", "有劲", "炸", "爆发"]),
        ("舒缓", ["舒缓", "安静", "轻柔", "柔和", "放松"]),
        ("伤感", ["伤感", "悲伤", "emo", "想哭"]),
        ("节奏", ["节奏", "律动", "鼓点"]),
        ("低沉", ["低沉", "暗一点", "暗黑"]),
    ]
    traits = [label for label, words in buckets if contains_any(query, words)]
    if not traits:
        return []
    if contains_any(query, ["有没有", "来点", "换成", "换点", "想听", "一点", "一些", "更"]):
        return traits
    return []


def topic_reco_traits(query: str) -> list[str]:
    buckets = [
        ("爱情", ["爱情", "恋爱", "情歌", "甜蜜", "暧昧", "心动", "表白"]),
        ("青春", ["青春", "校园", "少年", "毕业"]),
        ("梦想", ["梦想", "理想", "希望", "自由", "远方"]),
        ("孤独", ["孤独", "寂寞", "一个人", "独处"]),
        ("告别", ["告别", "离别", "分手", "怀念", "遗憾"]),
        ("城市", ["城市", "都市", "夜归", "通勤"]),
        ("夏天", ["夏天", "海边", "午后"]),
        ("雨天", ["雨天", "下雨", "阴天"]),
        ("居家", ["在家", "窝着", "不想出门"]),
        ("洗漱/洗澡", ["洗澡", "洗漱", "泡澡", "冲澡"]),
        ("家务", ["做饭", "收拾房间", "打扫", "整理房间", "洗衣服"]),
        ("出门准备", ["化妆", "穿搭", "换衣服", "准备出门"]),
        ("睡前/助眠", ["睡前", "助眠", "睡觉", "我要睡了"]),
        ("庆祝", ["生日", "庆祝", "派对"]),
        ("Dream Pop", ["dream pop", "dream-pop", "梦幻流行"]),
        ("欢快", ["欢快", "轻快", "开心", "快乐", "明亮"]),
        ("伤感", ["伤感", "悲伤", "emo", "想哭"]),
        ("治愈", ["治愈", "温暖", "安慰", "放松"]),
    ]
    traits = [label for label, words in buckets if contains_any(query, words)]
    return list(dict.fromkeys([*query_traits(query), *traits]))[:6]


def is_generic_reco_query(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if is_counted_open_music_request(q):
        return True
    generic_patterns = [
        r"^好听(的)?(歌|歌曲|音乐)$",
        r"^随便(来|放|找)?(点|些)?(歌|歌曲|音乐)?$",
        r"^(来|放|找)(点|些)?(歌|歌曲|音乐)$",
    ]
    return any(re.match(pattern, q) for pattern in generic_patterns)


def requested_song_count(query: str) -> int | None:
    q = query.strip()
    count_map = {
        "一": 1, "1": 1,
        "两": 2, "二": 2, "2": 2,
        "三": 3, "3": 3,
        "四": 4, "4": 4,
        "五": 5, "5": 5,
    }
    match = re.search(r"(?P<count>[一二两三四五1-5几])\s*(首|支|个|段)", q)
    if not match:
        return None
    raw = match.group("count")
    if raw == "几":
        return 3
    return count_map.get(raw)


def is_counted_open_music_request(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if is_creation_request(q):
        return False
    if extract_artist_song(q) or is_similar_artist_query(q) or is_artist_song_request(q) or recent_song_search_artist(q):
        return False
    if identify_artist(q):
        return False
    if not requested_song_count(q):
        return False
    has_music_object = contains_any(q, ["歌", "歌曲", "音乐", "曲子"])
    has_play_action = contains_any(q, ["放", "播放", "播", "来", "听", "听听", "推荐", "找", "挑"])
    return has_music_object and has_play_action


def strip_play_request_prefix(query: str) -> str:
    q = query.strip()
    q = re.sub(r"^(?:麻烦|请|帮我|给我|可以|能不能|能|想|我想|我要|我想要)\s*", "", q)
    q = re.sub(r"^(?:放|播放|播|听|听听|来|来点|来些|整|整点|搞点|安排|安排点|推荐|找|搜|挑)\s*", "", q)
    q = re.sub(r"^(?:一|1|几|两|二|三|四|五)?\s*(?:首|支|个|段|些|点)?\s*", "", q)
    return q.strip(" 《》。，,.!?？")


def play_request_target(query: str) -> dict[str, Any] | None:
    q = query.strip()
    if not q or is_favorite_request(q) or is_creation_request(q):
        return None
    if is_playback_control(q) or contains_any(q, ["这首", "当前", "现在这首", "刚才那首", "刚刚那首", "上一首", "下一首"]):
        return None
    if not re.search(r"^(?:麻烦|请|帮我|给我|可以|能不能|能|想|我想|我要|我想要)?\s*(?:放|播放|播|听|听听|来|来点|来些|整|整点|搞点|安排|安排点|推荐|找|搜|挑)", q):
        return None
    target = strip_play_request_prefix(q)
    if not target:
        return {"kind": "general", "target": q}
    matched = next((song for song in SONGS if normalize(song["title"]) == normalize(target)), None)
    if matched:
        return {"kind": "song", "target": matched["title"], "song": matched}
    artist = identify_artist(target) or identify_artist(q)
    if artist and contains_any(q, ["的歌", "歌曲", "作品", "歌手", "来点", "放点", "听点", "给我放", "播放"]):
        return {"kind": "artist", "target": artist}
    if contains_any(q, ["歌", "歌曲", "音乐", "曲子", "歌单"]) or query_traits(q) or modifier_reco_traits(q) or topic_reco_traits(q):
        return {"kind": "filtered", "target": q}
    if looks_like_bare_music_entity_query(target):
        return {"kind": "song", "target": target, "song": {"title": target, "artist": "", "traits": []}}
    return None


def is_topic_reco_query(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if is_generic_reco_query(q):
        return False
    if not contains_any(q, ["歌", "歌曲", "音乐", "曲子", "歌单"]):
        return False
    return bool(topic_reco_traits(q))


VARIETY_SHOW_MARKERS = [
    "乐队的夏天", "乐夏", "声生不息", "声生不息宝岛季", "中国好声音", "中国新歌声",
    "歌手", "我是歌手", "披荆斩棘", "乘风破浪", "天赐的声音", "中国新说唱",
    "说唱新世代", "明日之子", "我们的歌", "时光音乐会", "蒙面唱将猜猜猜",
    "梦想的声音", "快乐男声", "超级女声", "创造营", "青春有你", "这就是原创",
    "我是唱作人", "经典咏流传", "中国潮音", "闪光的乐队", "音浪合伙人",
]


def has_variety_show_marker(query: str) -> bool:
    return contains_any(query, VARIETY_SHOW_MARKERS) or any(
        item.get("type") == "collection" for item in linked_music_entities(query)
    )


def is_collection_limited_song_request(query: str) -> bool:
    q = query.strip()
    if not q:
        return False
    if extract_artist_song(q) or recent_song_search_artist(q):
        return False
    has_music_object = contains_any(q, ["歌", "歌曲", "音乐", "歌单", "作品", "民谣", "摇滚", "舞曲", "说唱", "港乐", "大vocal"])
    if not has_music_object:
        return False
    if has_variety_show_marker(q) and (
        contains_any(q, ["里", "里的", "相关", "曲库", "那种", "限定", "适合", "感"])
        or re.search(r"(?:的)?(?:歌|歌曲|音乐|作品)", q)
    ):
        return True
    collection_markers = ["节目", "综艺", "比赛", "竞演", "现场", "榜单", "厂牌", "音乐节"]
    return contains_any(q, collection_markers)


def classify(query: str) -> tuple[dict[str, Any], str]:
    artist = identify_artist(query)
    q = query.lower()
    matched_song = next((song for song in SONGS if normalize(song["title"]) in normalize(query)), None)
    artist_song = extract_artist_song(query)
    if is_favorite_request(query):
        return (
            {
                "domain": "function",
                "intent": "favorite",
                "entity_type": "unknown",
                "action": "classify",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            function_reply(query, "favorite"),
        )
    if is_playback_control(query):
        return (
            {
                "domain": "function",
                "intent": "control",
                "entity_type": "unknown",
                "action": "classify",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            function_reply(query, "control"),
        )
    similar_artist = is_similar_artist_query(query)
    if similar_artist:
        return (
            {
                "domain": "content_reco",
                "intent": "similar_reco",
                "entity_type": "artist",
                "action": "recommend",
                "identified": True,
                "reference": similar_artist,
                "target_entity": {"name": similar_artist, "artist": similar_artist, "album": ""},
                "traits": ["相似艺人", "音色相近", "声线参考"],
            },
            "",
        )
    play_target = play_request_target(query)
    if play_target:
        if play_target["kind"] == "song":
            song = play_target.get("song") or {}
            title = str(song.get("title") or play_target["target"])
            artist_name = str(song.get("artist") or "")
            return (
                {
                    "domain": "info_retrieval",
                    "intent": "entity_search",
                    "entity_type": "song",
                    "action": "play",
                    "identified": True,
                    "reference": f"{title} - {artist_name}".strip(" -"),
                    "target_entity": {"name": title, "artist": artist_name, "album": ""},
                    "traits": song.get("traits", []),
                },
                "",
            )
        if play_target["kind"] == "artist":
            artist_name = str(play_target["target"])
            return (
                {
                    "domain": "info_retrieval",
                    "intent": "entity_search",
                    "entity_type": "artist",
                    "action": "search",
                    "identified": True,
                    "reference": artist_name,
                    "target_entity": {"name": artist_name, "artist": artist_name, "album": ""},
                    "traits": artist_traits(artist_name),
                },
                "",
            )
        intent = "general_reco" if play_target["kind"] == "general" else "filtered_reco"
        return (
            {
                "domain": "content_reco",
                "intent": intent,
                "entity_type": "unknown",
                "action": "recommend",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": (topic_reco_traits(query) or query_traits(query) or modifier_reco_traits(query))[:6]
                or ["多样", "好入口", "流派覆盖"],
            },
            "",
        )
    recent_song_artist = recent_song_search_artist(query)
    if recent_song_artist:
        return (
            {
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "artist",
                "action": "search",
                "identified": True,
                "reference": recent_song_artist,
                "target_entity": {"name": recent_song_artist, "artist": recent_song_artist, "album": ""},
                "traits": ["新歌", "近期发行", "艺人歌曲"],
            },
            "",
        )
    if is_modifier_reco_query(query):
        return (
            {
                "domain": "content_reco",
                "intent": "filtered_reco",
                "entity_type": "unknown",
                "action": "recommend",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": (topic_reco_traits(query) or query_traits(query) or modifier_reco_traits(query))[:6],
            },
            "",
        )
    if is_music_qa_query(query):
        return (
            {
                "domain": "info_retrieval",
                "intent": "music_qa",
                "entity_type": "unknown",
                "action": "answer",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": artist or "", "album": ""},
                "traits": [],
            },
            "",
        )
    if is_state_only_chitchat(query):
        return (
            {
                "domain": "chitchat",
                "intent": "general_qa",
                "entity_type": "unknown",
                "action": "answer",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": [],
            },
            chitchat_reply(query),
        )
    similar_song = is_similar_song_query(query)
    if similar_song:
        return (
            {
                "domain": "content_reco",
                "intent": "similar_reco",
                "entity_type": "song",
                "action": "recommend",
                "identified": True,
                "reference": similar_song,
                "target_entity": {"name": similar_song, "artist": "", "album": ""},
                "traits": query_traits(query) or ["参照歌曲", "相似氛围", "相近听感", "可延展"],
            },
            "",
        )
    if artist_song:
        song_artist, song_title = artist_song
        return (
            {
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "song",
                "action": "play" if contains_any(query, ["播放", "放", "给我播", "听", "来几首", "推荐"]) else "search",
                "identified": True,
                "reference": f"{song_title} - {song_artist}",
                "target_entity": {"name": song_title, "artist": song_artist, "album": ""},
                "traits": ["单曲精搜", "明确歌手", "明确歌名"],
            },
            "",
        )
    if is_collection_limited_song_request(query):
        return (
            {
                "domain": "content_reco",
                "intent": "filtered_reco",
                "entity_type": "unknown",
                "action": "recommend",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": (topic_reco_traits(query) or query_traits(query) or modifier_reco_traits(query))[:6] or ["限定来源", "曲库推荐"],
            },
            "",
        )
    if matched_song and contains_any(query, ["播放", "放一下", "听", "起播"]):
        return (
            {
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "song",
                "action": "play",
                "identified": True,
                "reference": matched_song["title"],
                "target_entity": {"name": matched_song["title"], "artist": matched_song["artist"], "album": ""},
                "traits": matched_song.get("traits", []),
            },
            "",
        )
    feedback_traits = feedback_reco_traits(query)
    if feedback_traits:
        return (
            {
                "domain": "content_reco",
                "intent": "filtered_reco",
                "identified": True,
                "reference": query,
                "traits": feedback_traits,
            },
            "",
        )
    artist_request = is_artist_song_request(query)
    if artist_request:
        traits = artist_traits(artist_request)
        return (
            {
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": "artist",
                "action": "search",
                "identified": True,
                "reference": artist_request,
                "target_entity": {"name": artist_request, "artist": artist_request, "album": ""},
                "traits": traits,
            },
            "",
        )
    if is_generic_reco_query(query):
        count = requested_song_count(query)
        return (
            {
                "domain": "content_reco",
                "intent": "general_reco",
                "entity_type": "unknown",
                "action": "play" if count else "recommend",
                "identified": True,
                "reference": query,
                "target_entity": {"name": "", "artist": "", "album": ""},
                "traits": ["多样", "好入口", "流派覆盖", "不过分头部"],
                **({"count": count} if count else {}),
            },
            "",
        )
    if is_topic_reco_query(query):
        return (
            {
                "domain": "content_reco",
                "intent": "filtered_reco",
                "identified": True,
                "reference": query,
                "traits": topic_reco_traits(query),
            },
            "",
        )
    if contains_any(query, ["来点", "推荐", "适合", "想听", "听点", "听些", "随便", "放点", "找"]):
        traits = query_traits(query)
        if contains_any(query, ["关于", "梦想", "青春", "爱情", "孤独", "自由", "希望", "告别", "怀念", "城市", "夏天"]):
            traits = list(dict.fromkeys([*traits, "主题表达", "情绪叙事"]))[:6]
        return (
            {
                "domain": "content_reco",
                "intent": "filtered_reco" if traits else "general_reco",
                "identified": True,
                "reference": query,
                "traits": traits or ["多样", "好入口", "流派覆盖", "不过分头部"],
            },
            "",
        )
    if looks_like_bare_music_entity_query(query):
        ref = artist or query.strip()
        looks_like_title = bool(re.search(r"[,!:;()\\[\\]]", query)) or len(query.split()) >= 3
        entity_type = "song" if matched_song or (not artist and looks_like_title) else ("artist" if artist else "unknown")
        target_artist = matched_song["artist"] if matched_song else (artist or "")
        return (
            {
                "domain": "info_retrieval",
                "intent": "entity_search",
                "entity_type": entity_type,
                "action": "search",
                "identified": True,
                "reference": ref,
                "target_entity": {"name": query.strip(), "artist": target_artist, "album": ""},
                "traits": matched_song.get("traits", []) if matched_song else (artist_traits(ref) if artist else []),
            },
            "",
        )
    if contains_any(query, ["写一首", "帮我写", "歌词", "改成", "续写", "混音", "人声分离", "加点混响", "升一个调", "剪"]):
        intent = "lyrics" if "歌词" in query else "music_gen"
        if contains_any(query, ["改成", "改编"]):
            intent = "adaptation"
        if contains_any(query, ["续写", "接着写"]):
            intent = "continuation"
        if contains_any(query, ["混音", "母带"]):
            intent = "mixing"
        if contains_any(query, ["人声分离", "去掉人声"]):
            intent = "vocal_separation"
        return (
            {
                "domain": "creation",
                "intent": intent,
                "identified": True,
                "reference": query,
                "traits": [],
            },
            "识别为创作/编辑意图，当前复刻版只展示分类结果。",
        )
    if artist and contains_any(query, ["的歌", "歌曲", "播放", "听", "来点"]):
        traits = artist_traits(artist)
        return (
            {
                "domain": "info_retrieval",
                "intent": "entity_search",
                "identified": True,
                "reference": artist,
                "traits": traits,
            },
            "",
        )
    if contains_any(query, ["类似", "相似", "像", "这种", "那种", "风格", "同款"]):
        ref = artist or reference_from_song(query) or query
        return (
            {
                "domain": "content_reco",
                "intent": "similar_reco",
                "identified": True,
                "reference": ref,
                "traits": query_traits(query) or ["参照气质", "相似氛围", "相近圈层", "可延展"],
            },
            "",
        )
    if query_traits(query):
        return (
            {
                "domain": "content_reco",
                "intent": "filtered_reco",
                "identified": True,
                "reference": query,
                "traits": query_traits(query),
            },
            "",
        )
    if contains_any(query, ["在吗", "你好", "谢谢"]):
        return (
            {
                "domain": "chitchat",
                "intent": "chitchat",
                "identified": True,
                "reference": query,
                "traits": [],
            },
            "我在。可以直接告诉我你现在想听的情绪、场景或风格。",
        )
    return (
        {
            "domain": "chitchat",
            "intent": "general_qa",
            "identified": True,
            "reference": query,
            "traits": [],
        },
        "这个问题不太像音乐需求。你可以换成“适合深夜开车的歌”这类描述试试。",
    )


def answer_qa(query: str) -> str:
    if "世界杯" in query and contains_any(query, ["主题曲", "官方歌", "anthem", "主题歌"]):
        return "2026 年世界杯官方歌曲是《DNA (More Than A Game)》- Andrea Bocelli、David Guetta、EJAE、Megan Thee Stallion。"
    if "许嵩" in query and "生日" in query:
        return "许嵩生日是 1986 年 5 月 14 日。"
    if "晴天" in query and "谁唱" in query:
        return "《晴天》由周杰伦演唱。"
    if "后来" in query and ("原曲" in query or "翻唱" in query):
        return "《后来》的旋律源自 Kiroro 的《未来へ》，刘若英演唱的华语版本更广为人知。"
    return ""


def artist_traits(artist: str) -> list[str]:
    traits: list[str] = []
    for song in SONGS:
        if song["artist"] == artist:
            traits.extend(song["traits"])
    return list(dict.fromkeys(traits))[:6] or ["真实歌手", "代表作", "精搜"]


def reference_from_song(query: str) -> str | None:
    compact = normalize(query)
    for song in sorted(SONGS, key=lambda item: len(normalize(str(item.get("title") or ""))), reverse=True):
        if normalize(song["title"]) in compact:
            return f"{song['title']} - {song['artist']}"
    for (artist, title) in sorted(SIMILAR_SONG_MEMORY, key=lambda item: len(normalize(item[0][1])), reverse=True):
        if normalize(title) in compact:
            return f"{title} - {artist}"
    signature_rows = [
        (artist, title)
        for artist, titles in ARTIST_SIGNATURE_SONGS.items()
        for title in titles
    ]
    for artist, title in sorted(signature_rows, key=lambda item: len(normalize(item[1])), reverse=True):
        if normalize(title) in compact:
            return f"{title} - {artist}"
    return None


def similar_song_profile(query: str, analysis: dict[str, Any]) -> dict[str, Any] | None:
    text = " ".join(
        [
            query,
            str(analysis.get("reference") or ""),
            str((analysis.get("target_entity") or {}).get("name") or ""),
            str((analysis.get("target_entity") or {}).get("artist") or ""),
        ]
    )
    compact = normalize(text)
    for (artist, title), profile in sorted(SIMILAR_SONG_MEMORY.items(), key=lambda item: len(normalize(item[0][1])), reverse=True):
        identified_artist = identify_artist(text)
        if normalize(title) in compact and (normalize(artist) in compact or not identified_artist or identified_artist == artist):
            return {"artist": artist, "title": title, **profile}
    for (artist, title), profile in sorted(SIMILAR_SONG_MEMORY.items(), key=lambda item: len(normalize(item[0][1])), reverse=True):
        if normalize(title) in compact:
            return {"artist": artist, "title": title, **profile}
    for song in sorted(SONGS, key=lambda item: len(normalize(str(item.get("title") or ""))), reverse=True):
        title = str(song.get("title") or "")
        artist = str(song.get("artist") or "")
        identified_artist = identify_artist(text)
        if normalize(title) in compact and (normalize(artist) in compact or not identified_artist or identified_artist == artist):
            return {
                "artist": artist,
                "title": title,
                "traits": list(dict.fromkeys([
                    *song.get("traits", []),
                    *song.get("genres", []),
                    *song.get("moods", []),
                    *song.get("scenes", []),
                ]))[:8],
                "songs": [],
            }
    signature_rows = [
        (artist, title)
        for artist, titles in ARTIST_SIGNATURE_SONGS.items()
        for title in titles
    ]
    for artist, title in sorted(signature_rows, key=lambda item: len(normalize(item[1])), reverse=True):
        if normalize(title) in compact:
            identified_artist = identify_artist(text)
            if normalize(artist) in compact or not identified_artist or identified_artist == artist:
                traits = [
                    str(item)
                    for item in (analysis.get("traits") or [])
                    if str(item) not in {"相似艺人", "音色相近", "声线参考", "相似延展"}
                ]
                return {"artist": artist, "title": title, "traits": traits or artist_traits(artist), "songs": []}
    quoted = re.search(r"《([^》]{1,80})》", text)
    if quoted:
        title = quoted.group(1).strip()
        artist = identify_artist(text) or ""
        if artist:
            return {"artist": artist, "title": title, "traits": analysis.get("traits") or [], "songs": []}
    return None


def similar_song_groups(query: str, analysis: dict[str, Any]) -> list[dict[str, Any]]:
    profile = similar_song_profile(query, analysis)
    if not profile:
        return []
    source_artist = str(profile.get("artist") or "")
    source_title = str(profile.get("title") or "")
    songs = []
    seen: set[tuple[str, str]] = set()
    same_artist_count = 0
    for artist, title, reason in profile.get("songs") or []:
        key = (normalize(title), normalize(artist))
        source_key = (normalize(source_title), normalize(source_artist))
        if key in seen or key == source_key:
            continue
        if artist == source_artist:
            same_artist_count += 1
            if same_artist_count > 2:
                continue
        seen.add(key)
        songs.append(
            {
                "title": title,
                "artist": artist,
                "reason": reason,
                "verified": True,
                "source": "similar_song_memory",
                "url": song_external_url(title, artist),
                "spotify_search": f"https://open.spotify.com/search/{quote_plus(title + ' ' + artist)}",
            }
        )
        if len(songs) >= 5:
            break
    if not songs:
        synthetic_analysis = {
            **analysis,
            "intent": "similar_reco",
            "reference": f"{source_title} - {source_artist}",
            "target_entity": {"name": source_title, "artist": source_artist, "album": ""},
            "traits": list(dict.fromkeys([*(analysis.get("traits") or []), *(profile.get("traits") or [])]))[:8],
        }
        candidates = backfill_similar_song_candidates([], synthetic_analysis, max_count=5, query=query)
        songs = [song for _, song in candidates[:5]]
    return [{"title": f"类似《{source_title}》的歌曲", "songs": songs}]


def query_traits(query: str) -> list[str]:
    buckets = [
        ("深夜", ["深夜", "夜晚", "凌晨", "半夜"]),
        ("开车", ["开车", "驾驶", "公路"]),
        ("雨天", ["雨天", "下雨"]),
        ("居家", ["在家", "窝着", "不想出门"]),
        ("睡前/助眠", ["睡前", "助眠", "睡觉", "我要睡了"]),
        ("庆祝", ["生日", "庆祝", "派对"]),
        ("浪漫", ["浪漫", "情歌", "甜蜜", "心动", "表白"]),
        ("跑步/健身", ["跑步", "健身", "训练", "热血"]),
        ("伤感", ["伤感", "悲伤", "失恋", "想哭", "emo"]),
        ("治愈", ["治愈", "温暖", "安慰"]),
        ("英文", ["英文", "英语", "english"]),
        ("电子", ["电子", "edm", "合成器"]),
        ("摇滚", ["摇滚", "乐队"]),
        ("民谣", ["民谣", "folk"]),
        ("钢琴/纯音乐", ["钢琴", "纯音乐", "器乐"]),
        ("暗黑流行", ["billie", "暗黑", "低语"]),
        ("Dream Pop", ["dream pop", "dream-pop", "梦幻流行"]),
        ("乐队的夏天", ["乐队的夏天", "乐夏"]),
    ]
    found = [label for label, words in buckets if contains_any(query, words)]
    return list(dict.fromkeys(found))[:6]


def score_song(song: dict[str, Any], query: str, analysis: dict[str, Any]) -> float:
    text = " ".join(
        [
            song["title"],
            song["artist"],
            *song.get("traits", []),
            *song.get("genres", []),
            *song.get("moods", []),
            *song.get("scenes", []),
        ]
    )
    score = 0.0
    for trait in analysis.get("traits", []):
        if trait in text:
            score += 2.2
    for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", query):
        if len(token) >= 2 and token.lower() in text.lower():
            score += 1.0
    if analysis["intent"] == "entity_search" and song["artist"] == analysis["reference"]:
        score += 8.0
    if "英文" in analysis.get("traits", []) and re.search(r"[A-Za-z]", song["artist"]):
        score += 2.0
    if "不要" in query and ("周杰伦" in query or "Jay" in query) and song["artist"] == "周杰伦":
        score -= 10.0
    score += random.Random(song["title"] + query).random() * 0.6
    return score


def reason_for(song: dict[str, Any], analysis: dict[str, Any]) -> str:
    traits = "、".join(song.get("traits", [])[:3])
    if analysis["intent"] == "entity_search":
        return f"这是 {song['artist']} 的代表性作品之一，{traits} 的特征很突出，适合精搜场景直接播放。"
    if analysis["intent"] == "similar_reco":
        return f"它和「{analysis['reference']}」共享 {traits} 的气质，但歌手和表达角度不同，适合扩展同类听感。"
    return f"匹配本次需求里的 {('、'.join(analysis.get('traits', [])[:3]) or '场景/情绪')}，歌曲本身带有 {traits} 的听感。"


def build_groups(query: str, analysis: dict[str, Any], n: int) -> list[dict[str, Any]]:
    single_play = single_play_target_group(analysis)
    if single_play:
        return single_play
    if (
        analysis.get("intent") == "similar_reco"
        and analysis.get("entity_type") in {"song", "unknown"}
        and contains_any(query, ["类似", "相似", "像", "同款", "这种", "那种"])
    ):
        groups = similar_song_groups(query, analysis)
        if groups:
            return groups
    if analysis.get("intent") == "similar_reco" and analysis.get("entity_type") == "artist":
        artist = canonical_artist_name(str(analysis.get("reference") or ""))
        target = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
        artist = canonical_artist_name(str(target.get("artist") or target.get("name") or artist))
        groups = similar_artist_groups(artist)
        if groups:
            return groups
    if analysis.get("intent") == "entity_search":
        reference_artist = canonical_artist_name(str(analysis.get("reference") or ""))
        target = analysis.get("target_entity") if isinstance(analysis.get("target_entity"), dict) else {}
        reference_artist = canonical_artist_name(str(target.get("artist") or target.get("name") or reference_artist))
        if reference_artist:
            analysis = {**analysis, "reference": reference_artist}
    ranked = sorted(SONGS, key=lambda item: score_song(item, query, analysis), reverse=True)
    if analysis["intent"] == "entity_search":
        ranked = [song for song in ranked if song["artist"] == analysis["reference"]]
        if not ranked:
            artist = str(analysis.get("reference") or "")
            apple_songs = apple_music_artist_songs(artist, limit=max(5, min(n, 8)))
            if apple_songs:
                return [{"title": f"{artist} · Apple Music 搜索结果", "songs": apple_songs}]
    else:
        seen_songs: set[tuple[str, str]] = set()
        deduped = []
        for song in ranked:
            song_key = (normalize(song["title"]), normalize(song["artist"]))
            if song_key in seen_songs:
                continue
            seen_songs.add(song_key)
            deduped.append(song)
        ranked = deduped
    picked = ranked[: max(6, min(n, 15))]

    groups: dict[str, list[dict[str, Any]]] = {
        "同氛围": [],
        "同场景": [],
        "同圈层/流派": [],
    }
    for idx, song in enumerate(picked):
        item = {
            **song,
            "reason": reason_for(song, analysis),
            "verified": True,
            "source": "local",
            "url": song_external_url(song['title'], song['artist']),
            "spotify_search": f"https://open.spotify.com/search/{quote_plus(song['title'] + ' ' + song['artist'])}",
        }
        if idx % 3 == 0:
            groups["同氛围"].append(item)
        elif idx % 3 == 1:
            groups["同场景"].append(item)
        else:
            groups["同圈层/流派"].append(item)
    if analysis["intent"] == "entity_search":
        artist_groups = [{"title": f"{analysis['reference']} · 代表作品", "songs": [song for songs in groups.values() for song in songs]}]
        return prioritize_artist_signature_songs(query, analysis, artist_groups)
    return [{"title": title, "songs": songs} for title, songs in groups.items() if songs]


@app.get("/providers")
async def providers() -> dict[str, Any]:
    statuses = provider_status()
    return {
        "providers": statuses,
        "default": default_provider_id(statuses),
    }


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    statuses = provider_status()
    configured = [
        item["id"]
        for item in statuses
        if item["id"] != "local" and item.get("configured")
    ]
    return {
        "ok": True,
        "auth_enabled": demo_auth_enabled(),
        "configured_providers": configured,
        "default_provider": default_provider_id(statuses),
    }


@app.post("/recommend/start")
async def recommend_start(req: RecommendReq) -> dict[str, Any]:
    started_at = time.time()
    query = req.query.strip()
    context = sanitize_context_payload(req.context)
    control_result = classify_context_control(query, context)
    if control_result:
        result = {"query": query, "provider": req.provider, **control_result}
        logger.info("recommend_start_sync_control provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
        return {"mode": "sync", "result": attach_pending_dj(result)}

    if req.provider not in PROVIDERS:
        logger.info("recommend_start_sync_local provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
        return {"mode": "sync", "result": await recommend(req)}

    context_artist_result = classify_context_artist_search(query, context, req.n)
    if context_artist_result:
        result = {"query": query, "provider": req.provider, **context_artist_result}
        logger.info("recommend_start_sync_context_artist provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
        return {"mode": "sync", "result": attach_pending_dj(result)}

    context_result = classify_context_reference(query, context)
    if context_result:
        result = {"query": query, "provider": req.provider, **context_result}
        logger.info("recommend_start_sync_context provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
        return {"mode": "sync", "result": attach_pending_dj(result)}

    skeleton = skeleton_payload(query, req.provider)
    if skeleton["analysis"].get("intent") in DIALOGUE_INTENTS or skeleton["analysis"].get("domain") == "chitchat":
        try:
            get_client(req.provider)
            result = await dialogue_payload_with_known_answer(query, req.provider, skeleton["analysis"], context)
            logger.info("recommend_start_sync_dialogue provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
            return {"mode": "sync", "result": result}
        except Exception as exc:
            logger.error("recommend_start_dialogue_fallback provider=%s query=%r error=%s", req.provider, query, exc)
            fallback_text = chitchat_reply(query)
            if skeleton["analysis"].get("intent") == "music_qa":
                fallback_text = "我这边暂时没拿到稳定资料，先不乱讲。你可以换个问法，或者让我直接放几首相关代表作。"
            result = {
                **skeleton,
                "answer": fallback_text,
                "dj": speech_only_dj_response(fallback_text, program_title="Melodio 音乐百科" if skeleton["analysis"].get("intent") == "music_qa" else "Melodio"),
            }
            logger.info("recommend_start_sync_dialogue_fallback provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
            return {"mode": "sync", "result": result}

    if skeleton["analysis"]["intent"] not in SONG_INTENTS:
        try:
            get_client(req.provider)
            data = await get_online_recommendations(query, req.n, req.provider, context)
            result = attach_pending_dj({"query": query, "provider": req.provider, **data})
            logger.info("recommend_start_sync_answer provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
            return {"mode": "sync", "result": result}
        except Exception as exc:
            logger.error("recommend_start_answer_fallback provider=%s query=%r error=%s", req.provider, query, exc)
            result = attach_pending_dj(skeleton)
            logger.info("recommend_start_sync_skeleton_answer provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
            return {"mode": "sync", "result": result}

    if (
        skeleton["analysis"].get("intent") == "entity_search"
        and skeleton["analysis"].get("entity_type") == "song"
        and skeleton["analysis"].get("action") == "play"
    ):
        skeleton["analysis"]["action"] = "play"
        data = clean_model_payload(
            {
                "analysis": skeleton["analysis"],
                "answer": "",
                "entities": [],
                "groups": [],
            },
            query,
            prioritize_playable=False,
        )
        data["analysis"]["action"] = "play"
        result = attach_pending_dj({"query": query, "provider": req.provider, **data})
        logger.info("recommend_start_sync_exact_song provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
        return {"mode": "sync", "result": result}

    try:
        get_client(req.provider)
    except Exception as exc:
        return {"mode": "error", "error": str(exc), "skeleton": skeleton}

    cache_key = (req.provider, query.lower(), req.n, context_cache_key(context))
    cached = _online_cache.get(cache_key)
    if cached and time.time() - cached[0] < CACHE_TTL_SECONDS:
        data = json.loads(json.dumps(cached[1], ensure_ascii=False))
        data["cached"] = True
        result = attach_pending_dj({"query": query, "provider": req.provider, **data})
        logger.info("recommend_start_sync_cache provider=%s query=%r elapsed=%.3f", req.provider, query, time.time() - started_at)
        return {"mode": "sync", "result": result}

    job_id = uuid.uuid4().hex
    _jobs[job_id] = {
        "status": "pending",
        "query": query,
        "provider": req.provider,
        "context": context,
        "skeleton": skeleton,
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    create_task(run_online_job(job_id, query, req.n, req.provider, context))
    logger.info("recommend_start_async job_id=%s provider=%s query=%r elapsed=%.3f", job_id, req.provider, query, time.time() - started_at)
    return {"mode": "async", "job_id": job_id, "skeleton": skeleton}


@app.get("/recommend/status/{job_id}")
async def recommend_status(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if not job:
        return {"status": "error", "error": "任务不存在或已过期。"}
    return job


@app.post("/radio/continue")
async def radio_continue(req: RadioContinueReq) -> dict[str, Any]:
    started_at = time.time()
    context = sanitize_context_payload(req.context)
    analysis = req.analysis if isinstance(req.analysis, dict) else {}
    groups = sanitize_groups_payload(req.groups, max_groups=5, max_songs=10)
    base_query = safe_text(req.query, 500) or safe_text(analysis.get("reference") if isinstance(analysis, dict) else "", 500)
    if not analysis:
        analysis = skeleton_payload(base_query or "继续推荐歌曲", req.provider).get("analysis") or {}
    if analysis.get("intent") not in SONG_INTENTS:
        analysis = {
            **analysis,
            "domain": "content_reco",
            "intent": "filtered_reco",
            "action": "recommend",
            "identified": True,
        }
    exclude = [sanitize_song_payload(song) for song in (req.exclude or []) if isinstance(song, dict)]
    query = continuation_query(base_query, analysis, groups, exclude)
    n = max(5, min(int(req.n or 5), 8))
    provider = safe_text(req.provider, 40) or "local"
    try:
        if provider in PROVIDERS:
            data = await get_online_recommendations(query, n, provider, context)
        else:
            data = clean_model_payload(
                {"analysis": analysis, "groups": build_groups(query, analysis, n)},
                query,
                prioritize_playable=False,
            )
    except Exception as exc:
        logger.warning("radio_continue_model_fallback provider=%s query=%r error=%s", provider, base_query, exc)
        data = clean_model_payload(
            {"analysis": analysis, "groups": build_groups(query, analysis, n)},
            query,
            prioritize_playable=False,
        )
    next_groups = filter_excluded_groups(data.get("groups") if isinstance(data.get("groups"), list) else [], exclude, limit=5)
    result = {
        "query": base_query,
        "provider": provider,
        "analysis": data.get("analysis") if isinstance(data.get("analysis"), dict) else analysis,
        "answer": "",
        "entities": [],
        "groups": next_groups,
    }
    logger.info(
        "radio_continue_done provider=%s base_query=%r songs=%s elapsed=%.3f",
        provider,
        base_query,
        len(flatten_group_songs(next_groups, limit=10)),
        time.time() - started_at,
    )
    return result


@app.post("/netease-player")
async def netease_player(req: PlayerReq) -> dict[str, Any]:
    try:
        return await run_in_threadpool(fetch_netease_player, req.title, req.artist)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"网易云播放器解析失败：{exc}",
            "query": f"{req.title} {req.artist}".strip(),
        }


@app.post("/music-player")
async def music_player(req: PlayerReq) -> dict[str, Any]:
    return await run_in_threadpool(fetch_music_player, req.title, req.artist)


@app.post("/music-streams")
async def music_streams(req: StreamReq) -> dict[str, Any]:
    started_at = time.time()
    rows = await run_in_threadpool(fetch_music_streams, req.songs, req.offset)
    ok_count = sum(1 for row in rows if row.get("ok") and row.get("stream_url"))
    logger.info("music_streams_done songs=%s offset=%s ok=%s elapsed=%.3f", len(req.songs), req.offset, ok_count, time.time() - started_at)
    return {"tracks": rows}


@app.post("/dj/tts")
async def dj_tts(req: DjTtsReq) -> dict[str, Any]:
    started_at = time.time()
    try:
        dj_payload = req.dj if isinstance(req.dj, dict) else {}
        dj = await run_in_threadpool(attach_tts_to_dj, dj_payload)
        logger.info("dj_tts_done segments=%s elapsed=%.3f", len(dj.get("segments") or []), time.time() - started_at)
        return {"dj": dj}
    except Exception as exc:
        logger.error("dj_tts_error elapsed=%.3f error=%s\n%s", time.time() - started_at, exc, traceback.format_exc())
        return {"error": "DJ 语音生成失败，歌曲可以继续播放。", "dj": req.dj if isinstance(req.dj, dict) else {}}


@app.get("/doubao-tts/status")
async def doubao_tts_status() -> dict[str, Any]:
    return {
        "configured": doubao_tts_configured(),
        "endpoint": bool(DOUBAO_TTS_ENDPOINT),
        "api_key": bool(DOUBAO_TTS_API_KEY),
        "app_key": bool(DOUBAO_TTS_APP_ID),
        "access_key": bool(DOUBAO_TTS_ACCESS_KEY),
        "resource_id": DOUBAO_TTS_RESOURCE_ID,
        "speaker": DOUBAO_TTS_SPEAKER,
        "model": DOUBAO_TTS_MODEL,
        "format": DOUBAO_TTS_FORMAT,
        "speech_rate": DOUBAO_TTS_SPEECH_RATE,
        "loudness_rate": DOUBAO_TTS_LOUDNESS_RATE,
        "emotion": DOUBAO_TTS_EMOTION,
    }


@app.get("/doubao-tts/stream")
async def doubao_tts_stream(text: str, speaker: str = "", speech_rate: Optional[int] = None, loudness_rate: Optional[int] = None, emotion: str = ""):
    clean_text = safe_text(text, 500)
    clean_speaker = safe_text(speaker, 120)
    clean_emotion = safe_text(emotion, 80)
    if not clean_text:
        return JSONResponse({"error": "请输入要合成的文本。"}, status_code=400)
    if not doubao_tts_configured():
        return JSONResponse({"error": "豆包 TTS 尚未配置 key。"}, status_code=400)
    try:
        return StreamingResponse(
            await run_in_threadpool(
                lambda: stream_doubao_tts(
                    clean_text,
                    clean_speaker or None,
                    speech_rate=speech_rate,
                    loudness_rate=loudness_rate,
                    emotion=clean_emotion,
                )
            ),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as exc:
        logger.error("doubao_tts_stream_error error=%s\n%s", exc, traceback.format_exc())
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.get("/minimax-tts-ws/status")
async def minimax_tts_ws_status() -> dict[str, Any]:
    return {
        "configured": minimax_tts_configured(),
        "endpoint": bool(MINIMAX_TTS_WS_ENDPOINT),
        "api_key": bool(MINIMAX_API_KEY),
        "group_id": bool(MINIMAX_GROUP_ID),
        "model": MINIMAX_TTS_MODEL,
        "voice_id": MINIMAX_TTS_VOICE_ID,
        "format": "mp3",
    }


@app.get("/minimax-tts-ws/stream")
async def minimax_tts_ws_stream(text: str, voice_id: str = ""):
    clean_text = safe_text(text, 1000)
    clean_voice = safe_text(voice_id or MINIMAX_TTS_VOICE_ID, 160)
    if not clean_text:
        return JSONResponse({"error": "请输入要合成的文本。"}, status_code=400)
    if not minimax_tts_configured():
        return JSONResponse({"error": "MiniMax TTS WebSocket 尚未配置 key。"}, status_code=400)
    try:
        return StreamingResponse(
            stream_minimax_tts_ws(clean_text, clean_voice or None),
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "no-store",
                "Access-Control-Allow-Origin": "*",
            },
        )
    except Exception as exc:
        logger.error("minimax_tts_ws_stream_error error=%s\n%s", exc, traceback.format_exc())
        return JSONResponse({"error": str(exc)}, status_code=400)


@app.post("/tts/preview")
async def tts_preview(req: TtsPreviewReq) -> dict[str, Any]:
    provider = safe_text(req.provider, 30).lower()
    text = safe_text(req.text, 500)
    if not text:
        return {"ok": False, "error": "请输入测试文案。"}
    if provider == "doubao":
        speaker = safe_text(req.speaker or req.voice_id or DOUBAO_TTS_SPEAKER, 120)
        if not doubao_tts_configured():
            return {"ok": False, "error": "豆包 TTS 尚未配置 key。"}
        return {
            "ok": True,
            "provider": "doubao",
            "voice_id": speaker,
            "audio_url": f"/doubao-tts/stream?text={quote_plus(text)}&speaker={quote_plus(speaker)}&ts={int(time.time() * 1000)}",
            "streaming": True,
        }
    if provider == "minimax":
        voice_id = safe_text(req.voice_id or req.speaker or MINIMAX_TTS_VOICE_ID, 160)
        if not MINIMAX_API_KEY:
            return {"ok": False, "error": "MiniMax TTS 尚未配置 key。"}
        try:
            audio_url = await run_in_threadpool(synthesize_minimax_tts, text, {"type": "quick_touch"}, voice_id_override=voice_id)
        except Exception as exc:
            logger.error("tts_preview_minimax_error voice=%s error=%s\n%s", voice_id, exc, traceback.format_exc())
            return {"ok": False, "error": str(exc)}
        return {
            "ok": bool(audio_url),
            "provider": "minimax",
            "voice_id": voice_id,
            "audio_url": audio_url,
            "streaming": False,
        }
    if provider == "minimax_ws":
        voice_id = safe_text(req.voice_id or req.speaker or MINIMAX_TTS_VOICE_ID, 160)
        if not minimax_tts_configured():
            return {"ok": False, "error": "MiniMax TTS WebSocket 尚未配置 key。"}
        return {
            "ok": True,
            "provider": "minimax_ws",
            "voice_id": voice_id,
            "audio_url": f"/minimax-tts-ws/stream?text={quote_plus(text)}&voice_id={quote_plus(voice_id)}&ts={int(time.time() * 1000)}",
            "streaming": True,
        }
    return {"ok": False, "error": f"不支持的 TTS provider：{provider}"}


@app.post("/dj/build")
async def dj_build(req: DjBuildReq) -> dict[str, Any]:
    started_at = time.time()
    analysis = sanitize_analysis_payload(req.analysis)
    groups = sanitize_groups_payload(req.groups)
    context = sanitize_context_payload(req.context)
    result = {
        "query": req.query,
        "provider": req.provider,
        "analysis": analysis,
        "groups": groups,
        "entities": [],
        "answer": safe_text(req.answer, 800),
    }
    try:
        built = await attach_dj_response(result, context, include_tts=False)
        logger.info("dj_build_done provider=%s query=%r groups=%s elapsed=%.3f", req.provider, req.query, len(groups), time.time() - started_at)
        return {"dj": built.get("dj") or pending_dj_response(req.query, analysis, groups)}
    except Exception as exc:
        logger.error("dj_build_error provider=%s query=%r elapsed=%.3f error=%s\n%s", req.provider, req.query, time.time() - started_at, exc, traceback.format_exc())
        return {"dj": fallback_dj_response(req.query, analysis, groups, safe_error_message(exc))}


async def transcribe_audio_with_gemini(audio_base64: str, mime_type: str) -> str:
    api_key = str(PROVIDERS.get("gemini", {}).get("key") or "").strip()
    if not api_key:
        raise RuntimeError("未配置 GEMINI_API_KEY，无法使用语音输入兜底识别。")
    model = os.getenv("GEMINI_ASR_MODEL", "").strip() or str(PROVIDERS["gemini"].get("model") or "gemini-2.5-flash")
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{quote(model, safe='')}:generateContent?key={quote_plus(api_key)}"
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {
                        "text": (
                            "请把这段中文语音转成适合音乐搜索/播放助手使用的一句话。"
                            "只输出转写文本，不要解释，不要加标点之外的其他内容。"
                        )
                    },
                    {"inline_data": {"mime_type": mime_type or "audio/webm", "data": audio_base64}},
                ],
            }
        ],
        "generationConfig": {"temperature": 0.0},
    }

    def call() -> str:
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
        candidates = data.get("candidates") if isinstance(data, dict) else []
        if not candidates:
            raise RuntimeError(f"Gemini ASR 未返回结果：{data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text") or "") for part in parts if isinstance(part, dict)).strip()
        return re.sub(r"\s+", " ", text).strip(" \n\t\"“”")

    return await run_in_threadpool(call)


def doubao_asr_configured() -> bool:
    return bool(DOUBAO_ASR_ENDPOINT and DOUBAO_ASR_API_KEY and DOUBAO_ASR_RESOURCE_ID)


def doubao_asr_header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes([
        (ASR_PROTOCOL_VERSION << 4) | ASR_HEADER_SIZE,
        (message_type << 4) | flags,
        (serialization << 4) | compression,
        0,
    ])


def doubao_asr_full_request(seq: int, payload: dict[str, Any]) -> bytes:
    body = gzip.compress(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    header = doubao_asr_header(ASR_FULL_CLIENT_REQUEST, ASR_POS_SEQUENCE, ASR_JSON_SERIALIZATION, ASR_GZIP)
    return header + struct.pack(">iI", seq, len(body)) + body


def doubao_asr_audio_request(seq: int, audio: bytes, *, final: bool = False) -> bytes:
    body = gzip.compress(audio)
    flags = ASR_NEG_SEQUENCE if final else ASR_POS_SEQUENCE
    signed_seq = -abs(seq) if final else abs(seq)
    header = doubao_asr_header(ASR_AUDIO_ONLY_REQUEST, flags, ASR_NO_SERIALIZATION, ASR_GZIP)
    return header + struct.pack(">iI", signed_seq, len(body)) + body


def doubao_asr_parse_frame(frame: bytes) -> dict[str, Any]:
    if len(frame) < 4:
        return {"event": "error", "error": "豆包 ASR 返回了空响应。"}
    header_size = (frame[0] & 0x0F) * 4
    message_type = frame[1] >> 4
    flags = frame[1] & 0x0F
    serialization = frame[2] >> 4
    compression = frame[2] & 0x0F
    offset = header_size
    seq: int | None = None
    if flags in {ASR_POS_SEQUENCE, ASR_NEG_SEQUENCE} and len(frame) >= offset + 4:
        seq = struct.unpack(">i", frame[offset:offset + 4])[0]
        offset += 4
    if len(frame) < offset + 4:
        return {"event": "error", "error": "豆包 ASR 响应缺少 payload。", "seq": seq}
    payload_size = struct.unpack(">I", frame[offset:offset + 4])[0]
    offset += 4
    payload = frame[offset:offset + payload_size]
    if compression == ASR_GZIP and payload:
        try:
            payload = gzip.decompress(payload)
        except Exception:
            pass
    if message_type == ASR_SERVER_ERROR_RESPONSE:
        error_text = payload.decode("utf-8", errors="ignore") if payload else "豆包 ASR 返回错误。"
        try:
            parsed = json.loads(error_text)
            error_text = json.dumps(parsed, ensure_ascii=False)
        except Exception:
            pass
        return {"event": "error", "error": error_text, "seq": seq}
    parsed_payload: Any = None
    if payload:
        if serialization == ASR_JSON_SERIALIZATION or payload[:1] in (b"{", b"["):
            try:
                parsed_payload = json.loads(payload.decode("utf-8", errors="ignore"))
            except Exception:
                parsed_payload = payload.decode("utf-8", errors="ignore")
        else:
            parsed_payload = payload.decode("utf-8", errors="ignore")
    text = extract_asr_text(parsed_payload)
    event = "partial"
    if seq is not None and seq < 0:
        event = "final"
    elif isinstance(parsed_payload, dict):
        raw_event = str(parsed_payload.get("event") or parsed_payload.get("type") or "").lower()
        if "final" in raw_event or parsed_payload.get("is_final") is True or parsed_payload.get("utterances"):
            event = "final"
    return {"event": event, "text": text, "seq": seq, "payload": parsed_payload}


def extract_asr_text(payload: Any) -> str:
    texts: list[str] = []

    def visit(value: Any, key: str = "") -> None:
        if value is None:
            return
        if isinstance(value, str):
            if key.lower() in {"text", "utterance", "transcript", "result", "sentence"} and value.strip():
                texts.append(value.strip())
            return
        if isinstance(value, list):
            for item in value:
                visit(item, key)
            return
        if isinstance(value, dict):
            for text_key in ("text", "utterance", "transcript", "sentence"):
                raw = value.get(text_key)
                if isinstance(raw, str) and raw.strip():
                    texts.append(raw.strip())
            for child_key, child in value.items():
                visit(child, str(child_key))

    visit(payload)
    if not texts:
        return ""
    # 上游有时会同时返回整句和分词，取最长的一条更接近实时展示需要。
    return max((re.sub(r"\s+", " ", text).strip() for text in texts), key=len, default="")


async def websocket_send_json_safe(websocket: WebSocket, payload: dict[str, Any]) -> None:
    try:
        await websocket.send_json(payload)
    except Exception:
        pass


@app.websocket("/asr/stream")
async def asr_stream(websocket: WebSocket):
    await websocket.accept()
    if not doubao_asr_configured():
        await websocket.send_json({
            "event": "error",
            "error": "豆包 ASR 未配置。请在 .env 添加 DOUBAO_ASR_API_KEY，或确认 DOUBAO_TTS_API_KEY 已开通 ASR。",
        })
        await websocket.close()
        return
    try:
        import websockets
    except Exception as exc:
        await websocket.send_json({"event": "error", "error": f"缺少 websockets 依赖：{exc}"})
        await websocket.close()
        return

    connect_id = str(uuid.uuid4())
    headers = {
        "X-Api-Resource-Id": DOUBAO_ASR_RESOURCE_ID,
        "X-Api-Key": DOUBAO_ASR_API_KEY,
        "X-Api-Connect-Id": connect_id,
    }
    if DOUBAO_ASR_APP_ID:
        headers["X-Api-App-Key"] = DOUBAO_ASR_APP_ID

    audio_format = "pcm"
    sample_rate = DOUBAO_ASR_SAMPLE_RATE
    seq = 1
    upstream = None
    upstream_closed = False

    try:
        try:
            upstream = await websockets.connect(
                DOUBAO_ASR_ENDPOINT,
                additional_headers=headers,
                max_size=8 * 1024 * 1024,
                ping_interval=15,
            )
        except TypeError:
            upstream = await websockets.connect(
                DOUBAO_ASR_ENDPOINT,
                extra_headers=headers,
                max_size=8 * 1024 * 1024,
                ping_interval=15,
            )

        init_payload = {
            "user": {"uid": f"melodio-{connect_id}"},
            "audio": {
                "format": audio_format,
                "codec": "raw",
                "rate": sample_rate,
                "bits": 16,
                "channel": 1,
                "language": DOUBAO_ASR_LANGUAGE,
            },
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": True,
                "enable_ddc": True,
                "result_type": "single",
                "show_utterances": True,
            },
        }
        await upstream.send(doubao_asr_full_request(seq, init_payload))
        await websocket.send_json({"event": "ready", "sample_rate": sample_rate})

        async def receive_from_doubao() -> None:
            nonlocal upstream_closed
            try:
                async for message in upstream:
                    if isinstance(message, str):
                        try:
                            data = json.loads(message)
                        except Exception:
                            data = {"event": "message", "text": message}
                    else:
                        data = doubao_asr_parse_frame(message)
                    public = {k: v for k, v in data.items() if k != "payload"}
                    await websocket_send_json_safe(websocket, public)
                    if data.get("event") == "error":
                        break
            except Exception as exc:
                if not upstream_closed:
                    await websocket_send_json_safe(websocket, {"event": "error", "error": f"豆包 ASR 连接中断：{exc}"})

        receiver = asyncio.create_task(receive_from_doubao())
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if "bytes" in message and message["bytes"] is not None:
                    seq += 1
                    await upstream.send(doubao_asr_audio_request(seq, message["bytes"], final=False))
                    continue
                if "text" in message and message["text"] is not None:
                    try:
                        data = json.loads(message["text"])
                    except Exception:
                        data = {}
                    if data.get("event") == "stop":
                        seq += 1
                        await upstream.send(doubao_asr_audio_request(seq, b"", final=True))
                        break
                    if data.get("event") == "config":
                        audio_format = str(data.get("format") or audio_format)
                        sample_rate = int(data.get("sample_rate") or sample_rate)
        except WebSocketDisconnect:
            pass
        finally:
            upstream_closed = True
            if upstream:
                try:
                    await upstream.close()
                except Exception:
                    pass
            receiver.cancel()
            try:
                await receiver
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
    except Exception as exc:
        logger.error("asr_stream_error error=%s\n%s", exc, traceback.format_exc())
        await websocket_send_json_safe(websocket, {"event": "error", "error": f"豆包 ASR 启动失败：{exc}"})
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@app.post("/asr/transcribe")
async def asr_transcribe(req: AsrReq) -> dict[str, Any]:
    started_at = time.time()
    try:
        audio_text = re.sub(r"^data:[^,]+,", "", req.audio_base64 or "").strip()
        if not audio_text:
            return {"ok": False, "error": "没有收到音频。", "text": ""}
        text = await transcribe_audio_with_gemini(audio_text, req.mime_type)
        logger.info("asr_transcribe_done mime=%s bytes_b64=%s elapsed=%.3f", req.mime_type, len(audio_text), time.time() - started_at)
        return {"ok": True, "text": text}
    except Exception as exc:
        logger.error("asr_transcribe_error elapsed=%.3f error=%s\n%s", time.time() - started_at, exc, traceback.format_exc())
        return {"ok": False, "error": f"语音识别失败：{exc}", "text": ""}


@app.get("/netease-auth-status")
async def netease_auth_status(title: str = "宝贝", artist: str = "张悬") -> dict[str, Any]:
    data = await run_in_threadpool(fetch_netease_stream, title, artist)
    return {
        "cookie_configured": bool(NETEASE_COOKIE),
        "title": title,
        "artist": artist,
        "stream_ok": bool(data.get("stream_url")),
        "matched_title": data.get("title"),
        "matched_artist": data.get("artist"),
        "error": data.get("error") or "",
        "fee": data.get("fee"),
        "provider": data.get("provider"),
    }


@app.post("/netease-login/qr")
async def netease_login_qr() -> dict[str, Any]:
    def create_qr():
        key_payload, _ = netease_api_service_json("/login/qr/key", {"type": 1})
        key_data = key_payload.get("data") if isinstance(key_payload.get("data"), dict) else {}
        key = str(key_data.get("unikey") or key_payload.get("unikey") or "")
        if not key:
            raise RuntimeError(f"获取网易云二维码 key 失败：{key_payload}")
        qr_payload, _ = netease_api_service_json("/login/qr/create", {"key": key, "qrimg": "true"})
        data = qr_payload.get("data") if isinstance(qr_payload.get("data"), dict) else {}
        return {
            "key": key,
            "qrimg": data.get("qrimg") or "",
            "qrurl": data.get("qrurl") or "",
        }

    try:
        return await run_in_threadpool(create_qr)
    except Exception as exc:
        return {"error": str(exc)}


@app.get("/netease-login/check")
async def netease_login_check(key: str) -> dict[str, Any]:
    def check():
        payload, cookies = netease_api_service_json("/login/qr/check", {"key": key, "noCookie": "true", "type": 1})
        code = int(payload.get("code") or 0)
        cookie = str(payload.get("cookie") or "").strip() or merge_set_cookie_values(cookies)
        if code == 803 and cookie:
            save_netease_cookie(cookie)
        return {
            "code": code,
            "message": payload.get("message") or payload.get("msg") or "",
            "cookie_saved": code == 803 and bool(cookie),
            "cookie_configured": bool(NETEASE_COOKIE),
        }

    try:
        return await run_in_threadpool(check)
    except Exception as exc:
        return {"code": 0, "error": str(exc), "cookie_configured": bool(NETEASE_COOKIE)}


@app.post("/netease-login/logout")
async def netease_login_logout() -> dict[str, Any]:
    global NETEASE_COOKIE
    NETEASE_COOKIE = ""
    NETEASE_COOKIE_FILE.unlink(missing_ok=True)
    return {"ok": True, "cookie_configured": False}


@app.post("/recommend/stream")
async def recommend_stream(req: RecommendReq):
    async def generate():
        query = req.query.strip()
        context = sanitize_context_payload(req.context)
        yield stream_event("start", {"query": query, "provider": req.provider})
        try:
            control_result = classify_context_control(query, context)
            if control_result:
                result = attach_pending_dj({"query": query, "provider": req.provider, **control_result})
            elif (context_artist_result := classify_context_artist_search(query, context, req.n)):
                result = attach_pending_dj({"query": query, "provider": req.provider, **context_artist_result})
            elif req.provider in PROVIDERS:
                skeleton = skeleton_payload(query, req.provider)
                if skeleton["analysis"].get("intent") in DIALOGUE_INTENTS or skeleton["analysis"].get("domain") == "chitchat":
                    result = await dialogue_payload_with_known_answer(query, req.provider, skeleton["analysis"], context)
                else:
                    data = await get_online_recommendations(query, req.n, req.provider, context)
                    result = attach_pending_dj({"query": query, "provider": req.provider, **data})
            else:
                context_result = classify_context_reference(query, context)
                if context_result:
                    result = attach_pending_dj({"query": query, "provider": req.provider, **context_result})
                else:
                    analysis, answer = classify(query)
                    if analysis.get("intent") in DIALOGUE_INTENTS or analysis.get("domain") == "chitchat":
                        result = await dialogue_payload_with_known_answer(query, req.provider, analysis, context)
                    elif analysis["intent"] not in SONG_INTENTS:
                        result = {
                            "query": query,
                            "provider": req.provider,
                            "analysis": analysis,
                            "answer": answer,
                            "entities": [],
                            "groups": [],
                        }
                    else:
                        result = {
                            "query": query,
                            "provider": req.provider,
                            "analysis": analysis,
                            "answer": answer,
                            "entities": [],
                            "groups": prioritize_playable_groups(
                                limit_recommendation_groups(
                                    build_groups(query, analysis, req.n),
                                    analysis,
                                    max_count=STREAM_PROBE_CANDIDATE_LIMIT,
                                ),
                                analysis,
                            ),
                        }
                    result = attach_pending_dj(result)
            for event in response_song_events(result):
                yield stream_event("song", event)
            yield stream_event("final", {"result": result})
        except Exception as exc:
            logger.error("recommend_stream_error provider=%s query=%r error=%s\n%s", req.provider, query, exc, traceback.format_exc())
            yield stream_event("error", {"error": safe_error_message(exc), "query": query, "provider": req.provider})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/recommend")
async def recommend(req: RecommendReq) -> dict[str, Any]:
    query = req.query.strip()
    context = sanitize_context_payload(req.context)
    control_result = classify_context_control(query, context)
    if control_result:
        return attach_pending_dj({"query": query, "provider": req.provider, **control_result})

    context_artist_result = classify_context_artist_search(query, context, req.n)
    if context_artist_result:
        return attach_pending_dj({"query": query, "provider": req.provider, **context_artist_result})

    if req.provider in PROVIDERS:
        skeleton = skeleton_payload(query, req.provider)
        if skeleton["analysis"].get("intent") in DIALOGUE_INTENTS or skeleton["analysis"].get("domain") == "chitchat":
            try:
                get_client(req.provider)
                return await dialogue_payload_with_known_answer(query, req.provider, skeleton["analysis"], context)
            except Exception as exc:
                logger.error("recommend_dialogue_error provider=%s query=%r error=%s\n%s", req.provider, query, exc, traceback.format_exc())
                return {"error": safe_error_message(exc), "query": query, "provider": req.provider}

    if req.provider in PROVIDERS:
        try:
            data = await get_online_recommendations(query, req.n, req.provider, context)
        except Exception as exc:
            logger.error("recommend_error provider=%s query=%r error=%s\n%s", req.provider, query, exc, traceback.format_exc())
            return {"error": safe_error_message(exc), "query": query, "provider": req.provider}
        return attach_pending_dj({"query": query, "provider": req.provider, **data})

    context_result = classify_context_reference(query, context)
    if context_result:
        return attach_pending_dj({"query": query, "provider": req.provider, **context_result})

    analysis, answer = classify(query)
    if analysis.get("intent") in DIALOGUE_INTENTS or analysis.get("domain") == "chitchat":
        return await dialogue_result_payload(query, req.provider, analysis, context)
    if analysis["intent"] not in {"entity_search", "general_reco", "filtered_reco", "similar_reco"}:
        result = {
            "query": query,
            "provider": req.provider,
            "analysis": analysis,
            "answer": answer,
            "entities": [],
            "groups": [],
        }
        return attach_pending_dj(result)
    result = clean_model_payload(
        {
            "analysis": analysis,
            "answer": answer,
            "entities": [],
            "groups": prioritize_playable_groups(
                limit_recommendation_groups(
                    build_groups(query, analysis, req.n),
                    analysis,
                    max_count=STREAM_PROBE_CANDIDATE_LIMIT,
                ),
                analysis,
            ),
        },
        query,
        prioritize_playable=False,
    )
    result = {
        "query": query,
        "provider": req.provider,
        **result,
    }
    return attach_pending_dj(result)


app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/tts-cache/{filename}")
async def tts_cache_file(filename: str) -> Any:
    safe_name = Path(filename).name
    path = TTS_CACHE_DIR / safe_name
    if not safe_name.endswith(".mp3") or not looks_like_audio_file(path):
        return JSONResponse({"error": "TTS audio not found"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")
