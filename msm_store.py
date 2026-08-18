import json
import time
from pathlib import Path

from msm_protocol import SFSLong

db_dir = None
players_dir = None

_db_cache = {}



_UNCACHED_DB_NAMES = {"gs_timed_events"}


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
    with path.open("r", encoding="utf-8-sig") as fh:
        data = json.load(fh)
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
    if not path.exists():
        raise FileNotFoundError(f"no player data for {username!r} at {path}")
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def save_user_data(username, root):
    path = _player_file(username)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(root, fh)
