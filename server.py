import asyncio
import base64
import hashlib
import json
import logging
import os
import random
import re
import secrets
import struct
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qs
import uvicorn
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
import msm_protocol
import msm_store
import msm_handlers
import msm_playerdata

def same_name(path, name):
    return path.name.lower() == name.lower()

def locate_base():
    _c = os.environ.get('NPS_BASE_DIR')
    if _c:
        return Path(_c)
    _a = Path(__file__).resolve().parent
    _e = [_a, Path.cwd(), *_a.parents, *Path.cwd().parents]
    _f = set()
    for _d in _e:
        _b = str(_d).lower()
        if _b in _f:
            continue
        _f.add(_b)
        if (_d / 'Config.json').exists() or (_d / 'config.json').exists():
            return _d
    return _a

def locate_child(base, name, folder=False):
    _a = base / name
    if _a.exists():
        return _a
    for _b in base.iterdir():
        if same_name(_b, name) and (_b.is_dir() if folder else _b.is_file()):
            return _b
    return _a
BASE_DIR = locate_base()
CONFIG_PATH = locate_child(BASE_DIR, 'Config.json')
ACCOUNTS_PATH = locate_child(BASE_DIR, 'Accounts.json')
WHITELIST_PATH = locate_child(BASE_DIR, 'Whitelist.json')

def read_json(path, fallback):
    try:
        if path.exists() and path.stat().st_size:
            _a = json.loads(path.read_text(encoding='utf-8'))
            return _a if _a is not None else fallback
    except Exception:
        pass
    return fallback

def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')

def _clean_host(v: str) -> str:
    if not v:
        return ""
    v = str(v).strip()
    v = v.replace("https://", "").replace("http://", "").replace("wss://", "").replace("ws://", "")
    v = v.split("/")[0].strip()
    # drop accidental port for cloud hosts (Render/Railway public is always 443)
    if ":" in v:
        host_part, port_part = v.rsplit(":", 1)
        if port_part.isdigit() and host_part and not host_part.replace(".", "").isdigit():
            # keep non-standard ports only for pure IPs; for domains drop 80/443/8080
            if port_part in ("80", "443", "8080", "10000") or host_part.endswith((".onrender.com", ".up.railway.app", ".railway.app")):
                v = host_part
    return v.strip()


def lan_ip():
    """Best-effort public host for Render / Railway / local."""
    for key in (
        "PUBLIC_HOST",
        "RENDER_EXTERNAL_HOSTNAME",
        "RAILWAY_PUBLIC_DOMAIN",
        "RAILWAY_STATIC_URL",
        "RENDER_EXTERNAL_URL",
    ):
        v = _clean_host(os.environ.get(key) or "")
        if v and v not in ("127.0.0.1", "localhost", "0.0.0.0"):
            return v
    # Config.json override (SETTINGS may not exist at first import)
    try:
        cfg = SETTINGS  # type: ignore[name-defined]
    except NameError:
        cfg = {}
    cfg_host = _clean_host(str(cfg.get("public_host") or cfg.get("server_ip") or ""))
    if cfg_host and cfg_host not in ("auto", "127.0.0.1", "localhost", "0.0.0.0"):
        return cfg_host
    return "127.0.0.1"

def config():
    _b = read_json(CONFIG_PATH, {})
    _a = False
    _c = {
        'host': '0.0.0.0',
        'port': 9933,
        'http_ports': [9933],
        'server_ip': 'auto',
        'game_port': 9933,
        'server_id': 1,
        'max_players': 500,
        'files_folder': 'Files',
        'content_url': '',
        'force_empty_manifest': True,
        'cors_origins': ['*'],
        'cors_credentials': False,
        'token_ttl': 900,
        'auth_ttl': 1200,
        'login_ttl': 7200,
        'log_level': 'warning',
        'data_dir': 'Data',
        'players_dir': 'players',
        'server_name': 'MSM Private Server',
        'preload_db': True,
    }
    for _d, _e in _c.items():
        if _d not in _b:
            _b[_d] = _e
            _a = True
    if not _b.get('token_key'):
        _b['token_key'] = secrets.token_hex(8)
        _a = True
    if not _b.get('token_iv'):
        _b['token_iv'] = secrets.token_hex(8)
        _a = True
    if _b.get('server_ip') == 'auto':
        _b['resolved_server_ip'] = lan_ip()
    if _a:
        save_json(CONFIG_PATH, _b)
    return _b
SETTINGS = config()

# Railway / cloud: single port from $PORT (overrides config)
_env_port = os.environ.get("PORT") or os.environ.get("RAILWAY_PORT")
if _env_port:
    try:
        _p = int(_env_port)
        SETTINGS["port"] = _p
        SETTINGS["http_ports"] = [_p]
        SETTINGS["game_port"] = _p
    except ValueError:
        pass
# Ensure single port list
if not SETTINGS.get("http_ports"):
    SETTINGS["http_ports"] = [int(SETTINGS.get("port") or SETTINGS.get("game_port") or 9933)]
elif len(SETTINGS["http_ports"]) > 1 and _env_port:
    SETTINGS["http_ports"] = [int(_env_port)]

# Extra Railway / env overrides
if os.environ.get("MAX_PLAYERS"):
    try:
        SETTINGS["max_players"] = int(os.environ["MAX_PLAYERS"])
    except ValueError:
        pass
if os.environ.get("LOG_LEVEL"):
    SETTINGS["log_level"] = os.environ["LOG_LEVEL"].lower()
if os.environ.get("SERVER_ID"):
    try:
        SETTINGS["server_id"] = int(os.environ["SERVER_ID"])
    except ValueError:
        pass
if os.environ.get("SERVER_NAME"):
    SETTINGS["server_name"] = os.environ["SERVER_NAME"]
# Always prefer cloud public hostname when present
_pub = lan_ip()
if _pub and _pub not in ("127.0.0.1", "localhost", "0.0.0.0"):
    SETTINGS["server_ip"] = _pub
    SETTINGS["resolved_server_ip"] = _pub
elif os.environ.get("PUBLIC_HOST"):
    SETTINGS["server_ip"] = os.environ["PUBLIC_HOST"]
    SETTINGS["resolved_server_ip"] = os.environ["PUBLIC_HOST"]

FILES_DIR = locate_child(BASE_DIR, str(SETTINGS.get('files_folder') or 'Files'), True)
FILES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR = locate_child(BASE_DIR, str(SETTINGS.get('data_dir') or 'Data'), True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
PLAYERS_DIR = locate_child(BASE_DIR, str(SETTINGS.get('players_dir') or 'players'), True)
PLAYERS_DIR.mkdir(parents=True, exist_ok=True)
# Backwards compatible aliases
SFS_DB_DIR = DATA_DIR
SFS_PLAYERS_DIR = PLAYERS_DIR
msm_store.db_dir = DATA_DIR
msm_store.players_dir = PLAYERS_DIR
if not ACCOUNTS_PATH.exists():
    save_json(ACCOUNTS_PATH, [])
if not WHITELIST_PATH.exists():
    save_json(WHITELIST_PATH, [])
logging.basicConfig(level=getattr(logging, str(SETTINGS.get('log_level', 'info')).upper(), logging.INFO), format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger('msm.bridge')
app = FastAPI(title='LiveMSM Bridge', version='0.4.0')

# Active websocket connections (for max_players limit)
_active_connections = 0
_active_lock = None
try:
    import threading
    _active_lock = threading.Lock()
except Exception:
    pass

_UVICORN_SERVERS = []
_SHUTDOWN_REQUESTED = False

class _SuppressShutdownCancelledError(logging.Filter):
    def filter(self, record):
        if _SHUTDOWN_REQUESTED and record.exc_info and record.exc_info[0] is asyncio.CancelledError:
            return False
        return True

logging.getLogger('uvicorn.error').addFilter(_SuppressShutdownCancelledError())
logging.getLogger('asyncio').addFilter(_SuppressShutdownCancelledError())

def request_shutdown():
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = True
    for server in list(_UVICORN_SERVERS):
        try:
            server.should_exit = True
        except Exception:
            pass
    return True

async def _force_exit_watchdog(delay=5.0):
    await asyncio.sleep(delay)
    if not _SHUTDOWN_REQUESTED:
        return
    for server in list(_UVICORN_SERVERS):
        try:
            server.force_exit = True
        except Exception:
            pass
app.add_middleware(CORSMiddleware, allow_origins=list(SETTINGS.get('cors_origins') or ['*']), allow_credentials=bool(SETTINGS.get('cors_credentials', False)), allow_methods=['*'], allow_headers=['*'])
DEFAULT_ACCOUNT = {'username': 'Next Private Server', 'email': 'Nextstars@gmail.com', 'password': 'PrivateServerStudios', 'user_id': '00000001AB', 'user_game_id': 'NextPrivateServer', 'steam_id': '76561198000000001'}
PUBLIC_CONTENT_PREFIX = '/MSM/GameAssets/'
ZONE_NAME = 'MySingingMonsters'
BLUEBOX_HTTP_PORT = 8282
BLUEBOX_HTTPS_PORT = 8543
ACCESS_TOKEN_FALLBACK = 'local-private-server-token'
ERROR_MESSAGES = ['Username does not exist - re-register', 'Username does not exist', 'Invalid password', 'Invalid account type', 'Required argument missing', 'Login failed', 'Usernames do not match', 'Passwords do not match', 'The username is already in use', 'The email address is invalid', 'The email address has not been verified', 'Could not find the game server id based on the hostname provided', 'Email address not found', 'Connection error', 'Exceeded Maximum Accounts. Too Many Accounts Created.', 'Login info is already bound to another account', 'A login of this type is already bound to this account', 'Facebook failed to validate user on the server', 'These users are already friends.', 'No account found for that friend code.', 'An error has occured', 'The min client version is too low to play this game.', 'The email address you provided probably has a typo and cannot receive mail. Please contact support to resolve this issue.', 'Your device has been banned from sending emails. Please contact support to resolve this issue.', 'Accounts contain same game id.', 'Google Play authorization failed.', 'Amazon authorization failed.', 'Account has no data for this game.', 'No token was present when required', 'Invalid permissions', 'Expected client token, server token used', 'Expected server token, client token used', 'Game center authorization failed.', 'Global Achievement reward not found.', 'Too many accounts have been created from your IP address.', 'Game config not found for: ', 'GDPR consent required', 'Token Expired', 'Apple authorization failed.', 'Refresh Token authorization failed.', 'Credentials are expired.', 'Steam authorization failed.', 'Selected account type disabled.']

class AuthCode:
    MISSING_DATA = 4
    LOGIN_FAILED = 5
    SERVER_MESSAGE = 14
    GENERAL_ERROR = 20

def message_for(error_id):
    _a = 0 if error_id == -1 else error_id
    if 0 <= _a < len(ERROR_MESSAGES):
        return ERROR_MESSAGES[_a]
    return ERROR_MESSAGES[AuthCode.GENERAL_ERROR]

def error(error_id):
    return {'ok': False, 'error': error_id, 'message': message_for(error_id)}

def ok(data=None):
    _a = {'ok': True}
    if data:
        _a.update(data)
    return _a

def md5(value):
    return hashlib.md5(str(value).encode('utf-8')).hexdigest()

def aes_encrypt(value):
    _c = str(SETTINGS['token_key']).encode('utf-8')
    _b = str(SETTINGS['token_iv']).encode('utf-8')
    _a = AES.new(_c, AES.MODE_CBC, _b)
    return base64.b64encode(_a.encrypt(pad(value.encode('utf-8'), AES.block_size))).decode('utf-8')

def aes_decrypt(value):
    _c = str(SETTINGS['token_key']).encode('utf-8')
    _b = str(SETTINGS['token_iv']).encode('utf-8')
    _a = AES.new(_c, AES.MODE_CBC, _b)
    return unpad(_a.decrypt(base64.b64decode(value)), AES.block_size).decode('utf-8')

def load_accounts():
    _a = read_json(ACCOUNTS_PATH, [])
    return _a if isinstance(_a, list) else []

def forced_account():
    _b = load_accounts()
    _a = dict(_b[0]) if _b else {}
    _c = dict(DEFAULT_ACCOUNT)
    _c.update({key: value for key, value in _a.items() if value not in (None, '')})
    return _c

def load_whitelist():
    _a = read_json(WHITELIST_PATH, [])
    return set((str(item).strip() for item in _a if str(item).strip())) if isinstance(_a, list) else set()

def account_id(value, fallback=None):
    if fallback is None:
        fallback = random.randint(1000000, 2147483647)
    _a = str(value or '').strip()
    if not _a:
        return fallback
    try:
        if _a.lower().startswith('0x') or _a.startswith('0000'):
            return int(_a, 16)
        return int(_a)
    except Exception:
        return fallback

def password_ok(account, password):
    if not password:
        return False
    if account.get('password') == password:
        return True
    if account.get('password_sha256') == hashlib.sha256(password.encode('utf-8')).hexdigest():
        return True
    return False

def find_account(username, password):
    if not username or not password:
        return None
    for _a in load_accounts():
        if str(_a.get('username', '')) == str(username) and password_ok(_a, password):
            return _a
    return None

def token(username, user_game_id, login_type, account_id_value, game_id, ttl=None):
    _a = round(time.time())
    _b = {'account_id': account_id_value, 'user_game_id': user_game_id, 'game': game_id, 'token_version': 1, 'time_created': _a, 'expires_at': _a + int(ttl or SETTINGS.get('token_ttl', 900)), 'username': str(username).strip(), 'login_type': login_type}
    return aes_encrypt(json.dumps(_b, separators=(',', ':')))

def client_ip(request):
    _a = request.headers.get('x-forwarded-for')
    if _a:
        return _a.split(',', 1)[0].strip()
    return request.client.host if request.client else ''

def normalize_request_path(path):
    if not path:
        return '/'
    _a = re.sub('/+', '/', str(path))
    return _a or '/'

def apply_normalized_path(request):
    _b = request.scope.get('path') or '/'
    _a = normalize_request_path(_b)
    if _a != _b:
        request.scope['path'] = _a
        request.scope['raw_path'] = _a.encode('ascii', 'ignore')
    return (_b, _a)

@app.middleware('http')
async def gate(request, call_next):
    _e, _d = apply_normalized_path(request)
    _a = load_whitelist()
    _c = client_ip(request)
    if _a and _c not in _a:
        return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
    _h = await call_next(request)
    _f = str(request.url.query or '')
    _i = request.headers.get('user-agent', '')
    _g = request.headers.get('referer', '')
    _b = 'yes' if request.headers.get('authorization') else 'no'
    if _e != _d:
        logger.info('%s %s -> %s %s ip=%s auth=%s ua=%r referer=%r query=%r', request.method, _e, _d, _h.status_code, _c, _b, _i, _g, _f)
    else:
        logger.info('%s %s %s ip=%s auth=%s ua=%r referer=%r query=%r', request.method, _d, _h.status_code, _c, _b, _i, _g, _f)
    return _h

async def params(request):
    _a = dict(request.query_params)
    try:
        _b = await request.form()
        _a.update(dict(_b))
    except Exception:
        pass
    if not _a:
        try:
            _d = (await request.body()).decode('utf-8', 'ignore')
            if _d:
                if _d.lstrip().startswith('{'):
                    _a.update(json.loads(_d))
                else:
                    for _c, _e in parse_qs(_d, keep_blank_values=True).items():
                        _a[_c] = _e[-1]
        except Exception:
            pass
    return _a

def server_ip():
    # Prefer live env (Render/Railway) every request so PUBLIC_HOST works without restart races
    live = lan_ip()
    if live and live not in ("127.0.0.1", "localhost", "0.0.0.0"):
        SETTINGS["resolved_server_ip"] = live
        return live
    return str(SETTINGS.get("resolved_server_ip") or SETTINGS.get("server_ip") or "127.0.0.1")

def content_port():
    _b = SETTINGS.get('content_port')
    if _b:
        return int(_b)
    _a = SETTINGS.get('http_ports') or [80]
    return int(_a[0])

def is_public_host(host: str) -> bool:
    h = (host or "").lower().strip()
    if not h or h in ("127.0.0.1", "localhost", "0.0.0.0"):
        return False
    if h.endswith(".onrender.com") or h.endswith(".up.railway.app") or h.endswith(".railway.app"):
        return True
    if "." in h and not h.replace(".", "").isdigit():
        return True
    return False


def public_base_url():
    """HTTPS base for cloud (Render/Railway) or http://host:port locally."""
    if SETTINGS.get("content_url"):
        base = str(SETTINGS["content_url"]).rstrip("/")
        # strip path suffixes if any
        for suf in (PUBLIC_CONTENT_PREFIX.rstrip("/"), "/MSM/GameAssets"):
            if base.endswith(suf):
                base = base[: -len(suf)].rstrip("/")
        return base
    host = server_ip()
    if is_public_host(host):
        return f"https://{host}"
    port = content_port()
    suffix = "" if port in (80, 443) else f":{port}"
    return f"http://{host}{suffix}"


def content_root():
    if SETTINGS.get("content_url"):
        return str(SETTINGS["content_url"]).rstrip("/")
    return f"{public_base_url()}{PUBLIC_CONTENT_PREFIX}"


def sfs_block():
    host = server_ip()
    game_port = int(SETTINGS.get("game_port", 9933))
    public = is_public_host(host)
    path_bb = "/BlueBox/BlueBox.do"
    path_ws = "/msm/socket"

    if public:
        # Cloud: single HTTPS port (443), WSS for websockets
        http_port = 443
        https_port = 443
        ws_url = f"wss://{host}{path_ws}"
        http_url = f"https://{host}{path_bb}"
        https_url = http_url
        server_ip_str = f"https|websocket|{host}|443"
        secure = True
    else:
        http_port = BLUEBOX_HTTP_PORT
        https_port = BLUEBOX_HTTPS_PORT
        ws_url = f"ws://{host}:{http_port}{path_ws}"
        http_url = f"http://{host}:{http_port}{path_bb}"
        https_url = f"https://{host}:{https_port}{path_bb}"
        server_ip_str = f"http|websocket|{host}|{http_port}"
        secure = False

    return {
        "host": host, "ip": host, "address": host, "hostname": host, "serverAddress": host,
        "serverId": int(SETTINGS.get("server_id", 1)), "server_id": int(SETTINGS.get("server_id", 1)),
        "serverIp": server_ip_str, "serverIP": server_ip_str, "server_ip": server_ip_str,
        "serverHost": host, "server_host": host,
        "port": game_port, "serverPort": game_port, "server_port": game_port,
        "socketPort": game_port, "socket_port": game_port, "tcpPort": game_port, "tcp_port": game_port, "tcpPortNumber": game_port,
        "sfsHost": host, "sfs_host": host, "sfsIp": host, "sfsIP": host, "sfs_ip": host,
        "sfsPort": game_port, "sfs_port": game_port, "tcp_host": host,
        "zone": ZONE_NAME, "zoneName": ZONE_NAME, "zone_name": ZONE_NAME, "sfs_zone": ZONE_NAME,
        "protocol": "websocket", "transport": "websocket", "connection": "websocket",
        "connectionType": "websocket", "connection_type": "websocket",
        "socket": True, "use_socket": True, "useSocket": True,
        "secure": secure, "ssl": secure, "tls": secure, "use_ssl": secure, "use_tls": secure, "useSSL": secure, "useTLS": secure,
        "websocket": True, "webSocket": True, "use_websocket": True, "useWebSocket": True,
        "websocketHost": host, "websocket_host": host, "webSocketHost": host, "wsHost": host, "ws_host": host,
        "websocketPort": http_port, "websocket_port": http_port, "webSocketPort": http_port, "wsPort": http_port, "ws_port": http_port,
        "websocketPath": path_ws, "websocket_path": path_ws,
        "websocketUrl": ws_url, "websocket_url": ws_url, "webSocketUrl": ws_url, "wsUrl": ws_url, "ws_url": ws_url,
        "bluebox": False, "blueBox": False, "use_bluebox": False, "useBlueBox": False,
        "blueboxHost": host, "bluebox_host": host, "blueBoxHost": host, "blueBoxIpAddress": host,
        "blueboxPort": http_port, "bluebox_port": http_port, "blueBoxPort": http_port,
        "httpPort": http_port, "http_port": http_port, "httpsPort": https_port, "https_port": https_port,
        "blueboxUrl": http_url, "bluebox_url": http_url, "blueBoxUrl": http_url,
        "blueboxSslUrl": https_url, "bluebox_ssl_url": https_url, "blueBoxSslUrl": https_url,
    }

def account_entry(account):
    return {'type': 'email', 'username': account['username'], 'userName': account['username'], 'email': account['email'], 'can_bind_to': True, 'can_create': True, 'auto_create': False}

def existing_accounts_payload(account):
    return {'ok': True, 'success': True, 'status': 'ok', 'found': True, 'existing_account': True, 'account_exists': True, 'create_account': False, 'connectionError': False, 'can_create': True, 'auto_create': False, 'can_bind_to': ['email'], 'isAvailable': True, 'existing_accounts': [account_entry(account)], 'accounts': [{'username': account['username'], 'userName': account['username'], 'email': account['email'], 'type': 'email', 'portrait': 'email', 'email_name': account['email']}], 'login_types': ['email']}

def game_config_block():
    _c = sfs_block()
    _b = content_root()
    _a = [{'type': 'email', 'login_type': 'email', 'auth_type': 'email', 'auto_create': False, 'can_bind_to': True, 'can_create': True, 'enabled': True}]
    return {'login_types': _a, 'loginConfigs': _a, 'login_configs': _a, 'type': 'android', 'platform': 'android', 'store': 'android', 'package': 'com.bigbluebubble.singingmonsters.full', 'game_version': '5.4.2', 'client_version': '5.4.2', 'assets_version': '494', 'build': '494', 'contentUrl': _b, 'content_url': _b, 'update_url': _b, 'download_url': _b, 'precheck': True, 'precheck_required': True, 'precheck_db': 'db_precheck', 'precheckDb': 'db_precheck', 'precheck_databases': ['db_precheck'], 'precheckDatabases': ['db_precheck'], 'startup_databases': ['db_precheck'], 'startupDatabases': ['db_precheck'], 'server': _c, 'sfs': _c, 'game_server': _c, 'gameServer': _c, 'smartfox': _c, 'smartFox': _c, 'connection': _c, 'connectionInfo': _c, 'connection_info': _c, 'socket': _c, 'socketServer': _c, 'socket_server': _c, 'servers': [_c], 'server_list': [_c], 'serverList': [_c], 'sfs_servers': [_c], 'sfsServers': [_c], **_c}

def auth_payload(account, access_token):
    _d = str(account.get('user_id', DEFAULT_ACCOUNT['user_id']))
    _c = account.get('user_game_id') or account['username']
    _a = game_config_block()
    _b = existing_accounts_payload(account)
    return {'ok': True, 'success': True, 'status': 'ok', 'result': 'ok', 'verified': True, 'allow': True, 'connectionError': False, 'access_token': access_token, 'accessToken': access_token, 'has_token': True, 'token_type': 'bearer', 'token': access_token, 'sessId': 'local-private-server-session', 'session_id': 'local-private-server-session', 'account_id': _d, 'userId': _d, 'user_id': _d, 'bbbId': _d, 'bbbID': _d, 'bbbid': _d, 'username': account['username'], 'userName': account['username'], 'email': account['email'], 'userEmail': account['email'], 'email_name': account['email'], 'type': 'email', 'login_type': 'email', 'auth_type': 'email', 'authType': 'email', 'loginMethod': 'email', 'platform': 'android', 'platform_type': 'android', 'anon': False, 'guest': False, 'found': True, 'registered': True, 'existing_account': True, 'account_exists': True, 'create_account': False, 'needs_registration': False, 'needs_password_reset': False, 'auth_types': ['email'], 'userGameId': _c, 'user_game_id': _c, 'existing_accounts': _b['existing_accounts'], 'accounts': _b['accounts'], 'login_types': _a['login_types'], 'loginConfigs': _a['loginConfigs'], 'login_configs': _a['login_configs'], 'config': _a, 'game_config': _a, 'gameConfig': _a, **_a}

def token_payload(account, access_token):
    _b = str(account.get('user_id', DEFAULT_ACCOUNT['user_id']))
    _a = account.get('user_game_id') or account['username']
    return {'ok': True, 'success': True, 'status': 'ok', 'result': 'ok', 'access_token': access_token, 'accessToken': access_token, 'has_token': True, 'connectionError': False, 'token_type': 'bearer', 'token': access_token, 'sessId': 'local-private-server-session', 'bbbId': _b, 'bbbID': _b, 'bbbid': _b, 'userId': _b, 'user_id': _b, 'userName': account['username'], 'username': account['username'], 'email': account['email'], 'userEmail': account['email'], 'type': 'email', 'login_type': 'email', 'auth_type': 'email', 'authType': 'email', 'loginMethod': 'email', 'platform': 'android', 'platform_type': 'android', 'anon': False, 'guest': False, 'found': True, 'registered': True, 'existing_account': True, 'account_exists': True, 'create_account': False, 'needs_registration': False, 'needs_password_reset': False, 'auth_types': ['email'], 'userGameId': _a, 'user_game_id': [_a], 'email_name': account['email'], 'login_types': ['email'], 'existing_accounts': [account_entry(account)]}

@app.api_route('/', methods=['GET', 'POST'])
async def index():
    host = server_ip()
    public = is_public_host(host)
    return ok({
        "status": "running",
        "server_name": SETTINGS.get("server_name"),
        "public_host": host,
        "public": public,
        "base_url": public_base_url(),
        "content_url": content_root(),
        "websocket_url": f"{'wss' if public else 'ws'}://{host}{'/msm/socket' if public else ':' + str(BLUEBOX_HTTP_PORT) + '/msm/socket'}",
        "auth_php": f"{public_base_url()}/auth.php",
        "max_players": SETTINGS.get("max_players"),
        "hint": "Set PUBLIC_HOST or RENDER_EXTERNAL_HOSTNAME to your Render/Railway domain",
    })


@app.api_route('/status', methods=['GET', 'POST'])
async def status_endpoint():
    return await index()

async def legacy_auth_php(request: Request):
    try:
        _a = forced_account()
        _g = str(_a.get('legacy_bbb_id') or _a.get('bbbId') or _a.get('user_id') or '1')
        if _g.lower().startswith('0x') or any((ch.isalpha() for ch in _g)):
            _g = str(account_id(_g, 1))
        _h = str(_a.get('username') or 'Nextstars')
        _d = str(_a.get('password') or 'PrivateServerStudios')
        _f = str(_a.get('user_game_id') or _h)
        _host = server_ip()
        _public = is_public_host(_host)
        _sfs = sfs_block()
        _b = {
            'ok': True,
            'bbbId': _g,
            'sessId': 'local-private-server-session',
            'username': _h,
            'password': _d,
            'friends': [],
            'serverIp': _host,
            'server_ip': _host,
            'serverIP': _host,
            'serverAddress': _host,
            'host': _host,
            'contentUrl': str(content_root()),
            'content_url': str(content_root()),
            'websocketUrl': _sfs.get('websocketUrl'),
            'websocket_url': _sfs.get('websocketUrl'),
            'blueboxUrl': _sfs.get('blueboxUrl'),
            'secure': _public,
            'sync': [],
            'rs_verify': '',
        }
        logger.info('legacy auth.php response %s', _b)
        _e = JSONResponse(_b)
        _e.headers['content-type'] = 'application/json; charset=utf-8'
        return _e
    except Exception as _c:
        logger.exception('legacy auth.php failed: %s', _c)
        return JSONResponse({'ok': False, 'error': 5, 'message': 'Login Failed'}, status_code=500)

async def purchase_order(request: Request):
    return ok({'processed_order': False})

async def purchase_dlc(request: Request):
    return ok({'processed_dlc': False})

async def auth_handler(request: Request):
    try:
        _d = await params(request)
        logger.info('auth_handler path=%s params=%s', request.scope.get('path'), sorted(_d.keys()))
        _g = _d.get('g') or '27'
        try:
            _h = json.loads(_d.get('l') or '[]')
        except Exception:
            _h = []
        _e = _h[0] if _h else {}
        _i = _e.get('t', 'steam')
        _o = _d.get('username') or _d.get('u')
        _k = _d.get('password') or _d.get('p')
        _b = find_account(_o, _k) or forced_account()
        _n = account_id(_b.get('user_id'), 1)
        _m = _b.get('user_game_id') or _b.get('username', 'Nextstars')
        _a = ACCESS_TOKEN_FALLBACK
        _j = round(time.time())
        _c = token_payload(_b, _a)
        _c.update({'time_created': _j, 'expires_at': _j + int(SETTINGS.get('auth_ttl', 1200)), 'device_updated': True})
        _l = JSONResponse(_c)
        _l.headers['authorization'] = f'Bearer {_a}'
        _l.headers['content-type'] = 'application/json; charset=utf-8'
        return _l
    except Exception as _f:
        logger.exception('auth failed: %s', _f)
        return error(AuthCode.GENERAL_ERROR)

async def login_handler(request: Request):
    try:
        _d = await params(request)
        logger.info('login_handler path=%s params=%s', request.scope.get('path'), sorted(_d.keys()))
        _l = str(_d.get('username', '')).strip()
        _h = str(_d.get('password', '')).strip()
        _b = find_account(_l, _h) or forced_account()
        _k = account_id(_b.get('user_id'), 1)
        _j = _b.get('user_game_id') or _b.get('username', 'Nextstars')
        _f = _d.get('g', '27')
        _a = ACCESS_TOKEN_FALLBACK
        _g = round(time.time())
        _c = token_payload(_b, _a)
        _c.update({'time_created': _g, 'expires_at': _g + int(SETTINGS.get('login_ttl', 7200)), 'device_updated': True})
        _i = JSONResponse(_c)
        _i.headers['authorization'] = f'Bearer {_a}'
        _i.headers['content-type'] = 'application/json; charset=utf-8'
        return _i
    except Exception as _e:
        logger.exception('login failed: %s', _e)
        return error(AuthCode.GENERAL_ERROR)

def dof_accounts_json(account, requested_logins=None):
    _e = str(account.get('user_id', DEFAULT_ACCOUNT['user_id']))
    _d = account.get('user_game_id') or account.get('username', 'Nextstars')
    _b = []
    for _c in requested_logins or []:
        _b.append({'username': _c.get('u') or account['username'], 'password': _c.get('p') or account['password'], 'login_type': _c.get('t') or 'email'})
    if not _b:
        _b.append({'username': account['username'], 'password': account['password'], 'login_type': 'email'})
    _a = [{'account_id': _e, 'logins': _b, 'user_game_ids': [_d]}]
    return json.dumps(_a)

async def existing_accounts(request: Request):
    _c = await params(request)
    try:
        _d = json.loads(_c.get('l') or '[]')
    except Exception:
        _d = []
    logger.info('existing_accounts params=%s requested_logins=%s', dict(_c), _d)
    _a = forced_account()
    _b = existing_accounts_payload(_a)
    _b['accounts'] = dof_accounts_json(_a, _d)
    return _b

async def find_account_handler(request: Request):
    _b = await params(request)
    logger.info('find_account path=%s params=%s', request.scope.get('path'), sorted(_b.keys()))
    _a = forced_account()
    _c = existing_accounts_payload(_a)
    _c.update(auth_payload(_a, ACCESS_TOKEN_FALLBACK))
    _c.update({'found': True, 'registered': True, 'account_exists': True, 'existing_account': True, 'create_account': False})
    return JSONResponse(_c)

async def waf_handler(request: Request):
    _a = await request.body()
    logger.info('waf path=%s method=%s query=%s body=%r', request.scope.get('path'), request.method, str(request.url.query), _a[:500])
    return JSONResponse({
        'ok': True,
        'success': True,
        'status': 'ok',
        'challenge': {'type': 'none', 'required': False},
        'challengeRequired': False,
        'captcha': False,
        'token': ACCESS_TOKEN_FALLBACK,
        'aws-waf-token': ACCESS_TOKEN_FALLBACK,
        'wafToken': ACCESS_TOKEN_FALLBACK,
    })

async def game_config(request: Request):
    _b = await params(request)
    logger.info('game_config path=%s params=%s', request.scope.get('path'), sorted(_b.keys()))
    _a = forced_account()
    return auth_payload(_a, ACCESS_TOKEN_FALLBACK)

@app.api_route('/pregame_setup.php', methods=['GET', 'POST'])
async def pregame_setup(request: Request):
    _c = await params(request)
    logger.info('pregame_setup params=%s', sorted(_c.keys()))
    _d = content_root()
    _a = forced_account()
    _b = auth_payload(_a, ACCESS_TOKEN_FALLBACK)
    _b.update({'contentUrl': _d, 'content_url': _d, 'update_url': _d, 'download_url': _d, 'contentServer': _d, 'force_update': False, 'maintenance': False, 'min_version': '1.0.0'})
    return _b

def _download_manifest_path():
    return FILES_DIR / 'downloads.xml'


def _download_entries():
    path = _download_manifest_path()
    if not path.is_file():
        return []
    try:
        root = ET.parse(path).getroot()
    except Exception:
        logger.exception('failed to parse bundled downloads.xml')
        return []
    entries = []
    for node in root.findall('.//Download'):
        file_name = (node.get('file') or '').replace('\\', '/').lstrip('/')
        if not file_name:
            continue
        local_path = (FILES_DIR / file_name).resolve()
        try:
            local_path.relative_to(FILES_DIR.resolve())
        except Exception:
            continue
        if not local_path.is_file():
            logger.warning('downloads.xml announces missing asset: %s', file_name)
            continue
        checksum = hashlib.md5(local_path.read_bytes()).hexdigest()
        entries.append({
            'localName': file_name,
            'serverName': file_name,
            'checksum': checksum,
        })
    return entries


def _build_downloads_xml(entries):
    lines = ['<?xml version="1.0"?>', '<Downloads version="5.4.2" build="494">']
    for entry in entries:
        name = (
            str(entry.get('serverName') or '')
            .replace('&', '&amp;')
            .replace('"', '&quot;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
        )
        if not name:
            continue
        lines.append(f'    <Download file="{name}" checksum="{entry["checksum"]}" major="5" minor="4" micro="2" rev="0" />')
    lines.append('</Downloads>')
    return '\n'.join(lines).encode('utf-8')


def manifest():
    return _download_entries()

async def files_manifest(request: Request):
    _a = await params(request)
    entries = manifest()
    logger.info('files_manifest path=%s params=%s entries=%d', request.scope.get('path'), sorted(_a.keys()), len(entries))
    raw = json.dumps(entries, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return Response(raw, media_type='application/json')

async def downloads_xml(request: Request):
    entries = manifest()
    logger.info('downloads_xml path=%s entries=%d', request.scope.get('path'), len(entries))
    return Response(_build_downloads_xml(entries), media_type='application/xml')

async def serve_file(path: str):
    _a = (FILES_DIR / path).resolve()
    try:
        _a.relative_to(FILES_DIR.resolve())
    except Exception:
        return JSONResponse({'ok': False, 'error': 'bad path'}, status_code=400)
    if not _a.is_file():
        return JSONResponse({'ok': False, 'error': 'not found'}, status_code=404)
    return FileResponse(_a)

async def db_gs_player(request: Request):
    return ok({'players': []})

async def db_db_island(request: Request):
    return ok({'islands': []})

async def db_db_monster(request: Request):
    return ok({'monsters': []})
LOGIN_SUCCESS_PATH = locate_child(BASE_DIR, 'login_success_response.json')
_login_success_cache = None

def login_success_response():
    global _login_success_cache
    if _login_success_cache is None:
        _login_success_cache = json.loads(LOGIN_SUCCESS_PATH.read_text(encoding='utf-8'))
    _b = round(time.time() * 1000)
    _c = json.loads(json.dumps(_login_success_cache))
    for _a in _c:
        if _a.get('type') == 104:
            _a['clock'] = _b
        if _a.get('type') == 16:
            _a['date_created'] = _b
    return _c

async def msm2auth(request: Request):
    _a = await params(request)
    _d = _a.get('data') or '{}'
    try:
        _c = json.loads(_d)
    except Exception:
        _c = {}
    logger.info('msm2auth request payload=%s', _c)
    _e = _c.get('request', 8)
    _b = round(time.time() * 1000)
    if _e == 10:
        _f = login_success_response()
    else:
        _f = [{'type': 104, 'clock': _b}, {'type': 1002, 'address': content_root(), 'version': 18345, 'minVersion': 18343}]
    logger.info('msm2auth response type=%s size=%d', _e, len(json.dumps(_f)))
    return JSONResponse(_f)
PLAYER_SYNC_PATH = locate_child(BASE_DIR, 'player_sync_response.json')
LIVE_STATE_PATH = locate_child(BASE_DIR, 'player_state_live.json')
_player_sync_cache = None
_live_state = None

def player_sync_response():
    global _player_sync_cache
    if _player_sync_cache is None:
        _player_sync_cache = json.loads(PLAYER_SYNC_PATH.read_text(encoding='utf-8'))
    return json.loads(json.dumps(_player_sync_cache))

def load_live_state():
    global _live_state
    if _live_state is None:
        if LIVE_STATE_PATH.exists():
            _live_state = json.loads(LIVE_STATE_PATH.read_text(encoding='utf-8'))
        else:
            _live_state = player_sync_response()
    return _live_state

def save_live_state():
    LIVE_STATE_PATH.write_text(json.dumps(_live_state), encoding='utf-8')

def reset_live_state():
    global _live_state
    _live_state = None

async def msm2rh(request: Request):
    _g = await params(request)
    _j = _g.get('data') or '[]'
    logger.info('msm2rh request raw=%s', _j)
    _k = None
    _h = []
    try:
        _h = json.loads(_j)
        if _h and isinstance(_h, list):
            _k = _h[0].get('request')
    except Exception:
        pass
    if _k == 'playerSync':
        _n = load_live_state()
        _l = json.loads(json.dumps(_n))
    elif _k == 'submitCommand':
        _o = []
        try:
            _o = _h[0].get('data', {}).get('commands', [])
        except Exception:
            pass
        _n = load_live_state()
        _c = False
        _f = []
        for _d in _o:
            _e = _d.get('command')
            logger.info('submitCommand code=%s payload=%s', _e, _d)
            if _e == 1503:
                _b = _d.get('entity')
                if _b is not None:
                    _i = int(time.time() * 1000)
                    _m = _n[0]['state']['spinners']
                    _a = {'rng': {'s1': random.randint(1, 2 ** 31 - 1), 's2': 0, 's3': 0, 's4': 0}, 'position': 0, 'lastCollected': 0, 'activeBoard': _b, 'expiry': _i + 30 * 24 * 3600 * 1000}
                    _m['data'] = [_a]
                    _c = True
                    _f.append({'command': 1134, 'when': _i, 'bonusBoard': _a})
            else:
                logger.info('submitCommand code=%s has no captured real response; answering with no commands', _e)
        if _c:
            save_live_state()
        _l = [{'type': 101, 'commands': {'commands': _f}}]
    else:
        logger.info('msm2rh request_kind=%s has no captured real response; answering with no commands', _k)
        _l = [{'type': 101, 'commands': {'commands': []}}]
    logger.info('msm2rh request_kind=%s response_size=%d', _k, len(json.dumps(_l)))
    return JSONResponse(_l)

async def catch_all(path: str, request: Request):
    _a = await request.body()
    logger.info('catch_all path=%s method=%s query=%s body=%r', path, request.method, str(request.url.query), _a[:2000])
    return {'ok': False, 'error': 'not implemented', 'path': path}

async def bluebox(request: Request):
    logger.info('bluebox probe path=%s method=%s', request.scope.get('path'), request.method)
    return Response('<msg t="sys"><body action="apiOK" r="0"><ver v="2.13.0"/></body></msg>\x00', media_type='text/xml')

async def sfs_websocket(websocket: WebSocket):
    global _active_connections
    max_players = int(SETTINGS.get('max_players') or 0)
    # Check limit before accepting
    if max_players > 0:
        if _active_lock:
            with _active_lock:
                current = _active_connections
        else:
            current = _active_connections
        if current >= max_players:
            logger.warning('max_players reached (%s/%s), rejecting connection', current, max_players)
            await websocket.close(code=1013, reason='Server full')
            return
    await websocket.accept()
    if _active_lock:
        with _active_lock:
            _active_connections += 1
            current = _active_connections
    else:
        _active_connections += 1
        current = _active_connections
    logger.warning('websocket connected (%s/%s)', current, max_players or 'unlimited')
    try:
        while True:
            _a = await websocket.receive()
            _d = _a.get('bytes')
            if _d is None:
                continue
            try:
                _frame = msm_protocol.parse_raw_frame(_d)
            except Exception as _err:
                logger.info('bad frame: %s', _err)
                continue
            if _frame is None or _frame.command == 'alive':
                continue
            logger.debug('IN %s params=%.500r', _frame.command, _frame.params)
            try:
                _results = msm_handlers.handle_command(_frame.command, _frame.params)
            except Exception as _err:
                logger.info('%s failed: %s', _frame.command, _err)
                continue
            for _resp_cmd, _resp_payload in _results:
                if isinstance(_resp_payload, (dict, list)):
                    msm_playerdata.coerce_wire_types(_resp_payload)
                await websocket.send_bytes(msm_protocol.build_raw_frame(_resp_cmd, _resp_payload))
                logger.debug('%s -> %s payload=%.800r', _frame.command, _resp_cmd, _resp_payload)
            if _frame.command == 'USER_LOGIN':
                for _boot_cmd, _boot_payload in msm_handlers.login_bootstrap_frames():
                    if isinstance(_boot_payload, (dict, list)):
                        msm_playerdata.coerce_wire_types(_boot_payload)
                    await websocket.send_bytes(msm_protocol.build_raw_frame(_boot_cmd, _boot_payload))
                    logger.debug('login -> %s', _boot_cmd)
    except WebSocketDisconnect:
        pass
    except Exception as _f:
        logger.info('websocket stopped: %s', _f)
    finally:
        if _active_lock:
            with _active_lock:
                _active_connections = max(0, _active_connections - 1)
                current = _active_connections
        else:
            _active_connections = max(0, _active_connections - 1)
            current = _active_connections
        logger.warning('websocket disconnected (%s/%s)', current, max_players or 'unlimited')

for route in ['/auth.php', '/auth.php/']:
    app.add_api_route(route, legacy_auth_php, methods=['GET', 'POST'])
for route in ['/purchases/steam/my_singing_monsters/ProcessInitializedPurchases.php']:
    app.add_api_route(route, purchase_order, methods=['POST'])
for route in ['/purchases/steam/my_singing_monsters/ProcessDLCPurchases.php']:
    app.add_api_route(route, purchase_dlc, methods=['POST'])
for route in ['/auth/api/token', '/auth/api/token/', '/auth/api/anon_account', '/auth/api/anon_account/', '/auth/api/steam_account', '/auth/api/steam_account/', '//auth/api/token', '//auth/api/token/', '//auth/api/anon_account', '//auth/api/anon_account/', '//auth/api/steam_account', '//auth/api/steam_account/']:
    app.add_api_route(route, auth_handler, methods=['GET', 'POST'])
for route in ['/auth/api/login', '/auth/api/login/']:
    app.add_api_route(route, login_handler, methods=['POST'])
for route in ['/auth/api/existing_accounts', '/auth/api/existing_accounts/']:
    app.add_api_route(route, existing_accounts, methods=['POST'])
for route in ['/auth/api/find_account', '/auth/api/find_account/', '//auth/api/find_account', '//auth/api/find_account/']:
    app.add_api_route(route, find_account_handler, methods=['GET', 'POST'])
for route in ['/auth/api/game_config', '/auth/api/game_config/']:
    app.add_api_route(route, game_config, methods=['GET', 'POST'])
for route in ['/waf', '/waf/', '/waf/{path:path}', '/challenge', '/challenge/', '/token', '/token/']:
    app.add_api_route(route, waf_handler, methods=['GET', 'POST', 'PUT'])
for route in ['/crap-app/msm2auth', '/crap-app/msm2auth/']:
    app.add_api_route(route, msm2auth, methods=['GET', 'POST'])
for route in ['/crap-app/msm2rh', '/crap-app/msm2rh/']:
    app.add_api_route(route, msm2rh, methods=['GET', 'POST'])
app.add_api_route(f'/{FILES_DIR.name}/files.json', files_manifest, methods=['GET', 'POST'])
app.add_api_route(f'/{FILES_DIR.name}/downloads.xml', downloads_xml, methods=['GET', 'POST'])
app.add_api_route(f'/{FILES_DIR.name}/{{path:path}}', serve_file, methods=['GET'])
app.add_api_route(PUBLIC_CONTENT_PREFIX.rstrip('/'), files_manifest, methods=['GET', 'POST'])
app.add_api_route(PUBLIC_CONTENT_PREFIX, files_manifest, methods=['GET', 'POST'])
app.add_api_route(f'{PUBLIC_CONTENT_PREFIX}files.json', files_manifest, methods=['GET', 'POST'])
app.add_api_route(f'{PUBLIC_CONTENT_PREFIX}downloads.xml', downloads_xml, methods=['GET', 'POST'])
app.add_api_route('/content/files.json', files_manifest, methods=['GET', 'POST'])
app.add_api_route('/content/downloads.xml', downloads_xml, methods=['GET', 'POST'])
app.add_api_route(f'{PUBLIC_CONTENT_PREFIX}{{path:path}}', serve_file, methods=['GET'])
app.add_api_route('/BlueBox/BlueBox.do', bluebox, methods=['GET', 'POST'])
app.add_api_route('/msm/socket', bluebox, methods=['GET', 'POST'])
app.add_api_websocket_route('/BlueBox/BlueBox.do', sfs_websocket)
app.add_api_websocket_route('/msm/socket', sfs_websocket)
app.add_api_websocket_route('/websocket', sfs_websocket)
app.add_api_route('/db/gs_player', db_gs_player, methods=['GET', 'POST'])
app.add_api_route('/db/db_island', db_db_island, methods=['GET', 'POST'])
app.add_api_route('/db/db_monster', db_db_monster, methods=['GET', 'POST'])
app.add_api_route('/{path:path}', catch_all, methods=['GET', 'POST', 'PUT', 'DELETE'])

def preload_all_db():
    """Load every JSON in Data/ into memory once at startup (huge win under load)."""
    if not SETTINGS.get("preload_db", True):
        return
    if msm_store.db_dir is None:
        return
    root = Path(msm_store.db_dir)
    if not root.is_dir():
        return
    count = 0
    for p in root.glob("*.json"):
        name = p.stem
        try:
            msm_store.load_db_json(name)
            count += 1
        except Exception as e:
            logger.warning("preload %s failed: %s", name, e)
    logger.warning("preloaded %s db files into memory", count)


async def _serve_with_retry(host, port, log_level, max_attempts=10, delay=1.0):
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        # High-concurrency uvicorn config (single worker — websockets need one process)
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level=log_level,
            loop="asyncio",
            http="h11",
            ws="websockets",
            limit_concurrency=2000,
            timeout_keep_alive=75,
            access_log=False,
            backlog=2048,
        )
        server = uvicorn.Server(config)
        _UVICORN_SERVERS.append(server)
        try:
            await server.serve()
            return
        except asyncio.CancelledError:
            return
        except OSError as e:
            last_exc = e
            if server in _UVICORN_SERVERS:
                _UVICORN_SERVERS.remove(server)
            if _SHUTDOWN_REQUESTED or attempt >= max_attempts:
                raise
            logger.warning("port %s bind failed (attempt %s/%s): %s; retrying", port, attempt, max_attempts, e)
            await asyncio.sleep(delay)
    if last_exc:
        raise last_exc


async def main():
    global _SHUTDOWN_REQUESTED
    _SHUTDOWN_REQUESTED = False
    _UVICORN_SERVERS.clear()
    host = str(SETTINGS.get("host", "0.0.0.0"))
    log_level = str(SETTINGS.get("log_level", "warning")).lower()
    # Single fixed port only
    ports = SETTINGS.get("http_ports") or [SETTINGS.get("port") or SETTINGS.get("game_port") or 9933]
    port = int(ports[0])
    preload_all_db()
    max_p = SETTINGS.get("max_players") or 0
    logger.warning(
        "MSM Private Server starting host=%s port=%s max_players=%s server_id=%s",
        host, port, max_p or "unlimited", SETTINGS.get("server_id"),
    )
    watchdog = asyncio.ensure_future(_force_exit_watchdog())
    try:
        await _serve_with_retry(host, port, log_level)
    finally:
        watchdog.cancel()
        _UVICORN_SERVERS.clear()


if __name__ == "__main__":
    # Prefer uvloop when available (faster event loop)
    try:
        import uvloop
        uvloop.install()
    except ImportError:
        pass
    asyncio.run(main())
