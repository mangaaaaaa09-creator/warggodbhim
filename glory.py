import sys, asyncio, httpx, random, json, socket, struct, time, os, uuid
import itertools, secrets, base64, math
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass

from google_play_scraper import app as play_scraper
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from protobuf_decoder.protobuf_decoder import Parser
from message_ids import MESSAGE_ID_TO_NAME
import RbcTeam_pb2
import RbcFF_pb2
import thunderFF_pb2

try:
    import CguFF_pb2
    HAS_CGUFF = True
except ImportError:
    CguFF_pb2 = None
    HAS_CGUFF = False

try:
    from dashboard_server import bot_state, start_web_dashboard
    HAS_DASHBOARD = True
except Exception:
    HAS_DASHBOARD = False
    class _DummyState:
        def log(self, *a, **k): pass
        def update_status(self, *a, **k): pass
        def update_exp(self, *a, **k): pass
        def register_account(self, *a, **k): pass
        def increment_match(self, *a, **k): pass
        def is_paused(self, *a, **k): return False
        accounts = {}
        account_credentials = {}
        account_workers = {}
        refresh_callbacks = {}
    bot_state = _DummyState()
    async def start_web_dashboard(host="0.0.0.0", port=20333): pass
WEB_HOST = "0.0.0.0"
WEB_PORT = 20333
ACCOUNTS_FILE = "accounts.json"
TOKEN_CACHE_FILE = "token_cache.json"
DEVICES_FILE = "devices.json"
TOKEN_CACHE_TTL = 4500
START_MATCH_INTERVAL    = 3.0
NEW_MATCH_DELAY         = 1.0
MAX_MATCH_DURATION      = 3000
MATCH_IDLE_TIMEOUT      = 60.0
EXP_REFRESH_INTERVAL    = 30.0
EXP_REFRESH_AFTER_MATCH_DELAY = 9.0
MAX_CONSECUTIVE_PARSE_FAILURES = 5
NON_MATCH_RECONNECT_DELAY      = 0.5
BR_MODE_ID             = 1
BR_MAP_ID              = 1
MOVEMENT_TICK_MS       = 180
MOVEMENT_RADIUS        = 150
MOVEMENT_PATTERN       = "circle"
MATCH_SEARCH_TIMEOUT   = 999999.0
MATCH_WATCHDOG_CHECK   = 999999.0
REGION_ROTATION_LIST   = ["ID"]
REGION_ROTATE_EVERY_N  = 999999
MAX_SEARCH_ATTEMPTS    = 999999
SAFE_PLAY_MODE        = True
BYPASS_TIMING_JITTER  = True
BYPASS_PACKET_JITTER  = True
BYPASS_HELLO_DELAY    = True
BYPASS_KA_JITTER      = True
ENABLE_SPEED_MOVEMENT = True
ENABLE_HTTP_PING = False
PING_INTERVAL    = 15.0
PING_TIMEOUT     = 8.0
PING_URL         = "https://loginbp.ppmainecoonghj.com/Ping"
PING_REAL_IP     = "103.109.214.211"
FALLBACK_UID = ""
FALLBACK_PASSWORD = ""
TEAM_MODE               = True
TEAM_SIZE               = 4
TEAM_PEER_WAIT_TIMEOUT  = 15.0
TEAM_CREATE_WAIT        = 1.0
TEAM_INVITE_CYCLE_WAIT  = 0.8
TEAM_INVITE_MAX_TIME    = 40.0
TEAM_HEARTBEAT_INTERVAL = 2.0
TEAM_IDLE_ITERS_TEAM    = 999999
TEAM_MEMBER_START_DELAY = 1.5
TEAM_FINAL_WAIT         = 1.5
TEAM_READY_DELAY        = 1.0
_accept_friend_request  = True
DEBUG_TEAM_PACKETS      = False

TEAM_JOIN_CONFIRM_TIMEOUT = 20.0
TEAM_JOIN_CONFIRM_POLL    = 0.5
MATCH_JOIN_CONFIRM_TIMEOUT= 20.0
SQUAD_LIFETIME_SECONDS    = 2 * 24 * 60 * 60

STOP_ALL = False

_squad_start_time: Dict[str, float] = {}
_squad_start_lock = asyncio.Lock()

async def get_squad_start(uid):
    async with _squad_start_lock: return _squad_start_time.get(str(uid))

async def set_squad_start(uid, t):
    async with _squad_start_lock:
        uid = str(uid)
        if t is None: _squad_start_time.pop(uid, None)
        else: _squad_start_time[uid] = t

async def squad_age(uid):
    t0 = await get_squad_start(uid)
    return (time.time() - t0) if t0 else 0.0

async def squad_expired(uid):
    return await squad_age(uid) >= SQUAD_LIFETIME_SECONDS

class SquadMatchSync:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.active_squad_uids = set()
        self.dead_squad_uids = set()
        self.all_dead_event = asyncio.Event()
        self.team_join_event = asyncio.Event()
        self.match_join_event = asyncio.Event()
        self._team_joined_uids = set()
        self._match_joined_uids = set()

    async def reset_all(self):
        async with self.lock:
            self.active_squad_uids.clear()
            self.dead_squad_uids.clear()
            self.all_dead_event.clear()
            self.team_join_event.clear()
            self.match_join_event.clear()
            self._team_joined_uids.clear()
            self._match_joined_uids.clear()

    async def begin_team_join(self, uids):
        async with self.lock:
            self.team_join_event.clear()
            self._team_joined_uids.clear()

    async def mark_team_joined(self, uid):
        async with self.lock:
            self._team_joined_uids.add(str(uid))
            target = len(_team_state["peers"]) if _team_state["peers"] else TEAM_SIZE
            if len(self._team_joined_uids) >= target: self.team_join_event.set()

    async def wait_all_team_joined(self, timeout=TEAM_JOIN_CONFIRM_TIMEOUT):
        try:
            await asyncio.wait_for(self.team_join_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError: return False

    async def begin_match_join(self, uids):
        async with self.lock:
            self.match_join_event.clear()
            self._match_joined_uids.clear()
            self.dead_squad_uids.clear()
            self.all_dead_event.clear()
            self.active_squad_uids = set(str(u) for u in uids)

    async def mark_match_joined(self, uid):
        async with self.lock:
            self._match_joined_uids.add(str(uid))
            target = len(self.active_squad_uids) if self.active_squad_uids else TEAM_SIZE
            if len(self._match_joined_uids) >= target: self.match_join_event.set()

    async def mark_bot_dead(self, uid):
        async with self.lock:
            uid = str(uid)
            if uid in self.active_squad_uids:
                self.dead_squad_uids.add(uid)
                if len(self.dead_squad_uids) >= len(self.active_squad_uids):
                    self.all_dead_event.set()

    async def wait_for_all_dead(self, timeout=900.0):
        try: await asyncio.wait_for(self.all_dead_event.wait(), timeout=timeout)
        except asyncio.TimeoutError: pass

squad_sync = SquadMatchSync()

_match_alive_flags: Dict[str, bool] = {}
_match_alive_lock = asyncio.Lock()

async def set_match_alive(uid, alive):
    async with _match_alive_lock: _match_alive_flags[str(uid)] = bool(alive)

async def get_match_alive(uid):
    async with _match_alive_lock: return _match_alive_flags.get(str(uid), False)

def purge_extra_accounts_from_file(keep_uids):
    if not os.path.exists(ACCOUNTS_FILE): return
    try:
        keep = set(str(u) for u in keep_uids)
        with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f: data = json.load(f)
        if isinstance(data, list):
            filtered = [a for a in data if str(a.get("uid","")) in keep or str(a.get("account_id","")) in keep]
            with open(ACCOUNTS_FILE, "w", encoding="utf-8") as f: json.dump(filtered, f, indent=2)
    except Exception: pass

def bypass_jitter(base, spread=0.35):
    if not (SAFE_PLAY_MODE and BYPASS_TIMING_JITTER): return base
    return max(0.05, base + random.uniform(-spread, spread))

def bypass_packet_jitter(base, spread_ratio=0.35):
    if not (SAFE_PLAY_MODE and BYPASS_PACKET_JITTER): return base
    return max(0.1, base + random.uniform(-base*spread_ratio, base*spread_ratio))

def bypass_hello_delay():
    if not (SAFE_PLAY_MODE and BYPASS_HELLO_DELAY): return 0.0
    return random.uniform(0.05, 0.35)

def bypass_ka_jitter(base=5.0):
    if not (SAFE_PLAY_MODE and BYPASS_KA_JITTER): return base
    return max(3.0, base + random.uniform(-0.8, 1.2))

def get_device_for_account(account_identifier):
    devices = {}
    if os.path.exists(DEVICES_FILE):
        try:
            with open(DEVICES_FILE, "r", encoding="utf-8") as f: devices = json.load(f)
        except Exception: pass
    key = str(account_identifier)
    if key in devices: return devices[key]
    dev_list = [
        ("Samsung", "SM-G998B", "Adreno (TM) 660", "Android OS 12 / API-31"),
        ("Xiaomi", "2201122G", "Adreno (TM) 730", "Android OS 13 / API-33"),
        ("Realme", "RMX3700", "Mali-G710", "Android OS 14 / API-34"),
        ("OnePlus", "CPH2451", "Adreno (TM) 740", "Android OS 13 / API-33"),
        ("OPPO", "CPH2611", "Adreno (TM) 720", "Android OS 14 / API-34"),
    ]
    brand, model, gpu, os_ver = random.choice(dev_list)
    dev = {
        "unique_device_id": f"Google|{uuid.uuid4()}",
        "brand": brand, "model": model, "gpu_renderer": gpu, "system_software": os_ver,
        "screen_width": random.choice([1080,1440,720]),
        "screen_height": random.choice([2400,3200,1600]),
        "screen_dpi": str(random.randint(300,420)),
        "memory": random.randint(2800,6500),
        "processor_details": f"ARM64 FP ASIMD AES | {random.randint(2200,3200)} | {random.randint(6,12)}",
        "client_ip": f"{random.randint(103,223)}.{random.randint(10,250)}.{random.randint(10,250)}.{random.randint(10,250)}",
    }
    devices[key] = dev
    try:
        with open(DEVICES_FILE, "w", encoding="utf-8") as f: json.dump(devices, f, indent=2)
    except Exception: pass
    return dev
_DNS_CACHE: Dict[str, Tuple[str, float]] = {}
_DNS_CACHE_TTL = 300.0

async def resolve_host_cloudflare(hostname):
    if not hostname: return hostname
    parts = hostname.split('.')
    if len(parts) == 4 and all(p.isdigit() for p in parts): return hostname
    now = time.time()
    if hostname in _DNS_CACHE:
        ip, exp = _DNS_CACHE[hostname]
        if now < exp: return ip
    try:
        loop = asyncio.get_running_loop()
        info = await loop.getaddrinfo(hostname, None, family=socket.AF_INET)
        if info:
            ip = info[0][4][0]
            _DNS_CACHE[hostname] = (ip, now + _DNS_CACHE_TTL)
            return ip
    except Exception: pass
    return hostname

def optimize_tcp_socket(sock):
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"): sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 3)
        if hasattr(socket, "TCP_KEEPINTVL"): sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 3)
        if hasattr(socket, "TCP_KEEPCNT"): sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 65536)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 65536)
    except Exception: pass

def optimize_udp_socket(sock):
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 131072)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 131072)
    except Exception: pass

client = httpx.AsyncClient(verify=False, timeout=10.0,
    limits=httpx.Limits(max_connections=100, max_keepalive_connections=50))
headers = {
    'User-Agent': 'UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)',
    'Connection': 'Keep-Alive', 'Accept-Encoding': 'gzip',
    'Content-Type': 'application/x-www-form-urlencoded',
    'X-Unity-Version': '2018.4.12f1', 'X-GA-SV': '1789535859',
    'X-GA': 'v1 1', 'ReleaseVersion': 'OB55'
}

AES_KEY = b'Yg&tc%DEuh6%Zc^8'
AES_IV  = b'6oyZDr22E3ychjM%'

CRC7_TABLE = bytes([
    0,9,18,27,36,45,54,63,72,65,90,83,108,101,126,119,25,16,11,2,61,52,47,38,
    81,88,67,74,117,124,103,110,50,59,32,41,22,31,4,13,122,115,104,97,94,87,76,69,
    43,34,57,48,15,6,29,20,99,106,113,120,71,78,85,92,100,109,118,127,64,73,82,91,
    44,37,62,55,8,1,26,19,125,116,111,102,89,80,75,66,53,60,39,46,17,24,3,10,
    86,95,68,77,114,123,96,105,30,23,12,5,58,51,40,33,79,70,93,84,107,98,121,112,
    7,14,21,28,35,42,49,56,65,72,83,90,101,108,119,126,9,0,27,18,45,36,63,54,
    88,81,74,67,124,117,110,103,16,25,2,11,52,61,38,47,115,122,97,104,87,94,69,76,
    59,50,41,32,31,22,13,4,106,99,120,113,78,71,92,85,34,43,48,57,6,15,20,29,
    37,44,55,62,1,8,19,26,109,100,127,118,73,64,91,82,60,53,46,39,24,17,10,3,
    116,125,102,111,80,89,66,75,23,30,5,12,51,58,33,40,95,86,77,68,123,114,105,96,
    14,7,28,21,42,35,56,49,70,79,84,93,98,107,112,121,
])
_DELTA = 0x9E3779B9
_ROUNDS = 16
_FIELD_SIZES = {0:1, 1:2, 2:2, 3:1, 4:2}
_FIELD_NAMES = {0:"sendOption", 1:"cmd", 2:"orderId", 3:"flags", 4:"length"}

class Colors:
    GREEN='\033[92m'; FAIL='\033[91m'; WARNING='\033[93m'
    CYAN='\033[96m'; MAGENTA='\033[95m'; WHITE='\033[97m'; ENDC='\033[0m'

def print_colored(t, c=Colors.WHITE):
    try: print(f"{c}{t}{Colors.ENDC}")
    except Exception: pass

def print_success(t):
    print_colored(f"[+] {t}", Colors.GREEN)
    try: bot_state.log(t, "success")
    except Exception: pass

def print_error(t):
    print_colored(f"[-] {t}", Colors.FAIL)
    try: bot_state.log(t, "error")
    except Exception: pass

def print_warning(t):
    print_colored(f"[!] {t}", Colors.WARNING)
    try: bot_state.log(t, "warning")
    except Exception: pass

def print_info(t):
    print_colored(f"[i] {t}", Colors.CYAN)
    try: bot_state.log(t, "info")
    except Exception: pass

def print_debug(t): pass

def log_udp_full(*a, **k): pass
def log_udp_sent_full(*a, **k): pass
def log_udp_received_full(*a, **k): pass

def get_message_name(cmd):
    return MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")

def get_proto_field(d, key, default=None):
    if not d or not isinstance(d, dict): return default
    if key in d:
        v = d[key].get('data'); return v if v is not None else default
    if str(key) in d:
        v = d[str(key)].get('data'); return v if v is not None else default
    return default

_match_counters: Dict[str, int] = {}
_match_counter_lock = asyncio.Lock()

async def _inc_match(uid):
    async with _match_counter_lock:
        _match_counters[uid] = _match_counters.get(uid, 0) + 1
        return _match_counters[uid]

async def _dec_match(uid):
    async with _match_counter_lock:
        if uid in _match_counters and _match_counters[uid] > 0:
            _match_counters[uid] -= 1
        return _match_counters.get(uid, 0)

async def _get_match_count(uid):
    async with _match_counter_lock: return _match_counters.get(uid, 0)

_team_state = {
    "peers": {},
    "leader_uid": None,
    "team_code": None,
    "pk_code": None,
    "members": set(),
    "members_lock": asyncio.Lock(),
    "lock": asyncio.Lock(),
}

async def _team_member_join(uid):
    uid = str(uid)
    async with _team_state["members_lock"]:
        before = len(_team_state["members"])
        _team_state["members"].add(uid)
        after = len(_team_state["members"])
    if after != before:
        print_success(f"[TEAM] في السكواد ({after}/{TEAM_SIZE}) | {uid}")
        await squad_sync.mark_team_joined(uid)
        if await get_squad_start(uid) is None:
            await set_squad_start(uid, time.time())
    return after

async def _team_member_leave(uid):
    async with _team_state["members_lock"]: _team_state["members"].discard(str(uid))

async def _team_member_count():
    async with _team_state["members_lock"]: return len(_team_state["members"])

async def _team_member_reset(keep_leader=True):
    async with _team_state["members_lock"]:
        _team_state["members"].clear()
        if keep_leader and _team_state["leader_uid"]:
            _team_state["members"].add(_team_state["leader_uid"])

_token_cache_memo = {}
_token_cache_memo_time = 0.0
_TOKEN_CACHE_MEMO_TTL = 5.0

def _json_serializer(obj):
    if isinstance(obj, (bytes, bytearray)): return {"__bytes_hex__": bytes(obj).hex()}
    raise TypeError(f"not serializable: {type(obj)}")

def _json_deserializer(obj):
    if isinstance(obj, dict):
        if "__bytes_hex__" in obj and len(obj) == 1:
            try: return bytes.fromhex(obj["__bytes_hex__"])
            except Exception: return b""
        return {k: _json_deserializer(v) for k, v in obj.items()}
    if isinstance(obj, list): return [_json_deserializer(x) for x in obj]
    return obj

def _load_token_cache():
    global _token_cache_memo, _token_cache_memo_time
    now = time.time()
    if _token_cache_memo and (now - _token_cache_memo_time) < _TOKEN_CACHE_MEMO_TTL:
        return _token_cache_memo
    if not os.path.exists(TOKEN_CACHE_FILE): return {}
    try:
        with open(TOKEN_CACHE_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
        if not content: return {}
        data = json.loads(content)
        if not isinstance(data, dict): raise ValueError("root must be dict")
        parsed = _json_deserializer(data)
        _token_cache_memo = parsed; _token_cache_memo_time = now
        return parsed
    except Exception:
        try: os.remove(TOKEN_CACHE_FILE)
        except Exception: pass
        return {}

def _save_token_cache(cache):
    global _token_cache_memo, _token_cache_memo_time
    try:
        tmp = TOKEN_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=_json_serializer)
        os.replace(tmp, TOKEN_CACHE_FILE)
        _token_cache_memo = cache; _token_cache_memo_time = time.time()
    except Exception: pass

def cache_get(uid):
    cache = _load_token_cache()
    e = cache.get(str(uid))
    if not e: return None
    if time.time() - e.get("cached_at", 0) > TOKEN_CACHE_TTL:
        cache_invalidate(uid); return None
    if str(e.get("account_id", "")).isdigit(): e["account_id"] = int(e["account_id"])
    if not isinstance(e.get("login_payload_data"), (bytes, bytearray)):
        cache_invalidate(uid); return None
    return e

def cache_set(uid, data):
    cache = _load_token_cache()
    e = dict(data); e["cached_at"] = time.time()
    cache[str(uid)] = e; _save_token_cache(cache)

def cache_invalidate(uid):
    cache = _load_token_cache()
    if str(uid) in cache:
        del cache[str(uid)]; _save_token_cache(cache)

def _update_cache_profile(data, level, exp):
    try:
        keys = []
        if data.get('auth_uid'): keys.append(str(data['auth_uid']))
        if data.get('auth_token'): keys.append(f"tok_{data['auth_token'][:20]}")
        if not keys: return
        cache = _load_token_cache(); ch = False
        for k in keys:
            if k in cache and isinstance(cache[k], dict):
                cache[k]['level'] = level; cache[k]['exp'] = exp; ch = True
        if ch: _save_token_cache(cache)
    except Exception: pass
async def aes_encrypt(payload, key, iv):
    return AES.new(key, AES.MODE_CBC, iv).encrypt(pad(payload, AES.block_size))

async def get_playstore_version():
    loop = asyncio.get_event_loop()
    res = await loop.run_in_executor(None, lambda: play_scraper('com.dts.freefireth', lang='hi', country='id'))
    return res.get("version")

async def version_config():
    app_version = await get_playstore_version()
    url = ("https://version.ggwhitehawk.com/live/ver.php"
           f"?version={app_version}&lang=hi&device=android&channel=android"
           "&appstore=googleplay&region=ID&whitelist_version=1.3.0&whitelist_sp_version=1.0.0")
    try:
        r = await client.get(url); r.raise_for_status()
        d = r.json()
        su = d.get("server_url"); rv = d.get("remote_version"); lr = d.get("latest_release_version")
        if not su or not rv or not lr: return None
        return lr, rv, su
    except Exception: return None

async def get_access_token(uid, password):
    url = "https://100067.connect.garena.com/oauth/guest/token/grant"
    hdrs = {
        "Host": "100067.connect.garena.com",
        "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 12; SM-G998B)",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept-Encoding": "gzip, deflate, br", "Connection": "close"
    }
    data = {
        "uid": uid, "password": password, "response_type": "token", "client_type": "2",
        "client_secret": "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_id": "100067"
    }
    for attempt in range(5):
        try:
            r = await client.post(url, headers=hdrs, data=data)
            if r.status_code == 200:
                d = r.json()
                oid = d.get("open_id"); at = d.get("access_token"); pf = d.get("platform", 4)
                if oid and at: return oid, at, pf
            if r.status_code == 429: await asyncio.sleep(1); continue
        except Exception: pass
        await asyncio.sleep(0.5)
    return None

async def parse_results(parsed):
    out = {}
    for r in parsed:
        fd = {"wire_type": r.wire_type}
        if r.wire_type in ("varint","string","bytes"): fd["data"] = r.data
        elif r.wire_type == "length_delimited":
            fd["data"] = await parse_results(r.data.results)
        out[r.field] = fd
    return out

async def decode_protobuf(data):
    parsed = Parser().parse(data)
    return json.dumps(await parse_results(parsed))

def decode_protobuf_dict_safe(data):
    try: return _recursive_dict(Parser().parse(data))
    except Exception: return {}

def _recursive_dict(results):
    out = {}
    for r in results:
        fd = {"wire_type": r.wire_type}
        if r.wire_type in ("varint","string","bytes"): fd["data"] = r.data
        elif r.wire_type == "length_delimited":
            if hasattr(r.data, "results"): fd["data"] = _recursive_dict(r.data.results)
            elif isinstance(r.data, list): fd["data"] = _recursive_dict(r.data)
            else: fd["data"] = str(r.data)
        out[str(r.field)] = fd
    return out

def _decode_proto_manual(data):
    result = {}; offset = 0; data_len = len(data)
    while offset < data_len:
        header = 0; shift = 0
        while offset < data_len:
            b = data[offset]; offset += 1
            header |= (b & 0x7F) << shift
            if not (b & 0x80): break
            shift += 7
            if shift > 28: break
        if header == 0: break
        fn = header >> 3; wt = header & 0x7
        if fn == 0: break
        if wt == 0:
            v = 0; shift = 0
            while offset < data_len:
                b = data[offset]; offset += 1
                v |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
                if shift > 63: break
            result[fn] = v
        elif wt == 2:
            length = 0; shift = 0
            while offset < data_len:
                b = data[offset]; offset += 1
                length |= (b & 0x7F) << shift
                if not (b & 0x80): break
                shift += 7
                if shift > 28: break
            if length > data_len - offset: break
            value = data[offset:offset+length]; offset += length
            try:
                s = value.decode('utf-8')
                if s and all(31 < ord(c) < 127 or ord(c) in (9,10,13) for c in s):
                    result[fn] = s
                else:
                    nested = _decode_proto_manual(value)
                    result[fn] = nested if nested else value.hex()
            except UnicodeDecodeError:
                nested = _decode_proto_manual(value)
                result[fn] = nested if nested else value.hex()
        elif wt == 5: offset += 4
        elif wt == 1: offset += 8
        else: break
    return result

def encode_varint(n):
    if n < 0: return b''
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)

def build_proto(fields):
    parts = []
    for k, v in fields.items():
        if isinstance(v, dict):
            nested = build_proto(v)
            parts.append(encode_varint((k << 3) | 2) + encode_varint(len(nested)) + nested)
        elif isinstance(v, int):
            parts.append(encode_varint((k << 3) | 0) + encode_varint(v))
        elif isinstance(v, (str, bytes)):
            ev = v.encode() if isinstance(v, str) else v
            parts.append(encode_varint((k << 3) | 2) + encode_varint(len(ev)) + ev)
    return b''.join(parts)

def encrypt_api(plain_hex):
    return AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(
        pad(bytes.fromhex(plain_hex), AES.block_size)).hex()

def encrypt_api_bytes(plain_bytes):
    return AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(plain_bytes, AES.block_size))

def _pb_varint(fn, val): return encode_varint((fn << 3) | 0) + encode_varint(val)
def _pb_length(fn, val):
    enc = val.encode('utf-8') if isinstance(val, str) else val
    return encode_varint((fn << 3) | 2) + encode_varint(len(enc)) + enc

def create_proto(fields):
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(field, str): field = int(field)
        if isinstance(value, dict):
            packet.extend(_pb_length(field, bytes(create_proto(value))))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict): packet.extend(_pb_length(field, bytes(create_proto(item))))
                elif isinstance(item, str): packet.extend(_pb_length(field, item))
                elif isinstance(item, (bytes, bytearray)): packet.extend(_pb_length(field, bytes(item)))
                elif isinstance(item, bool): packet.extend(_pb_varint(field, 1 if item else 0))
                elif isinstance(item, int): packet.extend(_pb_varint(field, item))
        elif isinstance(value, bool): packet.extend(_pb_varint(field, 1 if value else 0))
        elif isinstance(value, int): packet.extend(_pb_varint(field, value))
        elif isinstance(value, str): packet.extend(_pb_length(field, value))
        elif isinstance(value, (bytes, bytearray)): packet.extend(_pb_length(field, bytes(value)))
    return bytes(packet)

def create_packet(Pk, N, K, V):
    if isinstance(K, str): K = bytes.fromhex(K) if len(K) == 32 else K.encode()
    if isinstance(V, str): V = bytes.fromhex(V) if len(V) == 32 else V.encode()
    PkEnc = AES.new(K, AES.MODE_CBC, V).encrypt(pad(bytes.fromhex(Pk), 16)).hex()
    L = len(PkEnc) // 2
    hexlen = hex(L)[2:]
    if len(hexlen) % 2 != 0: hexlen = '0' + hexlen
    pad_len = 12 - len(N) - len(hexlen)
    if pad_len < 0: pad_len = 0
    return bytes.fromhex(N + ('0' * pad_len) + hexlen + PkEnc)
def create_team(key, iv, game_version="1.132.9"):
    fields = {1: 1, 2: {2: bytes.fromhex("01"), 3: 1, 4: 3, 5: "en",
        8: {1: "IDC3", 2: 123, 3: "ID"}, 9: 1,
        10: bytes.fromhex("01090a0b1219202729"), 11: 2, 13: 1,
        14: {1: "08FBA33B4BABE2790205390333330000009700050092005F72697EB2134DCBB2467625142201040e38e848dc0e748c3f6aa04d81000000ff1113090dcacfa16d",
             2: 478, 3: "7e585d55", 4: "y[Z]", 6: 12, 7: "15686677735a7506101c",
             8: str(game_version), 9: 3, 10: 1, 11: "03626253513637754174"},
        19: 329, 21: bytes.fromhex("374f521955"), 24: {1: 21},
        27: "a_6534489873065906362"}}
    return create_packet(create_proto(fields).hex(), "0515", key, iv)

def team_fresh(account_id, key, iv):
    return create_packet(create_proto({1: 72, 2: {1: int(account_id)}}).hex(), "0515", key, iv)

def invite_player_in_team(target_uid, key, iv, region="ID"):
    return create_packet(create_proto({1: 2, 2: {1: int(target_uid), 2: region, 4: 1}}).hex(),
                         "0515", key, iv)

def accept_team_invite(target_uid, group_id, key, iv):
    fields = {1: 4, 2: {1: int(target_uid), 3: int(target_uid),
        4: bytes.fromhex("0107090a0b120f19202729"), 8: 1,
        9: {1: "08FBA33B0522052002041B0222220007000C00010004000547E265AE1080779546762514110104076fa2e8770e748c3f6a68ed75000000ff08080500cacfa16d",
            2: 235, 3: {14: 80, 11: 86}, 4: "{Y\\R", 6: 13, 7: {2: 4},
            8: "1.132.9", 9: 2, 10: 1, 11: "0362625351"},
        10: str(group_id),
        11: {"1": "IDC3", "2": 107, "3": "ID"}, 13: "en", 16: "374f5219",
        20: {1: 21}, 23: "a_6534489873065906362",
        24: "https://dl-sg-production.freefiremobile.com/", 27: {1: 2, 2: 4}}}
    return create_packet(create_proto(fields).hex(), "0515", key, iv)

def start_match_team(account_id, key, iv, region="ID"):
    fields = {1: 9, 2: {1: int(account_id), 7: {1: "IDC3", 2: 410, 3: region}}}
    return create_packet(create_proto(fields).hex(), "0515", key, iv)

def ready_for_game(uid, key, iv):
    return create_packet(create_proto({1: 15, 2: {1: uid, 2: 1}}).hex(), "0519", key, iv)

async def build_majorlogin_payload(open_id, access_token, platform, client_version, dev):
    try:
        p = {3: str(datetime.now())[:-7], 4: "free fire", 5: "1",
            7: str(client_version) if client_version else "1.132.8",
            8: str(dev.get("system_software", "Android OS 14 / API-34")),
            9: "Handheld", 10: "Telkomsel", 11: "CarrierDataNetwork",
            12: str(dev.get("screen_width", 1639)), 13: str(dev.get("screen_height", 720)),
            14: str(dev.get("screen_dpi", 320)), 15: str(dev.get("processor_details", "ARM64")),
            16: str(dev.get("memory", 5653)), 17: str(dev.get("gpu_renderer", "Mali-G52")),
            18: "OpenGL ES 3.2 v1.r49p1-03bet0",
            19: str(dev.get("unique_device_id", f"Google|{uuid.uuid4()}")),
            20: str(dev.get("client_ip", "182.5.135.225")),
            21: "en", 22: str(open_id), 23: str(platform), 24: "Handheld",
            25: str(dev.get("model", "Xiaomi")), 26: "ID",
            29: str(access_token), 30: "1", 41: "Telkomsel", 42: "4G",
            57: "7428b253defc164018c604a1ebbfebdf", 60: "109278", 61: "55402",
            62: "868", 64: "55927", 65: "109278", 66: "55927", 67: "109278",
            73: 2, 74: "/data/app/~~6Cw028g_ld-8Z0z2qhrOLA==/com.dts.freefireth-i3wiaEmpx8CbiRVhUMx_ag==/lib/arm64",
            76: 1, 77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/~~6Cw028g_ld-8Z0z2qhrOLA==/com.dts.freefireth-i3wiaEmpx8CbiRVhUMx_ag==/base.apk",
            78: 6, 79: 1, 81: "32", 83: "2019121229", 85: 3,
            86: "OpenGLES2", 87: 3071, 88: 4, 89: 14466, 93: "3rd_party",
            94: "KqsHTyb7yHjsAiyNWUUZa0DSOD6U0AhDQ76smAo1WeHHHpSmJ8KMRyRrxb2ttgJqO9YOqO/K6AORAvDMAX/qBS8+JahIkrM7kHfzlfULbgRAoZ9r",
            95: "111207", 96: "{\"cur_rate\":[60,90,120],\"support_etc2\":true}", 97: "1",
            98: "1", 99: str(platform), 100: str(platform),
            103: "1", 104: "52837", 105: "1",
            106: "https://dl.gmc.freefiremobile.com/live/ABHotUpdates/|211c933168f55902c7dfbfd8c4e2957d",
            107: "1.3fb8adbf45f44ce9"}
        return encrypt_api_bytes(build_proto(p))
    except Exception: return None

async def send_majorlogin(data, release_version, server_url):
    try:
        url = f"{server_url}MajorLogin" if server_url.endswith('/') else f"{server_url}/MajorLogin"
        hdrs = headers.copy(); hdrs["ReleaseVersion"] = str(release_version)
        r = await client.post(url, headers=hdrs, data=data)
        if r.status_code != 200: return None
        c = r.content
        if len(c) < 40: return None
        for off in [0, 64] + list(range(128)):
            try:
                m = thunderFF_pb2.MajorLoginRes(); m.ParseFromString(c[off:])
                if m.region and m.token: return m
            except Exception: continue
        return None
    except Exception: return None

async def send_getlogin(data, base_url, token, release_version):
    try:
        url = f"{base_url.rstrip('/')}/GetLoginData"
        hdrs = headers.copy()
        hdrs["ReleaseVersion"] = release_version
        hdrs['Authorization'] = f"Bearer {token}"
        hdrs['Host'] = "clientbp.ppmainecoonghj.com"
        r = await client.post(url, headers=hdrs, data=data)
        if r.status_code != 200: return None
        c = r.content
        rp = thunderFF_pb2.GetLoginDataRes(); ok = False
        try:
            rp.ParseFromString(c)
            if rp.functional_addrs or rp.informational_addrs: ok = True
        except Exception: pass
        if not ok:
            for off in range(min(128, len(c))):
                try:
                    cand = thunderFF_pb2.GetLoginDataRes(); cand.ParseFromString(c[off:])
                    if cand.functional_addrs or cand.informational_addrs: rp = cand; break
                except Exception: continue
        dd = {}
        try: dd = await parse_results(Parser().parse(c.hex()))
        except Exception: pass
        return rp, dd
    except Exception: return None

async def build_tcp_startup_packet(account_id, token, server_time, key, iv, region="ID", typ='OnLine'):
    uid_hex = f"{int(account_id):016x}"
    ts_hex = f"{int(server_time):08x}"
    enc = (await aes_encrypt(token.encode(), key, iv)).hex()
    enc_len = f"{len(enc)//2:08x}"
    reg = str(region).upper() if region else "ID"
    if typ == 'OnLine':
        pfx = '7119' if reg == 'ID' else ('7114' if reg == 'IND' else '7115')
        return f"{pfx}{uid_hex}{ts_hex}00000000{enc_len}{enc}"
    pfx = '9219' if reg == 'ID' else ('9214' if reg == 'IND' else '9215')
    return f"{pfx}{uid_hex}{ts_hex}{enc_len}{enc}"

async def send_keep_alive(region="ID"):
    try:
        reg = str(region).upper() if region else "ID"
        return bytes.fromhex("0219" if reg == "ID" else ("0214" if reg == "IND" else "0215"))
    except Exception: return bytes.fromhex("0219")

BR_HEX = (
    "080112800a0a010110013a110a044944433110aa011a064555524f50453a100a044944433210311a064555524f5045"
    "40014a0801090a0b1219202758016291090a80013038384638324246303241393637363730323031303130303030"
    "30303030303030303031363030303130303135303030323232463937454545304630303030303034363736323531"
    "34303030303030303030303030303030303030303030303030303030303030303030303030306666303030303030"
    "3030636163666131366410241afb02735d5e571400024a775d45414d1a041b1c001f11010449715f4243481a001e"
    "1d071c1703004b1a4066785c524570735c51486775421b5c5a4c07504042685a63610816054e19025e7519600147"
    "7c015165406370195f5547404e4550640103020f1304064863754268676c755f65576e40467e5f0a417a4701026d"
    "675d6e73670b1108495a4c6a0b78470b740065645e525a057258425f584a447d4e6759440c11044e7c596d7f4b62"
    "5f7d04055a47505c4e1d6b5b4107447d7201057d7f0f14084e430457674f7e517d72015172415d027473577c4d61"
    "5f79535256780911030f4d5e027a797f614165067806505d53777750475e75064257076500460817014e741e7e50"
    "78487e7a7c465e7669767153497064605a7376677773550d160148037e18675966787f4c42607a645f577e7b44"
    "1b460776026b18685d0b110205490060020f70676175654674706671797f41067346677c4e06585e780f15074c57"
    "047b40517075415f6364027259674b5b0166407f7340600407770a22047a5d5c52300b3a0a167305067162727516"
    "134208312e3133302e3232480350015ae90403626253513635686e556f4e36416456324b796f566c636f47777648"
    "4f624e56526c4d727073504b4f43654177616848494176795556497273743752737149734a7a786b324752526837"
    "7a2f637664626d504f6a73552f79626d38547a4c69586d2f474351696d494b53486833447955726f39515152756c"
    "34545350626d6d624b7949565937545671577059455372323646572f59624578507338514f706d317372785455736c"
    "30796a434144444d4f34616a654b615753366361496c554b4963797a494e396d52516f715277687939797257476d"
    "337a644345337a6a61436f492f5a585233656f65365a42647a64677654636b6b665733356e4d4c6a6a56507256"
    "4b6433523172756174394e50514150724a5546627859696c4c5a3859707336654d5447666b6649793574666a526c"
    "314d4648706b51774c6373374439656378566c41636f374e664f6d2b30654756466c443474447870677138553359"
    "5973587645384842502f70666c767a737138316a32524f4d7857437556445442492f684735625462773166456e42"
    "49725162762b636144775147696f74554e316d4c4b77734379456f4766706746614251457645672b736a764c4c78"
    "704743334c304a5344532f74526169504354553344374e6249306547516651622f5a466f4c36455630775a324d6f"
    "583932414c572f5049752f56634663584e70596b356f7966326151416a536971486a2f363276354843644f525551"
    "303578754e6171795251625653704654303137655237675255636b4966366c6f447476342b514e4a4670766d7475"
    "7077707774396a5a5974437a4b56743657726d6e36785837706658456251555434684f3758a201050803108703a2"
    "01050804108103a20105080510c001a20105081d10cc01a2010408161078a20105080e10af01a201020815"
)

async def start_game_battle_royale(region, client_version, writer, key, iv):
    packet = bytes.fromhex(BR_HEX)
    try:
        if HAS_CGUFF and CguFF_pb2 is not None:
            proto = CguFF_pb2.StartMatch(); proto.ParseFromString(packet)
            if hasattr(proto.main, 'region_list') and len(proto.main.region_list) > 0:
                proto.main.region_list[0].region = region
                if len(proto.main.region_list) > 1: proto.main.region_list[1].region = region
            if hasattr(proto.main, 'client_version'):
                proto.main.client_version.remote_version = client_version
            packet = proto.SerializeToString()
    except Exception: pass
    enc = (await aes_encrypt(packet, key, iv)).hex()
    plen = len(enc) // 2
    hl = hex(plen)[2:]
    hl = hl if len(hl) > 1 else "0" + hl
    reg = str(region).upper() if region else "BD"
    pfx = "031500" if reg == "ID" else ("031400" if reg == "IND" else "031500")
    writer.write(bytes.fromhex(pfx + "0" * (6 - len(hl)) + hl + enc)); await writer.drain()
async def has_ssan_zig(n):
    z = (n << 1) & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while z >= 0x80: out.append((z & 0x7F) | 0x80); z >>= 7
    out.append(z); return bytes(out)

async def uleb_encode(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)

async def zigzag_encode_signed(n):
    try: n = int(n)
    except Exception: n = 0
    zz = (n << 1) ^ (n >> 63)
    if zz < 0: zz = -zz
    out = bytearray()
    while True:
        b = zz & 0x7F; zz >>= 7
        if zz: b |= 0x80
        out.append(b)
        if not zz: break
    return bytes(out)

def zigzag_encode(n):
    z = n << 1
    out = bytearray()
    while z >= 0x80:
        out.append((z & 0x7F) | 0x80)
        z >>= 7
    out.append(z)
    return bytes(out)

def uleb_encode_sync(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)

def read_varints(b):
    out = []
    i = 0
    while i < len(b):
        n = 0
        shift = 0
        while i < len(b):
            byte = b[i]
            i += 1
            n |= (byte & 0x7F) << shift
            if not byte & 0x80:
                break
            shift += 7
        out.append(n)
    return out

def crc7(data):
    c = 0
    for b in data:
        c = CRC7_TABLE[((2 * (c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

def _layouts_from_mask(mask):
    ru = [int(c) for c in str(mask).strip()]
    nr = [c for c in ru if c != 2]
    return ru, nr

def build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, move_state, account_uid, room_code, phase="arena"):
    if phase == "arena":
        TAIL = (b"\x00" * 7 + b"\xbd\xb6\xe1\xf3\x03" + b"\x00" + b"\xc4\xb6\xe1\xfb\x0b" + b"\x00\x00")
    elif phase == "game":
        TAIL = (b"\x00" * 7 + b"\x93\xca\xd5\xf9\x0b" + b"\x8e\xfe\xfc\xf7\x0b" + b"\xf4\xe0\xfe\xf7\x03" + b"\x00\x00")
    else:
        TAIL = (b"\x00" * 7 + b"\xbd\xb6\xe1\xf3\x03" + b"\x00" + b"\xc4\xb6\xe1\xfb\x0b" + b"\x00\x00")
    
    body = bytearray()
    body += uleb_encode_sync(account_uid)
    body += uleb_encode_sync(player_state)
    body += zigzag_encode(x)
    body += zigzag_encode(y)
    body += zigzag_encode(z)
    body += b"\x00"
    body += uleb_encode_sync(move_state)
    body += TAIL
    body += uleb_encode_sync(tick)
    body += b"\x00\x00\x00"
    body += uleb_encode_sync(counter)
    body = bytes(body)
    
    k = key_bytes[0]
    v80 = ((k << 8) | k) & 0xFFFF
    
    h = bytearray()
    h.append(msg_key)
    h.append(0x00)
    h.append(0 ^ k)
    h += ((2001 ^ v80) & 0xFFFF).to_bytes(2, "little")
    h += (len(body) ^ v80).to_bytes(2, "little")
    h.append(0 ^ k)
    h[1] = crc7(bytes(h[2:]) + body)
    
    return bytes(h) + body

# ═══════════════ SYNC SEND FUNCTIONS (مع إصلاح loop) ═══════════════
async def send_idle(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 200, account_uid, room_code, "arena")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_run(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 26, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_jump(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 40, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_air(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 104, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_peak(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 132, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_land(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 136, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_drop(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 116, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_fall(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 60, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 82, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute_swing(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 76, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute_steer(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 56, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute_brake(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 46, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute_land_prep(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 36, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute_land(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 20, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_parachute_landed(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 8, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def send_vehicle(key_bytes, msg_key, player_state, x, y, z, tick, counter, sock, server_addr, account_uid, room_code):
    pkt = build_movement_packet_2001(key_bytes, msg_key, player_state, x, y, z, tick, counter, 160, account_uid, room_code, "game")
    _loop = asyncio.get_running_loop()
    await _loop.sock_sendto(sock, pkt, server_addr)
    return pkt

async def tea_enc(v0, v1, k0, k1, k2, k3):
    s = 0
    for _ in range(_ROUNDS):
        s = (s + _DELTA) & 0xFFFFFFFF
        v0 = (v0 + (((((v1<<4)&0xFFFFFFFF)+k0)&0xFFFFFFFF ^ ((v1+s)&0xFFFFFFFF) ^ (((v1>>5)+k1)&0xFFFFFFFF)))) & 0xFFFFFFFF
        v1 = (v1 + (((((v0<<4)&0xFFFFFFFF)+k2)&0xFFFFFFFF ^ ((v0+s)&0xFFFFFFFF) ^ (((v0>>5)+k3)&0xFFFFFFFF)))) & 0xFFFFFFFF
    return v0, v1

async def tea_dec(v0, v1, k0, k1, k2, k3):
    s = (_DELTA * _ROUNDS) & 0xFFFFFFFF
    for _ in range(_ROUNDS):
        v1 = (v1 - (((((v0<<4)&0xFFFFFFFF)+k2)&0xFFFFFFFF ^ ((v0+s)&0xFFFFFFFF) ^ (((v0>>5)+k3)&0xFFFFFFFF)))) & 0xFFFFFFFF
        v0 = (v0 - (((((v1<<4)&0xFFFFFFFF)+k0)&0xFFFFFFFF ^ ((v1+s)&0xFFFFFFFF) ^ (((v1>>5)+k1)&0xFFFFFFFF)))) & 0xFFFFFFFF
        s = (s - _DELTA) & 0xFFFFFFFF
    return v0, v1

async def tea_cbc_encrypt(padded, key_bytes):
    k0,k1,k2,k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0,4,8,12))
    out = bytearray(len(padded)); pc = bytearray(8); pi = bytearray(8)
    for i in range(0, len(padded), 8):
        x = bytearray(8)
        for j in range(8): x[j] = padded[i+j] ^ pc[j]
        e0,e1 = await tea_enc(struct.unpack_from("<I", x, 0)[0], struct.unpack_from("<I", x, 4)[0], k0,k1,k2,k3)
        enc = bytearray(8)
        struct.pack_into("<I", enc, 0, e0); struct.pack_into("<I", enc, 4, e1)
        for j in range(8): out[i+j] = enc[j] ^ pi[j]
        pc[:] = out[i:i+8]; pi[:] = x
    return bytes(out)

async def tea_cbc_decrypt(body, key_bytes):
    k0,k1,k2,k3 = (struct.unpack_from("<I", key_bytes, o)[0] for o in (0,4,8,12))
    out = bytearray(len(body)); pi = bytearray(8); pc = bytearray(8)
    x = bytearray(8); dec = bytearray(8)
    for i in range(0, len(body), 8):
        for j in range(8): x[j] = body[i+j] ^ pi[j]
        d0,d1 = await tea_dec(struct.unpack_from("<I", x, 0)[0], struct.unpack_from("<I", x, 4)[0], k0,k1,k2,k3)
        struct.pack_into("<I", dec, 0, d0); struct.pack_into("<I", dec, 4, d1)
        for j in range(8): out[i+j] = dec[j] ^ pc[j]
        pc[:] = body[i:i+8]; pi[:] = dec
    return bytes(out)

async def build_padded(content):
    pad_len = (8 - (len(content) + 10) % 8) % 8
    return bytes([pad_len, 0, 0]) + b"\x00" * pad_len + content + b"\x00" * 7

async def crc7_buff(crc, buf):
    c = crc & 0x7F
    for b in buf: c = CRC7_TABLE[((2*(c & 0xFF)) ^ (b & 0xFF)) & 0xFF] & 0x7F
    return c & 0x7F

async def encode_header(layout, so, cmd, oid, flags, length, k, v80):
    out = bytearray()
    for code in layout:
        val = {0:so, 1:cmd, 2:oid, 3:flags, 4:length}[code]
        if _FIELD_SIZES[code] == 1: out.append((val & 0xFF) ^ k)
        else:
            v = ((val & 0xFFFF) ^ v80) & 0xFFFF
            out.append(v & 0xFF); out.append((v >> 8) & 0xFF)
    return bytes(out)

async def sv_frame(msg_key, layout, so, cmd, oid, flags, content, key, encrypted=True):
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0]) + await encode_header(layout, so, cmd, oid, flags, len(body), k, v80)
    pkt = bytearray(hdr + body)
    pkt[1] = await crc7_buff(0, bytes(pkt[2:])) & 0x7F
    return bytes(pkt)

async def build_packet(msg_key, layout, so, cmd, oid, flags, content, key, encrypted=True):
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    body = await tea_cbc_encrypt(await build_padded(content), key) if encrypted else content
    hdr = bytearray([msg_key, 0])
    for code in layout:
        val = {0:so, 1:cmd, 2:oid, 3:flags, 4:len(body)}[code]
        if _FIELD_SIZES[code] == 1: hdr.append((val & 0xFF) ^ k)
        else:
            v = ((val & 0xFFFF) ^ v80) & 0xFFFF
            hdr.append(v & 0xFF); hdr.append((v >> 8) & 0xFF)
    pkt = bytearray(hdr + body)
    pkt[1] = await crc7_buff(0, bytes(pkt[2:])) & 0x7F
    return bytes(pkt)

async def layouts_from_mask(mask):
    ru = [int(c) for c in str(mask).strip()]
    nr = [c for c in ru if c != 2]
    return ru, nr

async def build_hello_packet(text, key, layout):
    data = text.encode("utf-8")
    if len(data) > 25: raise ValueError("too long")
    content = b"\x10\x00\x00\x00" + data + b"\x00" * (29 - 4 - len(data))
    k = key[0] if key else 10
    v80 = ((k << 8) | k) & 0xFFFF
    layout = [int(c) for c in str(layout).strip()] if isinstance(layout, str) else list(layout)
    padded = await build_padded(content)
    enc_body = await tea_cbc_encrypt(padded, key)
    hdr = await encode_header(layout, 1, 1, 0, 1, len(enc_body), k, v80)
    pkt = bytearray([0x63, 0x00]) + hdr + enc_body
    pkt[1] = await crc7_buff(0, pkt[2:]) & 0x7F
    return bytes(pkt).hex()

async def classify(frame):
    cmd = frame["cmd"]
    name = MESSAGE_ID_TO_NAME.get(cmd, f"UNKNOWN_{cmd}")
    if name == "UDP_HELLO": return "HELLO"
    if name == "UDP_ACK": return "ACK"
    if name == "UDP_PING": return "PING"
    if name == "RUDP_JOIN_MATCH": return "JOIN_MATCH"
    if name.startswith("RUDP_"): return name
    if name.startswith("UDP_"): return name
    return "DATA"

async def reply_for(frame, key, mask, ack_key=0x68, ping_key=0x6D, hello_key=0x5B, ack_style="short"):
    _, nr = await layouts_from_mask(mask)
    typ = await classify(frame)
    if typ == "HELLO":
        if ack_style == "echo":
            content = frame["content"] if frame["content"] else b"\x10\x00\x00\x00"
            return typ, await build_packet(hello_key, nr, 1, 1, None, 1, content, key)
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x01\x00", key)
    if typ == "ACK":
        content = frame["content"] if frame["content"] else b"\x01\x00"
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, content, key)
    if typ == "PING":
        c = frame["content"]
        counter = c[:4] if len(c) >= 4 else c
        return typ, await build_packet(ping_key, nr, 0, 3, None, 0, counter + b"\x00\x00\x00", key, encrypted=False)
    if typ == "JOIN_MATCH":
        return typ, await build_packet(ack_key, nr, 0, 2, None, 1, b"\x02\x00", key)
    return typ, None

async def keepalive_ping(sock, ip, port, key_bytes, mask, stop_event):
    nr = (await layouts_from_mask(mask))[1]
    ping_keys = [0x66, 0x6D, 0x69, 0x6C, 0x6B, 0x6E, 0x6F, 0x70]
    loop = asyncio.get_event_loop(); i = 0
    while not stop_event.is_set():
        pk = ping_keys[i % len(ping_keys)]
        counter = int(time.time() * 1000) & 0xFFFFFFFF
        pkt = await build_packet(pk, nr, 0, 3, None, 0, struct.pack("<I", counter) + b"\x00\x00\x00", key_bytes, encrypted=False)
        try: await loop.sock_sendto(sock, pkt, (ip, port))
        except Exception: pass
        i += 1
        try: await asyncio.wait_for(stop_event.wait(), timeout=bypass_packet_jitter(2.0, 0.4))
        except asyncio.TimeoutError: pass

async def try_header(buf, layout, k, v80):
    off = 2; out = {}
    for code in layout:
        size = _FIELD_SIZES[code]
        if off + size > len(buf): return None
        out[_FIELD_NAMES[code]] = ((buf[off] ^ k) if size == 1 else ((buf[off] | (buf[off+1] << 8)) ^ v80) & 0xFFFF)
        off += size
    out["headerLen"] = off
    return out

async def oicq_unpad(padded):
    if not padded or len(padded) < 8: return None
    if not all(padded[-1-i] == 0 for i in range(7)): return None
    pad_len = padded[0] & 0x07
    s = 3 + pad_len; e = len(padded) - 7
    return padded[s:e] if s < e else b""

async def decode_packet(packet, key, mask=None):
    data = bytes(packet) if isinstance(packet, bytes) else bytes.fromhex(packet)
    if len(data) < 8: return None
    k = key[0]; v80 = ((k << 8) | k) & 0xFFFF
    crc_ok = (data[1] & 0x7F) == await crc7_buff(0, data[2:])
    candidates = []
    if mask:
        ru, nr = await layouts_from_mask(mask)
        layouts = [("RUDP", ru), ("nonRUDP", nr)]
    else:
        layouts = [("RUDP", list(p)) for p in itertools.permutations([0,1,2,3,4])]
        layouts += [("nonRUDP", list(p)) for p in itertools.permutations([0,1,3,4])]
    for kind, layout in layouts:
        f = await try_header(data, layout, k, v80)
        if not f: continue
        if f["flags"] > 7 or f["sendOption"] > 7: continue
        if f["length"] != len(data) - f["headerLen"]: continue
        body = data[f["headerLen"]:f["headerLen"]+f["length"]]
        content = None
        if f["flags"] & 1:
            if len(body) < 8 or len(body) % 8 != 0: continue
            padded = await tea_cbc_decrypt(body, key)
            content = await oicq_unpad(padded)
            if content is None: continue
        else: content = body
        score = (1 if crc_ok else 0) + (1 if content is not None else 0)
        candidates.append({"kind":kind,"layout":layout,"headerLen":f["headerLen"],"msgKey":data[0],"cmd":f["cmd"],"flags":f["flags"],"sendOption":f["sendOption"],"orderId":f.get("orderId"),"length":f["length"],"content":content,"crcOk":crc_ok,"score":score,"total":len(data)})
    if not candidates: return None
    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[0]

async def build_match_startup_packets(token, udp_key, match_code, account_id, block_val,
                                      server_ip="", region="ID", client_version="1.132.6",
                                      client_version_code="2019121229", access_token="",
                                      mode_id=BR_MODE_ID, map_id=BR_MAP_ID):
    token = token.strip(); udp_key = bytes.fromhex(udp_key)
    match_code = [int(ch) for ch in str(match_code).strip()]
    thunder_jwt = token[:660] if len(token) > 660 else token
    sharma_jwt = token[660:] if len(token) > 660 else ""
    eth = thunder_jwt.encode() if isinstance(thunder_jwt, str) else thunder_jwt
    esh = sharma_jwt.encode() if isinstance(sharma_jwt, str) else sharma_jwt
    garena420 = await has_ssan_zig(len(eth)) + eth
    reg = str(region).upper() if region else "ID"
    csoversea_block = bytes.fromhex("ca0163736f7665727365612e7374726f6e67686f6c642e66726565666972656d6f62696c652e636f6d3b302e302e302e303b33342e3132362e37362e34353b33342e38372e3137372e31343b33342e38372e3137302e3233303b33352e3138352e3138332e3537000000000000010000000000000000000000000100000800000100000000000100a8a2d7bebd8d8bdf110200")
    mid = bytes.fromhex('0000000001000102030101') + await has_ssan_zig(len(reg)) + reg.encode()
    mid += bytes.fromhex('0001030003000004')
    mid += await has_ssan_zig(len(client_version)) + client_version.encode()
    mid += await has_ssan_zig(len(client_version_code)) + client_version_code.encode()
    mid += csoversea_block
    clean_ip = server_ip.split(':')[0] if server_ip else "0.0.0.0"
    mid += await has_ssan_zig(len(clean_ip)) + clean_ip.encode()
    if access_token:
        clean_acc = access_token.strip()
        mid += await has_ssan_zig(len(clean_acc)) + clean_acc.encode()
    mid += await has_ssan_zig(len(esh)) + esh
    tg = (await uleb_encode(int(account_id)) + await uleb_encode(int(block_val)) + await uleb_encode(1) + await uleb_encode(int(mode_id)) + await uleb_encode(int(block_val)) + await uleb_encode(int(map_id)) + mid)
    process = await sv_frame(0x5E, match_code, 2, 447, 0, 1, garena420, udp_key)
    loading = await sv_frame(0x5A, match_code, 2, 448, 1, 1, tg, udp_key)
    return process.hex(), loading.hex()
async def play_game(server_ip_port, thunder, sharma, udp_key, match_code,
                    account_id, player_region, client_version, key, iv,
                    match_index, on_match_complete=None):
    t0 = time.time()
    ping_task = move_task = None
    sock = None
    ping_stop = asyncio.Event()
    move_stop = asyncio.Event()
    uid_str = str(account_id); completed = False

    try:
        ip, port = server_ip_port.split(":"); port = int(port)
        rip = await resolve_host_cloudflare(ip)
        loop = asyncio.get_event_loop()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: sock.bind(('0.0.0.0', 0))
        except Exception: pass
        optimize_udp_socket(sock); sock.setblocking(False)
        udp_key_bytes = bytes.fromhex(udp_key)
        server_addr = (rip, port)

        plane = []
        jump_calculated = False
        jump_time_abs = None
        player_state = 21073
        player_x = 1400160
        player_y = 295
        player_z = 0
        player_tick = 860
        player_counter = 6773
        msg_key_counter = 0
        movement_keys = [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]
        idle_sent = False
        jump_sent = False
        parachute_opened = False
        parachute_time = None
        landed = False
        land_time = None
        ground_move_counter = 0
        player_id = None
        land_x = 0
        land_z = 0
        glide_distance = 500000
        last_pos = {"x": player_x, "y": player_y, "z": player_z}
        forced_move_start = None

        await asyncio.sleep(bypass_hello_delay())
        hello = await build_hello_packet(f"{account_id}_2585", udp_key_bytes, match_code)
        await loop.sock_sendto(sock, bytes.fromhex(hello), (rip, port))
        print_success(f"[MATCH #{match_index}] Sent hello_1")

        ack_state = "waiting_for_hello_reply"
        thunder_sent = False; join_match_rcv = False; local_closed = False
        send_lock = asyncio.Lock()
        ping_task = asyncio.create_task(keepalive_ping(sock, rip, port, udp_key_bytes, match_code, ping_stop))
        last_activity = time.time()
        print_colored(f"[MATCH #{match_index}] UDP -> {server_ip_port} (DNS:{rip})", Colors.MAGENTA)

        await squad_sync.mark_match_joined(uid_str)
        await set_match_alive(uid_str, True)

        async def send_move_packet(move_state, x, y, z, phase="game"):
            nonlocal msg_key_counter, player_counter, player_tick, player_id
            msg_key = movement_keys[msg_key_counter % len(movement_keys)]
            msg_key_counter += 1
            move_id = player_id if player_id else account_id
            pkt = build_movement_packet_2001(
                udp_key_bytes, msg_key, player_state,
                int(x), int(y), int(z),
                player_tick, player_counter,
                move_state, move_id, match_code, phase
            )
            await loop.sock_sendto(sock, pkt, server_addr)
            player_counter += 130
            player_tick += 41
            last_pos["x"] = int(x); last_pos["y"] = int(y); last_pos["z"] = int(z)
            move_names = {200:"IDLE", 26:"RUN", 40:"JUMP", 104:"AIR", 132:"PEAK", 136:"LAND", 116:"DROP", 60:"FALL", 82:"PARACHUTE", 20:"LANDED"}
            mn = move_names.get(move_state, str(move_state))
            if move_state != 200 or msg_key_counter % 20 == 0:
                print_success(f"📤 [MOVE] {mn} | ID={move_id} | x={int(x)} y={int(y)} z={int(z)}")
            return pkt

        async def send_startup():
            nonlocal ack_state, thunder_sent
            if thunder_sent: return
            async with send_lock:
                if thunder_sent: return
                try:
                    await loop.sock_sendto(sock, bytes.fromhex(thunder), (rip, port))
                    thunder_sent = True
                    await asyncio.sleep(bypass_jitter(0.08, 0.03))
                    _, nr = await layouts_from_mask(match_code)
                    ack = await build_packet(0x68, nr, 0, 2, None, 1, b"\x01\x00", udp_key_bytes)
                    await loop.sock_sendto(sock, ack, (rip, port))
                    await asyncio.sleep(bypass_jitter(0.15, 0.03))
                    await loop.sock_sendto(sock, bytes.fromhex(sharma), (rip, port))
                    ack_state = "thunder_sharma_sent"
                    print_success(f"[MATCH #{match_index}] Startup delivered")
                except Exception as e:
                    print_error(f"[MATCH #{match_index}] startup: {e}")

        while not local_closed:
            if time.time() - t0 > MAX_MATCH_DURATION:
                print_info(f"[MATCH #{match_index}] duration cap → exit")
                break
            try:
                resp, saddr = await asyncio.wait_for(loop.sock_recvfrom(sock, 65535), timeout=0.5)
                if resp:
                    last_activity = time.time()
                    frame = await decode_packet(resp, udp_key_bytes, match_code)
                    if frame:
                        cmd = frame['cmd']
                        pt = await classify(frame)

                        # ── PLAYER_JOIN ──
                        if cmd == 101 and player_id is None:
                            try:
                                vs = read_varints(frame['content'])
                                if len(vs) >= 3:
                                    player_id = vs[2]
                                    print_success(f"👤 PLAYER_JOIN: UID={vs[0]} | PlayerID={player_id}")
                            except Exception: pass

                        # ── WAITINGPHASE (2038) → IDLE ──
                        if cmd == 2038 and not idle_sent:
                            await send_move_packet(200, player_x, player_y, player_z, phase="arena")
                            idle_sent = True
                            print_success(f"🟢 IDLE sent")

                        # ── Plane points (2001 with vs[1]==2) ──
                        if cmd == 2001:
                            try:
                                vs = read_varints(frame['content'])
                                if len(vs) >= 6 and vs[1] == 2 and 100000 < abs(vs[4]) < 3000000:
                                    rel_time = time.time() - t0
                                    plane.append({'t': rel_time, 'x': vs[3], 'y': vs[4], 'z': vs[5]})
                                    if len(plane) >= 5 and not jump_calculated:
                                        from collections import Counter
                                        y_clusters = Counter(round(p['y'] / 1000) for p in plane)
                                        top_y, cnt = y_clusters.most_common(1)[0]
                                        if cnt >= 3:
                                            psel = [p for p in plane if round(p['y'] / 1000) == top_y]
                                            p0 = psel[0]; p1 = psel[-1]
                                            dt = p1['t'] - p0['t']
                                            dist = ((p1['x'] - p0['x']) ** 2 + (p1['z'] - p0['z']) ** 2) ** 0.5
                                            speed = dist / dt if dt > 0 else 0
                                            dx = p1['x'] - p0['x']; dz = p1['z'] - p0['z']
                                            direction = math.atan2(dz, dx)
                                            land_x = p1['x'] + glide_distance * math.cos(direction + math.pi / 2)
                                            land_z = p1['z'] + glide_distance * math.sin(direction + math.pi / 2)
                                            time_to_jump = glide_distance / speed if speed > 0 else 10.0
                                            jump_time_abs = time.time() + time_to_jump
                                            jump_calculated = True
                                            print_colored(f"🛩️ هبوط=({land_x:.0f},{land_z:.0f}) | قفز بعد {time_to_jump:.1f}s", Colors.CYAN)
                            except Exception: pass

                        if jump_calculated and time.time() >= jump_time_abs and not jump_sent:
                            await send_move_packet(116, land_x, 700000, land_z)
                            jump_sent = True
                            parachute_time = time.time()
                            plane.clear()
                            print_colored("🪂 قفزة!", Colors.RED)l
                        if jump_sent and not parachute_opened and time.time() - parachute_time > 2:
                            await send_move_packet(82, land_x, 500000, land_z)
                            parachute_opened = True
                            print_colored("🪂 مظلة!", Colors.GREEN)

                        if parachute_opened and not landed and time.time() - parachute_time > 8:
                            await send_move_packet(20, land_x, 0, land_z)
                            landed = True
                            land_time = time.time()
                            ground_move_counter = 0
                            print_colored("🏃 هبط!", Colors.GREEN)

                        if landed and time.time() - land_time > 0.3:
                            land_time = time.time()
                            ground_move_counter += 1
                            if ground_move_counter % 5 == 0: move_state = 40; z_off = 0
                            elif ground_move_counter % 5 == 1: move_state = 104; z_off = 50
                            elif ground_move_counter % 5 == 2: move_state = 132; z_off = 100
                            elif ground_move_counter % 5 == 3: move_state = 136; z_off = 0
                            else: move_state = 26; z_off = 0
                            if ground_move_counter % 10 < 5: x_off = ground_move_counter * 100
                            else: x_off = -ground_move_counter * 100
                            await send_move_packet(move_state, land_x + x_off, land_z, z_off)

                        if not landed and not jump_sent and time.time() - t0 > 40:
                            if forced_move_start is None:
                                forced_move_start = time.time()
                                print_warning(f"[MATCH #{match_index}] 🔄 Force move (no plane data)")
                            # Force jump cycle
                            if time.time() - forced_move_start < 0.5:
                                await send_move_packet(116, 100000, 500000, 100000)
                            elif time.time() - forced_move_start < 3.0:
                                await send_move_packet(82, 100000, 300000, 100000)
                            elif time.time() - forced_move_start < 4.0:
                                await send_move_packet(20, 100000, 0, 100000)
                            else:
                                jump_sent = True; parachute_opened = True; landed = True
                                land_time = time.time(); land_x = 100000; land_z = 100000
                                print_success(f"[MATCH #{match_index}] ✅ Forced landed")

                        if cmd in [103, 107]:
                            print_success(f"[MATCH #{match_index}] نهاية الماتش cmd={cmd} for {uid_str}")
                            completed = True
                            local_closed = True
                            await set_match_alive(uid_str, False)
                            await squad_sync.mark_bot_dead(uid_str)
                            continue

                        if cmd == 101:
                            try:
                                _, nr = await layouts_from_mask(match_code)
                                a = await build_packet(0x68, nr, 0, 2, None, 1, b"\x01\x00", udp_key_bytes)
                                await loop.sock_sendto(sock, a, saddr)
                            except Exception: pass
                            continue

                        if pt in ["ACK", "PING", "HELLO", "JOIN_MATCH"]:
                            if pt == "HELLO" and ack_state == "waiting_for_hello_reply":
                                _, r = await reply_for(frame, udp_key_bytes, match_code, ack_style="short")
                                if r: await loop.sock_sendto(sock, r, saddr)
                                ack_state = "ack_sent_waiting"
                            elif pt == "ACK":
                                if ack_state == "waiting_for_hello_reply":
                                    _, r = await reply_for(frame, udp_key_bytes, match_code)
                                    if r: await loop.sock_sendto(sock, r, saddr)
                                    ack_state = "ready_to_send_thunder"
                                elif ack_state == "ack_sent_waiting":
                                    ack_state = "ready_to_send_thunder"
                                else:
                                    _, r = await reply_for(frame, udp_key_bytes, match_code)
                                    if r: await loop.sock_sendto(sock, r, saddr)
                            elif pt == "PING":
                                _, r = await reply_for(frame, udp_key_bytes, match_code)
                                if r: await loop.sock_sendto(sock, r, saddr)
                            elif pt == "JOIN_MATCH" and not join_match_rcv:
                                _, r = await reply_for(frame, udp_key_bytes, match_code)
                                if r: await loop.sock_sendto(sock, r, saddr); join_match_rcv = True
            except asyncio.TimeoutError:
                if ack_state == "ready_to_send_thunder" and not thunder_sent:
                    await send_startup()
                elif ack_state == "waiting_for_hello_reply":
                    if (time.time() - last_activity) > 7.0:
                        try:
                            hp = await build_hello_packet(f"{account_id}_2585", udp_key_bytes, match_code)
                            await loop.sock_sendto(sock, bytes.fromhex(hp), (rip, port))
                        except Exception: pass
                        last_activity = time.time()
                    if (time.time() - t0) > 25.0:
                        print_warning(f"[MATCH #{match_index}] handshake timeout")
                        await set_match_alive(uid_str, False)
                        await squad_sync.mark_bot_dead(uid_str)
                        break
                elif ack_state == "thunder_sharma_sent":
                    if (time.time() - last_activity) > MATCH_IDLE_TIMEOUT:
                        print_info(f"[MATCH #{match_index}] idle {MATCH_IDLE_TIMEOUT}s → exit")
                        completed = True
                        await set_match_alive(uid_str, False)
                        await squad_sync.mark_bot_dead(uid_str)
                        break
                continue
            except BlockingIOError: await asyncio.sleep(0.05)
            except OSError: await asyncio.sleep(0.5); continue
            except Exception: await asyncio.sleep(0.5); continue
            if ack_state == "ready_to_send_thunder" and not thunder_sent:
                try: await send_startup()
                except Exception: passl
        print_info(f"[MATCH #{match_index}] {uid_str} ينتظر باقي السكواد...")
        await squad_sync.wait_for_all_dead()
        print_success(f"[MATCH #{match_index}] كل السكواد كملو!")
        return f"match #{match_index} finished"

    except Exception as e:
        print_error(f"[MATCH #{match_index}] {e}")
        await set_match_alive(uid_str, False)
        await squad_sync.mark_bot_dead(uid_str)
        return f"match #{match_index} error"
    finally:
        if completed:
            try: bot_state.increment_match(uid_str)
            except Exception: pass
            if on_match_complete:
                try: asyncio.create_task(on_match_complete())
                except Exception: pass
        await set_match_alive(uid_str, False)
        await squad_sync.mark_bot_dead(uid_str)
        ping_stop.set()
        if ping_task:
            ping_task.cancel()
            try: await ping_task
            except asyncio.CancelledError: pass
        if sock:
            try: sock.close()
            except Exception: pass
        rem = await _dec_match(uid_str)
        print_info(f"[MATCH #{match_index}] مغلق. UID active: {rem}")
async def functional_battle_royale(addrs, starter_packet, account_region, client_version,
                                    key, iv, account_id="", account_data=None,
                                    account_level=2, max_reconnects=999999):
    global STOP_ALL
    ip, port = addrs.split(":")
    play_matches: List[asyncio.Task] = []
    no_response_count = 0
    uid_str = str(account_id)
    current_key = key; current_iv = iv
    current_account_data = account_data
    current_token = starter_packet
    _writer_ref = {"w": None}
    _team_active = {"flag": True}
    _retry_count = 0
    current_search_region = "ID"

    async def trigger_post_match_refresh():
        await asyncio.sleep(EXP_REFRESH_AFTER_MATCH_DELAY)
        try:
            cd = bot_state.account_credentials.get(uid_str)
            if cd: await refresh_account_profile(cd)
        except Exception: pass

    async def _team_coordinator():
        try:
            deadline = time.time() + TEAM_PEER_WAIT_TIMEOUT
            while time.time() < deadline:
                async with _team_state["lock"]:
                    n = len(_team_state["peers"])
                if n >= TEAM_SIZE: break
                if STOP_ALL: return
                await asyncio.sleep(0.4)

            async with _team_state["lock"]:
                is_leader = (_team_state["leader_uid"] == uid_str)
                peers_snapshot = dict(_team_state["peers"])

            if not is_leader: return

            await squad_sync.begin_team_join(list(peers_snapshot.keys()))
            await asyncio.sleep(TEAM_READY_DELAY)

            own_id_num = current_account_data.get('account_id') if current_account_data else None
            if not own_id_num:
                try: own_id_num = int(uid_str)
                except Exception: own_id_num = 0

            try:
                pkt = create_team(current_key, current_iv, client_version)
                if _writer_ref["w"] and not _writer_ref["w"].is_closing():
                    _writer_ref["w"].write(pkt); await _writer_ref["w"].drain()
                    await _team_member_reset(keep_leader=False)
                    await _team_member_join(uid_str)
            except Exception: pass

            await asyncio.sleep(TEAM_CREATE_WAIT)

            peer_uids = []
            for peer_uid, info in peers_snapshot.items():
                if peer_uid == uid_str: continue
                pa = None
                try: pa = info["data"].get("account_id")
                except Exception: pass
                if not pa: pa = peer_uid
                peer_uids.append(int(pa))

            heartbeat_stop = asyncio.Event()
            async def heartbeat_loop():
                while not heartbeat_stop.is_set():
                    try:
                        if _writer_ref["w"] and not _writer_ref["w"].is_closing():
                            pkt = team_fresh(int(own_id_num), current_key, current_iv)
                            _writer_ref["w"].write(pkt); await _writer_ref["w"].drain()
                    except Exception: pass
                    try: await asyncio.wait_for(heartbeat_stop.wait(), timeout=TEAM_HEARTBEAT_INTERVAL)
                    except asyncio.TimeoutError: pass
            hb_task = asyncio.create_task(heartbeat_loop())

            invite_start = time.time()
            team_joined = False
            while time.time() - invite_start < TEAM_INVITE_MAX_TIME:
                if not _team_active["flag"] or STOP_ALL: break
                cnt = await _team_member_count()
                if cnt >= TEAM_SIZE: team_joined = True; break
                for tuid in peer_uids:
                    async with _team_state["members_lock"]:
                        joined = str(tuid) in _team_state["members"]
                    if joined: continue
                    try:
                        inv = invite_player_in_team(tuid, current_key, current_iv, region=account_region)
                        if _writer_ref["w"] and not _writer_ref["w"].is_closing():
                            _writer_ref["w"].write(inv); await _writer_ref["w"].drain()
                    except Exception: pass
                    await asyncio.sleep(0.4)
                try: await asyncio.wait_for(heartbeat_stop.wait(), timeout=TEAM_INVITE_CYCLE_WAIT)
                except asyncio.TimeoutError: pass

            final_cnt = await _team_member_count()
            print_colored(f"[TEAM] ══ FINAL: {final_cnt}/{TEAM_SIZE} ══", Colors.MAGENTA)

            heartbeat_stop.set()
            try: hb_task.cancel(); await hb_task
            except Exception: pass

            if not team_joined and final_cnt < TEAM_SIZE:
                print_warning(f"[TEAM] فقط {final_cnt}/{TEAM_SIZE} — إعادة")
                return

            await squad_sync.wait_all_team_joined(timeout=TEAM_JOIN_CONFIRM_TIMEOUT)
            await asyncio.sleep(TEAM_FINAL_WAIT)

            while _team_active["flag"] and not STOP_ALL:
                try:
                    active_matches = await _get_match_count(uid_str)
                    if active_matches > 0:
                        await asyncio.sleep(0.8); continue
                    async with _team_state["lock"]:
                        if _team_state["leader_uid"] != uid_str: break
                    oid = current_account_data.get('account_id', own_id_num) if current_account_data else own_id_num
                    try:
                        rdy = ready_for_game(int(oid), current_key, current_iv)
                        if _writer_ref["w"] and not _writer_ref["w"].is_closing():
                            _writer_ref["w"].write(rdy); await _writer_ref["w"].drain()
                    except Exception: pass
                    await asyncio.sleep(0.4)
                    sm = start_match_team(int(oid), current_key, current_iv, region=account_region)
                    if _writer_ref["w"] and not _writer_ref["w"].is_closing():
                        _writer_ref["w"].write(sm); await _writer_ref["w"].drain()
                except Exception: pass
                try: await asyncio.wait_for(asyncio.sleep(START_MATCH_INTERVAL), timeout=START_MATCH_INTERVAL+0.5)
                except asyncio.TimeoutError: pass
        except asyncio.CancelledError: raise
        except Exception as e: print_error(f"[TEAM] coordinator: {e}")

    async def _member_match_trigger():
        try:
            wait_deadline = time.time() + TEAM_JOIN_CONFIRM_TIMEOUT
            while time.time() < wait_deadline:
                async with _team_state["members_lock"]:
                    joined = uid_str in _team_state["members"]
                if joined: break
                if STOP_ALL: return
                await asyncio.sleep(0.3)

            async with _team_state["members_lock"]:
                joined = uid_str in _team_state["members"]
            if not joined:
                return

            await asyncio.sleep(TEAM_MEMBER_START_DELAY)
            async with _team_state["lock"]:
                if _team_state["leader_uid"] == uid_str: return

            my_id = current_account_data.get('account_id', uid_str) if current_account_data else uid_str
            while _team_active["flag"] and not STOP_ALL:
                try:
                    active_matches = await _get_match_count(uid_str)
                    if active_matches > 0:
                        await asyncio.sleep(0.8); continue
                    if _writer_ref["w"] and not _writer_ref["w"].is_closing():
                        try:
                            rdy = ready_for_game(int(my_id), current_key, current_iv)
                            _writer_ref["w"].write(rdy); await _writer_ref["w"].drain()
                        except Exception: pass
                        await asyncio.sleep(0.4)
                        sm = start_match_team(int(my_id), current_key, current_iv, region=account_region)
                        _writer_ref["w"].write(sm); await _writer_ref["w"].drain()
                except Exception: pass
                try: await asyncio.wait_for(asyncio.sleep(START_MATCH_INTERVAL), timeout=START_MATCH_INTERVAL+0.5)
                except asyncio.TimeoutError: pass
        except asyncio.CancelledError: raise
        except Exception: pass

    while not STOP_ALL:
        writer = None
        gateway_ping_task = None
        team_coord_task = None
        member_trigger_task = None
        try:
            _retry_count += 1
            if current_account_data:
                fresh = None
                if current_account_data.get('auth_type') == 'guest' and current_account_data.get('auth_uid'):
                    fresh = cache_get(str(current_account_data['auth_uid']))
                elif current_account_data.get('auth_type') == 'token' and current_account_data.get('auth_token'):
                    fresh = cache_get(f"tok_{current_account_data['auth_token'][:20]}")
                if fresh:
                    current_account_data = fresh
                    current_key = fresh['aes_ak']; current_iv = fresh['iv_i']
                    current_token = await build_tcp_startup_packet(fresh['account_id'], fresh['token'], fresh['server_time'], current_key, current_iv, region=fresh.get('region', account_region), typ='OnLine')
                else:
                    current_token = await build_tcp_startup_packet(current_account_data['account_id'], current_account_data['token'], current_account_data['server_time'], current_key, current_iv, region=current_account_data.get('region', account_region), typ='OnLine')

            rip = await resolve_host_cloudflare(ip)
            reader, writer = await asyncio.open_connection(rip, int(port))
            _writer_ref["w"] = writer
            raw_sock = writer.get_extra_info('socket')
            if raw_sock: optimize_tcp_socket(raw_sock)

            await asyncio.sleep(bypass_hello_delay())
            writer.write(bytes.fromhex(current_token)); await writer.drain()

            async def func_gateway_keepalive():
                ka_bytes = await send_keep_alive(account_region)
                while True:
                    await asyncio.sleep(3.0)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(ka_bytes); await writer.drain()
                    except Exception: break
            gateway_ping_task = asyncio.create_task(func_gateway_keepalive())

            print_success(f"[FUNC] TCP متصل {uid_str} (DNS:{rip}) #محاولة {_retry_count}")

            async with _team_state["lock"]:
                _team_state["peers"][uid_str] = {"writer": writer, "data": current_account_data, "key": current_key, "iv": current_iv}
                if _team_state["leader_uid"] is None or _team_state["leader_uid"] not in _team_state["peers"]:
                    _team_state["leader_uid"] = list(_team_state["peers"].keys())[0]
                    print_success(f"[TEAM] 👑 القائد: {_team_state['leader_uid']}")

            if TEAM_MODE:
                team_coord_task = asyncio.create_task(_team_coordinator())
                member_trigger_task = asyncio.create_task(_member_match_trigger())
            else:
                await start_game_battle_royale(current_search_region, client_version, writer, current_key, current_iv)

            while True:
                if STOP_ALL: break
                play_matches[:] = [m for m in play_matches if not m.done()]
                active = await _get_match_count(uid_str)
                try: bot_state.update_status(uid_str, "ONLINE" if active == 0 else "IN_MATCH", active)
                except Exception: pass

                try:
                    data = await asyncio.wait_for(reader.read(8192), timeout=0.5)
                except asyncio.TimeoutError:
                    no_response_count += 1
                    if no_response_count % 240 == 0:
                        print_info(f"[FUNC] {uid_str} idle {no_response_count//2}s")
                    continue
                if not data: raise ConnectionError("TCP مغلق من السيرفر")
                hex_data = data.hex(); pl = len(data)
                no_response_count = 0

                if hex_data.startswith("0600") and pl > 20:
                    await _process_social_packet(data, current_account_data, tag="MAIN")
                    continue

                if hex_data.startswith("05") and pl > 10:
                    await _handle_team_invite(hex_data, pl, uid_str, current_account_data, current_key, current_iv, writer)
                    continue

                if hex_data.startswith("0300") and pl >= 300:
                    print_colored("=" * 60, Colors.GREEN)
                    print_colored("MATCH FOUND! Loading...", Colors.GREEN)
                    print_colored("=" * 60, Colors.GREEN)

                    for tk in (team_coord_task, member_trigger_task):
                        if tk and not tk.done():
                            tk.cancel()
                            try: await tk
                            except asyncio.CancelledError: pass
                    team_coord_task = None; member_trigger_task = None
                    _team_active["flag"] = False

                    try:
                        res = json.loads(await decode_protobuf(hex_data[10:]))
                        token = udp_key = match_code = server_ip_port = None
                        match_account_id = block_val = None
                        if '42' in res and 'data' in res['42']: match_code = res['42']['data']
                        if '5' in res and 'data' in res['5']:
                            r5 = res['5']['data']
                            server_ip_port = r5.get('2', {}).get('data')
                            udp_key = r5.get('3', {}).get('data')
                            token = r5.get('4', {}).get('data')
                            if '42' in r5: match_code = r5['42']['data']
                        if '1' in res and 'data' in res['1']: match_account_id = res['1']['data']
                        if '5' in res and 'data' in res['5']: block_val = res['5']['data'].get('1', {}).get('data')

                        effective = match_account_id or account_id or "BD_BOT"
                        if token and udp_key and match_code and server_ip_port:
                            async with _team_state["lock"]: all_peers = list(_team_state["peers"].keys())
                            if all_peers:
                                await squad_sync.reset_all()
                                await squad_sync.begin_match_join(all_peers)

                            acc_tok = current_account_data.get('access_token', '') if current_account_data else ""
                            thunder, sharma = await build_match_startup_packets(token, udp_key, match_code, effective, block_val or 0, server_ip=server_ip_port, region=account_region, client_version=client_version, access_token=acc_tok, mode_id=BR_MODE_ID, map_id=BR_MAP_ID)
                            match_index = await _inc_match(uid_str)

                            new_match = asyncio.create_task(play_game(server_ip_port, thunder, sharma, udp_key, match_code, effective, current_search_region, client_version, current_key, current_iv, match_index=match_index, on_match_complete=trigger_post_match_refresh))
                            play_matches.append(new_match)

                            async def drain_gw():
                                while not new_match.done():
                                    try:
                                        dg = await asyncio.wait_for(reader.read(4096), timeout=1.0)
                                        if not dg: break
                                    except asyncio.TimeoutError: continue
                                    except Exception: break
                            drain_task = asyncio.create_task(drain_gw())
                            try: await new_match
                            except Exception as e: print_error(f"[MATCH #{match_index}] {e}")
                            finally:
                                drain_task.cancel()
                                try: await drain_task
                                except asyncio.CancelledError: pass
                            play_matches[:] = [m for m in play_matches if not m.done()]

                            async with _team_state["lock"]:
                                _team_state["peers"].pop(uid_str, None)
                                if _team_state["leader_uid"] == uid_str: _team_state["leader_uid"] = None
                            await _team_member_leave(uid_str)

                            try:
                                if writer and not writer.is_closing():
                                    writer.close(); await writer.wait_closed()
                            except Exception: pass

                            _team_active["flag"] = True
                            print_info(f"[RESTART] {NEW_MATCH_DELAY}s ثم سكواد جديد...")
                            await asyncio.sleep(NEW_MATCH_DELAY)
                            print_success(f"[RESTART] ♻️  بدء دورة جديدة لـ {uid_str}")
                            break
                    except Exception as e:
                        print_error(f"[FUNC] Match parse error: {e}")
                        break

        except asyncio.CancelledError:
            if gateway_ping_task: gateway_ping_task.cancel()
            async with _team_state["lock"]:
                _team_state["peers"].pop(uid_str, None)
                if _team_state["leader_uid"] == uid_str: _team_state["leader_uid"] = None
            await _team_member_leave(uid_str)
            raise
        except Exception as e:
            if gateway_ping_task: gateway_ping_task.cancel()
            print_error(f"[FUNC] {uid_str}: {e} — إعادة بعد 1s")
            if writer:
                try: writer.close(); await writer.wait_closed()
                except Exception: pass
            await asyncio.sleep(1.0)
        finally:
            _team_active["flag"] = False
            for tk in (team_coord_task, member_trigger_task):
                if tk and not tk.done():
                    tk.cancel()
                    try: await tk
                    except Exception: pass
            if gateway_ping_task: gateway_ping_task.cancel()
            if writer:
                try: writer.close(); await writer.wait_closed()
                except Exception: pass
            async with _team_state["lock"]:
                _team_state["peers"].pop(uid_str, None)
                if _team_state["leader_uid"] == uid_str: _team_state["leader_uid"] = None
            await _team_member_leave(uid_str)
            _team_active["flag"] = True

            if STOP_ALL: return
async def _process_social_packet(raw_bytes, account_data, tag="MAIN"):
    try:
        hex_data = raw_bytes.hex()
        candidates = []
        if len(raw_bytes) >= 6:
            plen = raw_bytes[4]
            if 0 < plen <= (len(raw_bytes) - 5):
                try:
                    inner = bytes(raw_bytes[5:5+plen])
                    d0 = decode_protobuf_dict_safe(inner) or _wrap_manual(inner)
                    if d0: candidates.append((5, d0))
                except Exception: pass
        for off in [5,6,10,8,12,4,0]:
            if off >= len(hex_data): continue
            try: inner = bytes.fromhex(hex_data[off:])
            except Exception: continue
            decoded = decode_protobuf_dict_safe(inner) or _wrap_manual(inner)
            if decoded: candidates.append((off, decoded))
        if not candidates: return
        candidates.sort(key=lambda x: len(x[1]) if isinstance(x[1], dict) else 0, reverse=True)
        best_off, decoded = candidates[0]
        def _v(c, k):
            if not isinstance(c, dict): return None
            v = c.get(k) if k in c else c.get(str(k))
            if isinstance(v, dict) and "data" in v: return v["data"]
            return v
        f5w = decoded.get("5") or decoded.get(5) if isinstance(decoded, dict) else None
        f5 = f5w["data"] if isinstance(f5w, dict) and "data" in f5w else f5w
        target = None
        if isinstance(f5, dict):
            for fk in [1,2,3,4,6]:
                c = _v(f5, fk)
                if c and str(c).isdigit() and 6 <= len(str(c)) <= 15:
                    target = str(c); break
        if not target: return
        own = str(account_data.get('account_id', '')) if account_data else ''
        if own and target == own: return
        if not _accept_friend_request or not account_data: return
        jwt = account_data.get('token'); srv = account_data.get('server_url')
        rel = account_data.get('release_version'); own_id = account_data.get('account_id')
        if not (jwt and srv and rel and own_id): return
        url = f"{srv.rstrip('/')}/ConfirmFriendRequest"
        fields = {"1": int(target), "2": int(own_id)}
        try:
            payload = bytes.fromhex(encrypt_api(create_proto(fields).hex()))
            hdrs = {"authorization": f"Bearer {jwt}", "host": srv.replace("https://","").replace("http://","").split("/")[0], "x-ga": "v1 1", "content-type": "application/x-www-form-urlencoded", "accept-encoding": "deflate, gzip", "releaseversion": f"{rel}", "user-agent": "UnityPlayer/2022.3.47f1", "accept": "*/*", "x-unity-version": "2022.3.47f1"}
            async with httpx.AsyncClient(verify=False, timeout=8.0) as s:
                r = await s.post(url, headers=hdrs, content=payload)
                if r.status_code == 200 and len(r.content) > 0:
                    print_success(f"[FRIEND-{tag}] ✅ {target}")
        except Exception: pass
    except Exception: pass

def _wrap_manual(inner):
    try:
        alt = _decode_proto_manual(inner)
        if alt and len(alt) > 0: return {str(k): {"data": v} for k, v in alt.items()}
    except Exception: pass
    return None

async def _handle_team_invite(hex_data, pl, uid_str, current_account_data, current_key, current_iv, writer):
    try:
        candidates = []
        for off in [10,8,6,12,14,4,16,0,20,2]:
            if off >= len(hex_data) or len(hex_data) - off < 4: continue
            try: inner = bytes.fromhex(hex_data[off:])
            except Exception: continue
            dec = decode_protobuf_dict_safe(inner)
            if dec and isinstance(dec, dict) and len(dec) > 0:
                candidates.append((off, "parser", dec)); continue
            alt = _decode_proto_manual(inner)
            if alt and len(alt) > 0:
                candidates.append((off, "manual", {str(k): {"data": v} for k, v in alt.items()}))
        if not candidates: return False
        candidates.sort(key=lambda x: len(x[2]) if isinstance(x[2], dict) else 0, reverse=True)
        best_off, decoder, dec = candidates[0]

        def _unwrap(d, keys):
            if not isinstance(d, dict): return None
            for k in keys:
                v = d.get(k) if k in d else d.get(str(k))
                if isinstance(v, dict) and "data" in v: return v["data"]
                if isinstance(v, dict): return v
            return None
        target_dict = None
        for kp in [["5"],["4"],["6"],["2"],["1"]]:
            u = _unwrap(dec, kp)
            if isinstance(u, dict) and len(u) >= 3: target_dict = u; break
        if target_dict is None: target_dict = dec

        def _g(d, k):
            if not isinstance(d, dict): return None
            v = d.get(k) if k in d else d.get(str(k))
            if isinstance(v, dict) and "data" in v: return v["data"]
            if isinstance(v, dict):
                for kk in ["1","2","3","4","5","6","7","8"]:
                    vv = v.get(kk) if kk in v else v.get(int(kk))
                    if isinstance(vv, dict) and "data" in vv: return vv["data"]
            return v

        group_id = None
        for k in list(target_dict.keys()):
            c = _g(target_dict, k)
            if isinstance(c, str) and 20 <= len(c) <= 40: group_id = c; break
        if not group_id:
            for k in list(dec.keys()):
                c = _g(dec, k)
                if isinstance(c, str) and 20 <= len(c) <= 40: group_id = c; break

        own_acc = str(current_account_data.get('account_id')) if current_account_data else None
        inviter = None
        all_f = list(target_dict.keys()) + list(dec.keys())
        for k in all_f:
            c = _g(target_dict, k) or _g(dec, k)
            if c and str(c).isdigit() and 6 <= len(str(c)) <= 15:
                if str(c) != uid_str and str(c) != own_acc:
                    inviter = str(c); break

        is_member = (_team_state["leader_uid"] != uid_str)
        if inviter and group_id and is_member:
            async with _team_state["members_lock"]:
                already = uid_str in _team_state["members"]
            if already: return True
            accepted = False
            for attempt in range(3):
                try:
                    acc = accept_team_invite(int(inviter), group_id, current_key, current_iv)
                    if writer and not writer.is_closing():
                        writer.write(acc); await writer.drain()
                        accepted = True; break
                except Exception: pass
                await asyncio.sleep(0.4)
            if accepted: await _team_member_join(uid_str)
            return True
        return False
    except Exception: return False
async def informational(addrs, starter_packet, key, iv, region="ID", max_reconnects=999999):
    ip, port = addrs.split(":")
    while not STOP_ALL:
        writer = None; ping_task = None
        try:
            rip = await resolve_host_cloudflare(ip)
            reader, writer = await asyncio.open_connection(rip, int(port))
            rs = writer.get_extra_info('socket')
            if rs: optimize_tcp_socket(rs)
            writer.write(bytes.fromhex(starter_packet)); await writer.drain()
            async def info_ka():
                ka = await send_keep_alive(region)
                while True:
                    await asyncio.sleep(2.5)
                    try:
                        if writer and not writer.is_closing():
                            writer.write(ka); await writer.drain()
                    except Exception: break
            ping_task = asyncio.create_task(info_ka())
            while True:
                data = await reader.read(8192)
                if not data: raise ConnectionError("closed")
        except asyncio.CancelledError:
            if ping_task: ping_task.cancel()
            if writer:
                try: writer.close(); await writer.wait_closed()
                except Exception: pass
            raise
        except Exception:
            if ping_task: ping_task.cancel()
            if writer:
                try: writer.close(); await writer.wait_closed()
                except Exception: pass
            await asyncio.sleep(1.5)l
def _register_credentials(ad):
    try:
        acc_id = str(ad['account_id'])
        bot_state.account_credentials[acc_id] = ad
        if ad.get('auth_uid'): bot_state.account_credentials[str(ad['auth_uid'])] = ad
        if ad.get('auth_token'): bot_state.account_credentials[f"tok_{ad['auth_token'][:20]}"] = ad
    except Exception: pass

async def refresh_account_profile(ad_or_uid):
    try:
        if isinstance(ad_or_uid, str):
            uid = str(ad_or_uid); ad = bot_state.account_credentials.get(uid)
        else:
            ad = ad_or_uid; uid = str(ad.get('account_id')) if ad else "?"
        if not ad: return
        url = ad.get('server_url'); token = ad.get('token')
        rel = ad.get('release_version'); payload = ad.get('login_payload_data')
        if not (url and token and rel and payload): return
        res = await send_getlogin(payload, url, token, rel)
        if not res: return
        rp, dd = res
        def _si(v, d):
            try:
                if v is None or v == "": return d
                return int(v)
            except Exception: return d
        level = _si(get_proto_field(dd, 6, None), None)
        exp = _si(get_proto_field(dd, 7, None), None)
        likes = _si(get_proto_field(dd, 8, None), None)
        try: nick = rp.nickname or get_proto_field(dd, 4, "") or ""
        except Exception: nick = ""
        if level is None and exp is None: return
        level = level if level is not None else 1
        exp = exp if exp is not None else 0
        likes = likes if likes is not None else 0
        acc_id = str(ad['account_id'])
        try: bot_state.update_exp(acc_id, exp, level)
        except Exception: pass
        if likes > 0 and acc_id in bot_state.accounts: bot_state.accounts[acc_id]["likes"] = likes
        if nick and acc_id in bot_state.accounts: bot_state.accounts[acc_id]["nickname"] = nick
        _update_cache_profile(ad, level, exp)
        ad['level'] = level; ad['exp'] = exp
        if likes > 0: ad['likes'] = likes
        if nick: ad['nickname'] = nick
    except Exception: pass

async def process_account_uid_pass(uid, password):
    cached = cache_get(uid)
    if cached:
        print_success(f"[CACHE] {uid}")
        acc_id = str(cached['account_id'])
        try: bot_state.register_account(uid=acc_id, nickname=cached.get('nickname', f"Player_{acc_id}"), region=cached.get('region', 'ID'), level=cached.get('level', 1), exp=cached.get('exp', 0), likes=cached.get('likes', 0))
        except Exception: pass
        _register_credentials(cached); return cached
    print_info(f"[LOGIN] UID {uid}...")
    try:
        vc = await version_config()
        if not vc: return None
        rel, cv, su = vc
        tg = await get_access_token(uid, password)
        if not tg: return None
        oid, at, pf = tg
        dev = get_device_for_account(uid)
        lpd = await build_majorlogin_payload(oid, at, pf, cv, dev)
        if not lpd: return None
        mresp = await send_majorlogin(lpd, rel, su)
        if mresp is None: return None
        gl = await send_getlogin(lpd, mresp.url, mresp.token, rel)
        if gl is None: return None
        rp, dd = gl
        acc_id = str(mresp.account_id)
        level = int(get_proto_field(dd, 6, 1) or 1)
        exp = int(get_proto_field(dd, 7, 0) or 0)
        likes = int(get_proto_field(dd, 8, 0) or 0)
        nick = rp.nickname or get_proto_field(dd, 4, f"Player_{acc_id}")
        region = mresp.region or get_proto_field(dd, 3, "ID")
        try: bot_state.register_account(uid=acc_id, nickname=nick, region=region, level=level, exp=exp, likes=likes)
        except Exception: pass
        print_success(f"[OK] {acc_id} | {nick} | Lvl{level}")
        ad = {'account_id': mresp.account_id, 'nickname': nick, 'region': region, 'level': level, 'exp': exp, 'likes': likes, 'open_id': oid, 'access_token': at, 'platform': str(pf), 'token': mresp.token, 'server_time': mresp.server_time, 'aes_ak': mresp.aes_ak, 'iv_i': mresp.iv_i, 'functional_addrs': rp.functional_addrs or get_proto_field(dd, 14), 'informational_addrs': rp.informational_addrs or get_proto_field(dd, 32), 'release_version': rel, 'client_version': cv, 'server_url': mresp.url, 'login_payload_data': lpd, 'auth_type': 'guest', 'auth_uid': uid, 'auth_password': password}
        _register_credentials(ad); cache_set(uid, ad); return ad
    except Exception as e:
        print_error(f"process_account_uid_pass: {e}"); return None

async def process_account_token(access_token):
    cache_key = f"tok_{access_token[:20]}"
    cached = cache_get(cache_key)
    if cached:
        acc_id = str(cached['account_id'])
        try: bot_state.register_account(uid=acc_id, nickname=cached.get('nickname', f"Player_{acc_id}"), region=cached.get('region', 'ID'), level=cached.get('level', 1), exp=cached.get('exp', 0), likes=cached.get('likes', 0))
        except Exception: pass
        _register_credentials(cached); return cached
    print_info("[LOGIN] Token...")
    try:
        vc = await version_config()
        if not vc: return None
        rel, cv, su = vc
        import requests
        url = f"https://100067.connect.garena.com/oauth/token/inspect?token={access_token}"
        hdrs = {"User-Agent": "GarenaMSDK/4.0.19P4(G011A ;Android 9;en;US;)"}
        resp = await asyncio.to_thread(requests.get, url, headers=hdrs, timeout=10)
        d = resp.json()
        if 'error' in d: return None
        oid = d.get('open_id'); pf = d.get('platform', 4)
        if not oid: return None
        dev = get_device_for_account(oid)
        lpd = await build_majorlogin_payload(oid, access_token, str(pf), cv, dev)
        if not lpd: return None
        mresp = await send_majorlogin(lpd, rel, su)
        if mresp is None: return None
        gl = await send_getlogin(lpd, mresp.url, mresp.token, rel)
        if gl is None: return None
        rp, dd = gl
        acc_id = str(mresp.account_id)
        level = int(get_proto_field(dd, 6, 1) or 1); exp = int(get_proto_field(dd, 7, 0) or 0); likes = int(get_proto_field(dd, 8, 0) or 0)
        nick = rp.nickname or get_proto_field(dd, 4, f"Player_{acc_id}")
        region = mresp.region or get_proto_field(dd, 3, "ID")
        try: bot_state.register_account(uid=acc_id, nickname=nick, region=region, level=level, exp=exp, likes=likes)
        except Exception: pass
        ad = {'account_id': mresp.account_id, 'nickname': nick, 'region': region, 'level': level, 'exp': exp, 'likes': likes, 'open_id': oid, 'access_token': access_token, 'platform': str(pf), 'token': mresp.token, 'server_time': mresp.server_time, 'aes_ak': mresp.aes_ak, 'iv_i': mresp.iv_i, 'functional_addrs': rp.functional_addrs or get_proto_field(dd, 14), 'informational_addrs': rp.informational_addrs or get_proto_field(dd, 32), 'release_version': rel, 'client_version': cv, 'server_url': mresp.url, 'login_payload_data': lpd, 'auth_type': 'token', 'auth_token': access_token}
        _register_credentials(ad); cache_set(cache_key, ad); return ad
    except Exception as e:
        print_error(f"process_account_token: {e}"); return None

async def run_account_worker(ad, label):
    acc_id = str(ad['account_id'])
    info_task = None; exp_task = None
    try:
        reg = ad.get('region', 'ID')
        tcp_online = await build_tcp_startup_packet(ad['account_id'], ad['token'], ad['server_time'], ad['aes_ak'], ad['iv_i'], region=reg, typ='OnLine')
        tcp_chat = await build_tcp_startup_packet(ad['account_id'], ad['token'], ad['server_time'], ad['aes_ak'], ad['iv_i'], region=reg, typ='ChaT')
        info_task = asyncio.create_task(informational(ad['informational_addrs'], tcp_chat, ad['aes_ak'], ad['iv_i'], region=reg))
        async def exp_refresher():
            try:
                f = bot_state.account_credentials.get(acc_id)
                if f: await refresh_account_profile(f)
            except Exception: pass
            while not STOP_ALL:
                await asyncio.sleep(EXP_REFRESH_INTERVAL + random.uniform(-3.0, 3.0))
                try:
                    f = bot_state.account_credentials.get(acc_id)
                    if f: await refresh_account_profile(f)
                except Exception: pass
        exp_task = asyncio.create_task(exp_refresher())
        await functional_battle_royale(ad['functional_addrs'], tcp_online, ad['region'], ad['client_version'], ad['aes_ak'], ad['iv_i'], account_id=acc_id, account_data=ad, account_level=int(ad.get('level', 2) or 2))
    except asyncio.CancelledError: raise
    except Exception as e: print_error(f"run_account_worker {label}: {e}")
    finally:
        for t in (info_task, exp_task):
            if t and not t.done(): t.cancel()
        for t in (info_task, exp_task):
            if t:
                try: await t
                except Exception: pass

async def account_loop_guest(uid, password):
    while not STOP_ALL:
        try:
            print_info(f"[LOGIN] Guest {uid}...")
            try: bot_state.update_status(str(uid), "CONNECTING")
            except Exception: pass
            ad = await process_account_uid_pass(uid, password)
            if not ad:
                print_error(f"فشل تسجيل {uid}, بعد 10s")
                try: bot_state.update_status(str(uid), "ERROR")
                except Exception: pass
                await asyncio.sleep(10); continue
            await run_account_worker(ad, uid)
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            try: bot_state.update_status(str(uid), "OFFLINE")
            except Exception: pass
            break
        except Exception as e:
            print_error(f"خطأ {uid}: {e}, بعد 5s")
            await asyncio.sleep(5)

async def account_loop_token(token):
    while not STOP_ALL:
        try:
            ad = await process_account_token(token)
            if not ad:
                print_error("فشل token, بعد 10s")
                await asyncio.sleep(10); continue
            acc_id = str(ad['account_id'])
            await run_account_worker(ad, acc_id)
            await asyncio.sleep(1)
        except asyncio.CancelledError: break
        except Exception as e:
            print_error(f"Token خطأ: {e}, بعد 5s")
            await asyncio.sleep(5)

def load_accounts():
    accounts = []
    if os.path.exists(ACCOUNTS_FILE):
        try:
            with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list): accounts = data
        except Exception: pass
    if not accounts and FALLBACK_UID and FALLBACK_PASSWORD:
        accounts.append({"uid": FALLBACK_UID, "password": FALLBACK_PASSWORD})
    return accounts

async def main():
    global STOP_ALL
    print_colored("=" * 60, Colors.CYAN)
    print_colored("  TEAM RBC — Squad Bot (Plane + Movement)", Colors.GREEN)
    print_colored("=" * 60, Colors.CYAN)
    print_success("✅ حالة اللعب الكاملة: طيارة → قفزة → مظلة → هبوط → جري")
    print_success("✅ Fallback: بعد 40s بلا plane → تحرك بالقوة")
    print_success("✅ كل بوت يكمل ماتشو، يستنى الباقي، ثم يعاودو سكواد")
    print_success("✅ بدون إطلاق نار")
    print_colored("=" * 60, Colors.CYAN)

    if HAS_DASHBOARD:
        try:
            await start_web_dashboard(host=WEB_HOST, port=WEB_PORT)
            print_success(f"Dashboard: http://localhost:{WEB_PORT}")
        except Exception as e:
            print_error(f"Dashboard: {e}")

    async def on_account_added(data):
        if "token" in data and data["token"]:
            t = str(data["token"]).strip()
            task = asyncio.create_task(account_loop_token(t))
            try: bot_state.account_workers[t[:10]] = task
            except Exception: pass
        elif "uid" in data and "password" in data:
            u = str(data["uid"]).strip(); p = str(data["password"]).strip()
            task = asyncio.create_task(account_loop_guest(u, p))
            try: bot_state.account_workers[u] = task
            except Exception: pass

    async def on_refresh_account(uid):
        await refresh_account_profile(uid)

    try:
        bot_state.refresh_callbacks["on_account_added"] = on_account_added
        bot_state.refresh_callbacks["on_refresh_account"] = on_refresh_account
    except Exception: pass

    accounts = load_accounts()
    if not accounts:
        print_warning(f"لا حسابات في {ACCOUNTS_FILE}")
    for acc in accounts:
        if acc.get("token"):
            t = asyncio.create_task(account_loop_token(acc["token"]))
            try: bot_state.account_workers[acc["token"][:10]] = t
            except Exception: pass
        elif acc.get("uid") and acc.get("password"):
            u = str(acc["uid"])
            t = asyncio.create_task(account_loop_guest(u, acc["password"]))
            try: bot_state.account_workers[u] = t
            except Exception: pass

    try:
        while True:
            if STOP_ALL:
                for t in list(bot_state.account_workers.values()):
                    if not t.done(): t.cancel()
                await asyncio.gather(*bot_state.account_workers.values(), return_exceptions=True)
                return
            await asyncio.sleep(1)
    except (KeyboardInterrupt, asyncio.CancelledError):
        for t in list(bot_state.account_workers.values()):
            if not t.done(): t.cancel()
        await asyncio.gather(*bot_state.account_workers.values(), return_exceptions=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print_warning("stopped")