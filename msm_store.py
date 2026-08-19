"""DB + player persistence with aggressive caching for high concurrency."""
import json
import time
from pathlib import Path
from threading import RLock

from msm_protocol import SFSLong

db_dir = None
players_dir = None

_db_cache = {}
_player_cache = {}  # username -> (mtime, data)
_player_lock = RLock()
_UNCACHED_DB_NAMES = {"gs_timed_events"}

# Optional faster JSON
try:
    import orjson

    def _loads(raw: bytes):
        return orjson.loads(raw)

    def _dumps(obj) -> bytes:
        return orjson.dumps(obj)
except ImportError:
    def _loads(raw: bytes):
        return json.loads(raw.decode("utf-8-sig") if isinstance(raw, (bytes, bytearray)) else raw)

    def _dumps(obj) -> bytes:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def load_db_json(name):
    if name in _db_cache:
        return _db_cache[name]
    if db_dir is None:
        raise RuntimeError("msm_store.db_dir not configured")
    path = Path(db_dir) / f"{name}.json"
    if not path.exists():
        if name in _UNCACHED_DB_NAMES:
            return None
        _db_cache[name] = None
        return None
    data = _loads(path.read_bytes())
    if name not in _UNCACHED_DB_NAMES:
        _db_cache[name] = data
    return data


def normalize_db_payload(command, payload):
    now_ms = SFSLong(int(time.time() * 1000))
    payload.setdefault("server_time", now_ms)
    payload.setdefault("last_updated", now_ms)
    if command.startswith("gs_"):
        payload.setdefault("success", True)
    return payload


def _player_file(username):
    if players_dir is None:
        raise RuntimeError("msm_store.players_dir not configured")
    return Path(players_dir) / f"{username}.json"


def load_user_data(username):
    path = _player_file(username)
    with _player_lock:
        if path.exists():
            mtime = path.stat().st_mtime
            cached = _player_cache.get(username)
            if cached and cached[0] == mtime:
                return cached[1]
            data = _loads(path.read_bytes())
            _player_cache[username] = (mtime, data)
            return data
        raise FileNotFoundError(f"no player data for {username!r} at {path}")


def save_user_data(username, root):
    path = _player_file(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _dumps(root)
    path.write_bytes(raw)
    with _player_lock:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = time.time()
        _player_cache[username] = (mtime, root)


def invalidate_player_cache(username=None):
    with _player_lock:
        if username is None:
            _player_cache.clear()
        else:
            _player_cache.pop(username, None)
