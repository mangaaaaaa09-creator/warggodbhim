# -*- coding: utf-8 -*-
import os
import sys
import time
import base64
import random
import json
import codecs
import signal
import threading
import argparse
import requests
import hmac
import hashlib
import re
import string
import binascii
from datetime import datetime
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import urllib3
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
EXIT = False
SUCCESS_COUNT = 0
BIO_SET_COUNTER = 0
TARGET_COUNT = 0
LOCK = threading.Lock()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_FILE = os.path.join(BASE_DIR, "accounts.json")

RELEASE_VERSION = "OB55"
USER_AGENT_MODEL = "ASUS_Z01QD"
API_HEX_KEY = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
API_SECRET_KEY = "2ee44819e9b4598845141067b281621874d0d5d7af9d8f7e00c1e54715b7d1e3"
AES_KEY_G = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV_G = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

REGION_LANG = {
    "BD": "bn", "IND": "hi", "PK": "ur", "SG": "en", "ID": "id",
    "ME": "ar", "VN": "vi", "TW": "zh", "CIS": "ru", "TH": "th",
    "EU": "en", "US": "en", "SAC": "es", "LK": "en"
}

BIO_TEXT = "[B][C][00FFFF] [b][c]f f g l o r y b o t ==> W A R G O OD "
_sym_db = _symbol_database.Default()
DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\ndata.proto\"\xbb\x01\n\x04\x44\x61ta\x12\x0f\n\x07\x66ield_2\x18\x02 \x01(\x05\x12\x1e\n\x07\x66ield_5\x18\x05 \x01(\x0b\x32\r.EmptyMessage\x12\x1e\n\x07\x66ield_6\x18\x06 \x01(\x0b\x32\r.EmptyMessage\x12\x0f\n\x07\x66ield_8\x18\x08 \x01(\t\x12\x0f\n\x07\x66ield_9\x18\t \x01(\x05\x12\x1f\n\x08\x66ield_11\x18\x0b \x01(\x0b\x32\r.EmptyMessage\x12\x1f\n\x08\x66ield_12\x18\x0c \x01(\x0b\x32\r.EmptyMessage\"\x0e\n\x0c\x45mptyMessageb\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'data_pb2', _globals)

if _descriptor._USE_C_DESCRIPTORS == False:
    DESCRIPTOR._options = None
    _globals['_DATA']._serialized_start = 15
    _globals['_DATA']._serialized_end = 202
    _globals['_EMPTYMESSAGE']._serialized_start = 204
    _globals['_EMPTYMESSAGE']._serialized_end = 218

Data = _sym_db.GetSymbol('Data')
EmptyMessage = _sym_db.GetSymbol('EmptyMessage')
IP_ROTATION = {
    'counter': 0,
    'lock': threading.Lock()
}

PROXY_LIST = []

DATADOME_CID = "FWTNdJThVpQebS2UwFDDVuTDUrooDRONkwc3RotkozZEl36Ud9amFYFASlPQMF~5P0rgDg1HOU~kVRzCxF6SzKLxq~n1woK49aR5JKDK6WeO1sPcQ1W41MJLWf0MurjT"
DATADOME_DDK = "AE3F04AD3F0D3A462481A337485081"
def safe_exit(signum=None, frame=None):
    global EXIT
    EXIT = True
    sys.exit(0)


signal.signal(signal.SIGINT, safe_exit)
signal.signal(signal.SIGTERM, safe_exit)

def encode_varint(n):
    if n < 0: return b''
    result = []
    while True:
        byte = n & 0x7F
        n >>= 7
        if n:
            byte |= 0x80
        result.append(byte)
        if not n:
            break
    return bytes(result)


def create_proto_field(field_num, value):
    if isinstance(value, int):
        return encode_varint((field_num << 3) | 0) + encode_varint(value)
    elif isinstance(value, (str, bytes)):
        encoded_val = value.encode() if isinstance(value, str) else value
        return encode_varint((field_num << 3) | 2) + encode_varint(len(encoded_val)) + encoded_val
    return b''


def build_proto(fields):
    return b''.join(create_proto_field(k, v) for k, v in fields.items())


def encrypt_api(plain_hex):
    cipher = AES.new(AES_KEY_G, AES.MODE_CBC, AES_IV_G)
    return cipher.encrypt(pad(bytes.fromhex(plain_hex), AES.block_size)).hex()
def save_account_to_json(account_data):
    try:
        with LOCK:
            if os.path.exists(ACCOUNTS_FILE):
                with open(ACCOUNTS_FILE, 'r', encoding='utf-8') as f:
                    try:
                        accounts = json.load(f)
                        if not isinstance(accounts, list):
                            accounts = []
                    except:
                        accounts = []
            else:
                accounts = []

            simplified_data = {
                "uid": account_data["uid"],
                "password": account_data["password"],
                "account_id": account_data["account_id"],
                "name": account_data["name"],
                "region": account_data["region"],
                "date_created": account_data["date_created"]
            }
            accounts.append(simplified_data)

            tmp = ACCOUNTS_FILE + ".tmp"
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(accounts, f, indent=2, ensure_ascii=False)
            os.replace(tmp, ACCOUNTS_FILE)
    except Exception as e:
        print(f"[SAVE-ERR] {e}")

def generate_password():
    return f"BLRX-HELLO{''.join(random.choices(string.ascii_uppercase + string.digits, k=6))}"

def get_datadome_cookie():
    try:
        url = "https://api-sdk.datadome.co/sdk/"
        payload = {
            'cid': DATADOME_CID,
            'ddv': "1.13.9",
            'ddvc': "4.0.42",
            'ddk': DATADOME_DDK,
            'request': "https://100067.connect.garena.com/api/v2/oauth/guest:register",
            'os': "Android",
            'osr': "15",
            'osn': "VANILLA_ICE_CREAM",
            'osv': "35",
            'ua': "GarenaMSDK/4.0.42(25028RN03A ;Android 15;ar;EG;app 1.128.2 2019120828;)",
            'screen_x': "1640",
            'screen_y': "720",
            'screen_d': "320",
            'events': "[{\"id\":1, \"message\":\"response validation\", \"source\":\"sdk\", \"date\":" + str(int(time.time() * 1000)) + "}]",
            'camera': "{\"auth\":\"false\", \"info\":\"{}\"}",
            'mdl': "25028RN03A",
            'prd': "serenity_global",
            'mnf': "Xiaomi",
            'dev': "serenity",
            'hrd': "serenity",
            'fgp': "Redmi/serenity_global/serenity:15/AP3A.240905.015.A2/A15.0.26.0.VGWMIXM:user/release-keys",
            'tgs': "release-keys",
            'inte': "android-java-okhttp"
        }
        headers = {
            'User-Agent': "okhttp/4.12.0",
            'Accept-Encoding': "gzip"
        }
        response = requests.post(url, data=payload, headers=headers, timeout=10, verify=False)
        try:
            js = response.json()
            cookie_str = js.get("cookie", "")
            match = re.search(r'datadome=([^;]+)', cookie_str)
            if match:
                return match.group(1)
        except:
            pass
        cookie = response.cookies.get("datadome")
        if cookie:
            return cookie
        set_cookie = response.headers.get("Set-Cookie", "")
        match = re.search(r'datadome=([^;]+)', set_cookie)
        if match:
            return match.group(1)
        return None
    except Exception as e:
        return None


def get_session_with_rotation():
    session = requests.Session()
    with IP_ROTATION['lock']:
        IP_ROTATION['counter'] += 1
        if IP_ROTATION['counter'] >= 20:
            IP_ROTATION['counter'] = 0
            if PROXY_LIST:
                proxy = random.choice(PROXY_LIST)
                session.proxies = {
                    'http': proxy,
                    'https': proxy
                }
    return session

def set_account_bio(jwt_token, bio_text):
    try:
        data = Data()
        data.field_2 = 17
        data.field_5.CopyFrom(EmptyMessage())
        data.field_6.CopyFrom(EmptyMessage())
        data.field_8 = bio_text
        data.field_9 = 1
        data.field_11.CopyFrom(EmptyMessage())
        data.field_12.CopyFrom(EmptyMessage())

        data_bytes = data.SerializeToString()
        padded_data = pad(data_bytes, AES.block_size)
        cipher = AES.new(AES_KEY_G, AES.MODE_CBC, AES_IV_G)
        encrypted_data = cipher.encrypt(padded_data)

        headers = {
            "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            "Accept-Encoding": "deflate, gzip",
            "X-GA-SV": "1789535861",
            "Authorization": f"Bearer {jwt_token}",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55",
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Unity-Version": "2018.4.12f1",
            "Host": "clientbp.ppmainecoonghj.com",
            "Connection": "Keep-Alive"
        }

        game_response = requests.post(
            "https://clientbp.ppmainecoonghj.com/UpdateSocialBasicInfo",
            headers=headers,
            data=encrypted_data,
            timeout=10,
            verify=False
        )

        if game_response.status_code == 200:
            return True
        return False
    except Exception as e:
        return False


def get_login_data(jwt_token):
    try:
        payload = ""
        headers = {
            'User-Agent': "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            'Accept-Encoding': "deflate, gzip",
            'X-GA-SV': "1789535861",
            'Authorization': f"Bearer {jwt_token}",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-Unity-Version': "2018.4.12f1"
        }
        response = requests.post("https://clientbp.ppmainecoonghj.com/GetLoginData", data=payload, headers=headers, verify=False, timeout=10)
        return response.text
    except Exception as e:
        return None
def major_login(access_token, open_id, lang):
    try:
        dT = bytes.fromhex('1a13323032362d30392d32382031363a33333a3039220966726565206669726528013a07312e3133322e38423e416e64726f6964204f53203135202f204150492d33352028415033412e3234303930352e3031352e41322f4131352e302e32362e302e5647574d49584d294a0848616e6468656c6452094d544e2053595249415a1243617272696572446174614e6574776f726b60e80c68d00572033332307a1d41524d3634204650204153494d4420414553207c2031383230207c20388001d21d8a01084d616c692d47353792013e4f70656e474c20455320332e322076312e72343970312d3034656163302e63383264376466616662353534653435316437303436356139613231666139389a012b476f6f676c657c34383535623136372d616539622d346237622d393531642d353234636336343461313962a2010c34362e35382e3137312e3639aa01026172b201203435393935623533323538333730306231393264643965356261646335316539ba010134c2010848616e6468656c64ca01115869616f6d69203235303238524e303341d201024d45ea014032383438303866316233326531653538343861303464666163303735633462633439613637613938646539303731356462343265313461316134666539663566f00101ca02094d544e205359524941d202023347ca03206538396231353865346263663938386562643039656238336635333738653837e00387df06e803cac701f003a50a8004cac801880487df069004cac801980487df06c80403d2045a2f646174612f6170702f7e7e35745f77707645586d6e3153656d6a757853337251673d3d2f636f6d2e6474732e667265656669726574682d56386e6233734e7a4b4a696a707a75737a55784c78773d3d2f6c69622f61726d3634e00401ea047a62386530636435653239356565653432663538363064336338366534383364647c2f646174612f6170702f7e7e35745f77707645586d6e3153656d6a757853337251673d3d2f636f6d2e6474732e667265656669726574682d56386e6233734e7a4b4a696a707a75737a55784c78773d3d2f626173652e61706bf00403f804028a050236349a050a32303139313231323239b205094f70656e474c455332b805ff3fc00504e0059b9501ea0507616e64726f6964f205704b717348547943694835645553466250354270506a44536e4f7235426652544d57323133433177397558326553476f6b317756356970464777385175503238326266496971724f4676364746766c4341794941384336787236483474316d35394933664e6153666f4466563435425748f805e7e40682062d7b226375725f72617465223a5b36302c39302c3132305d2c22737570706f72745f65746332223a66616c73657d8806019006019a060134a2060134b206094352171554095b5434c006f87bc80601d2068a0168747470733a2f2f646c2e616b2e66726565666972656d6f62696c652e636f6d2f6c6976652f4142486f74557064617465732f7c68747470733a2f2f636f72652d616b2e66726565666972656d6f62696c652e636f6d2f6c6976652f4142486f74557064617465732f7c3231316339333331363866353539303263376466626664386334653239353764da0612312e34323762356638316437323161343430')

        dT = dT.replace(b'2026-06-29 13:42:51', str(datetime.now())[:-7].encode())
        dT = dT.replace(b'284808f1b32e1e5848a04dfac075c4bc49a67a98de90715db42e14a1a4fe9f5f', access_token.encode())
        dT = dT.replace(b'45995b532583700b192dd9e5badc51e9', open_id.encode())

        data = bytes.fromhex(encrypt_api(dT.hex()))

        response = requests.post("https://loginbp.ppmainecoonghj.com/MajorLogin", headers={
            'User-Agent': "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
            'Accept-Encoding': "deflate, gzip",
            'X-GA-SV': str(int(time.time())),
            'Authorization': "Bearer",
            'X-GA': "v1 1",
            'ReleaseVersion': "OB55",
            'Content-Type': "application/x-www-form-urlencoded",
            'X-Unity-Version': "2018.4.12f1"
        }, data=data, verify=False, timeout=10)

        if response.status_code == 200:
            jwt_start = response.text.find("eyJ")
            if jwt_start != -1:
                jwt_token = response.text[jwt_start:]
                second_dot = jwt_token.find(".", jwt_token.find(".") + 1)
                if second_dot != -1:
                    jwt_token = jwt_token[:second_dot + 44]
                    payload_part = jwt_token.split('.')[1]
                    data_json = json.loads(base64.urlsafe_b64decode(payload_part + '=' * (4 - len(payload_part) % 4)))
                    acc_id = data_json.get('account_id') or data_json.get('external_id')
                    if acc_id:
                        return {"account_id": str(acc_id), "jwt_token": jwt_token}
    except Exception as e:
        pass
    return None

def create_account(region, prefix, thread_id):
    global SUCCESS_COUNT
    max_attempts = 5

    for attempt in range(max_attempts):
        with LOCK:
            if SUCCESS_COUNT >= TARGET_COUNT:
                return None

        try:
            session = get_session_with_rotation()
            password = generate_password()

            datadome_cookie = get_datadome_cookie()
            if not datadome_cookie:
                time.sleep(0.5)
                continue

            payload_register = json.dumps(
                {"app_id": 100067, "client_type": 2, "password": password, "source": 2},
                separators=(',', ':')
            )
            signature = hmac.new(API_SECRET_KEY.encode(), payload_register.encode(), hashlib.sha256).hexdigest()
            headers_reg = {
                "User-Agent": "GarenaMSDK/4.0.44(25028RN03A ;Android 15;ar;EG;app 1.132.1 2019121229;)",
                "Connection": "Keep-Alive",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Authorization": f"Signature {signature}",
                "Content-Type": "application/json; charset=utf-8",
                "Cookie": f"datadome={datadome_cookie}",
                "Host": "100067.connect.garena.com",
            }

            resp_reg = session.post(
                "https://100067.connect.garena.com/api/v2/oauth/guest:register",
                headers=headers_reg,
                data=payload_register,
                timeout=10,
                verify=False
            )

            if resp_reg.status_code != 200:
                if resp_reg.status_code == 429:
                    time.sleep(2 ** attempt)
                continue
            reg_json = resp_reg.json()
            if reg_json.get("code") != 0:
                continue
            uid = reg_json['data']['uid']

            with LOCK:
                if SUCCESS_COUNT >= TARGET_COUNT:
                    return None

            payload_token = json.dumps({
                "client_id": 100067,
                "client_secret": API_HEX_KEY,
                "client_type": 2,
                "device_id": "02-344afb0e-593c-40b7-92f2-171972f74807",
                "password": password,
                "response_type": "token",
                "uid": uid,
            }, separators=(',', ':'))
            signature2 = hmac.new(API_SECRET_KEY.encode(), payload_token.encode(), hashlib.sha256).hexdigest()
            headers_tok = {
                "User-Agent": "GarenaMSDK/4.0.44(25028RN03A ;Android 15;ar;EG;app 1.132.1 2019121229;)",
                "Connection": "Keep-Alive",
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "Content-Type": "application/json; charset=utf-8",
                "Cookie": f"datadome={datadome_cookie}",
                "Host": "100067.connect.garena.com",
            }
            resp_tok = session.post(
                "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant",
                headers=headers_tok,
                data=payload_token,
                timeout=10,
                verify=False
            )

            if resp_tok.status_code != 200:
                continue
            tok_json = resp_tok.json()
            if tok_json.get("code") != 0:
                continue
            access_token = tok_json['data']['access_token']
            open_id = tok_json['data']['open_id']

            with LOCK:
                if SUCCESS_COUNT >= TARGET_COUNT:
                    return None

            keystream = [0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30,0x31,0x37,0x30,0x30,0x30,0x30,0x30,0x32,0x30]
            field = codecs.decode(''.join(chr(ord(open_id[i]) ^ keystream[i % len(keystream)]) for i in range(len(open_id))).encode('unicode_escape').decode('utf-8'), 'unicode_escape').encode('latin1')

            name = f"{prefix}{random.randint(1000, 9999)}"
            lang = REGION_LANG.get(region.upper(), "en")
            proto_data = build_proto({
                1: name, 2: access_token, 3: open_id,
                5: 102000007, 6: 4, 7: 1, 13: 1, 14: field,
                15: lang, 16: 1, 17: 1,
                20: "1.132.6", 21: 1,
                22: bytes.fromhex('474752450101010067020000a6a42db7bc5516876af3d1ba4adc337bac558af092eb3757d59d65c9323bba42c6593a48b74f33b2b5b3dc45cbd7ac02040db58f394045be4835213e12c35e5566445a5224f39d205fcf91c0e6bec797e7b3968ac00e90d7500b5865828a9d6f2091c3070f5319a130748e407ed57e6638974670ac045631b3d08c310cf1256cebcf1aed2d97d177534603d1c95d9c5d698340e797e72aa7ecc67a33122e48b0dfda050a1649586aca5e979be1fd9d99f48cd8cf59630e0ff60f67d4ed2ec4e5e7475970449a6c06329009ee0ce2567892587675781a31e4bb2774403b2f78e9811df2cb397fa602572266747704c6258077910902eb7420bcb4ab743d1610cddba9019e7867aaad3aa7ba9b04968064a409b66733f9f78c566a25ff478cba37a2ffe23203d4b05bceef826f174b0be7912d19432cc759325251fa094d70693fb672d6f9e799284081b3adb541dd8f27ef80dcf1e7f0ff30f2fd976659457ce41e175a2d6301b777981ccc16b9a8247abaab8de0867836c27de0146fe4d0e1fd39b86ba51f0b58601cfcbd7f6f3451fe4184b26ed44ac2f6f7bb4ce5d9a80f88c2cbfe7553e5ab97c8b028ae16b4f70f037753b8c229a6e5e9038fcbb9b4c2abb954894f8f2faf177bfdaab3b0ed537156633621d16b62d58ba4ebe518997c33e2304976ba6af9df7e7e34302c7910ae559c7e3d20a30d71c14f85c0e86f26291bbf18c2d9dfe9a908592eea4523e6c1e5d9bb5abfbebfccd5c4e136f9be777723e932b06c029df5125191000c90fde62a8e5f8fceb28648f0c69ec3037d09302b2ade908a20dbd42761ca449b2743fc362649e16235769d9fbd7f87cd64972b58d69c0441abb5d22ddc6ed059f7ac1bdbfaef8c60e64631809c5e08c7cb4074c8ce6170d94b411604986be4ae163a'),
            })
            encrypted_payload = bytes.fromhex(encrypt_api(proto_data.hex()))

            headers_major = {
                "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
                "Accept-Encoding": "deflate, gzip",
                "X-GA-SV": "1789535859",
                "Authorization": "Bearer",
                "X-GA": "v1 1",
                "ReleaseVersion": "OB55",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Unity-Version": "2018.4.12f1",
                "Host": "loginbp.ppmainecoonghj.com"
            }
            session.post("https://loginbp.ppmainecoonghj.com/MajorRegister", headers=headers_major, data=encrypted_payload, verify=False, timeout=10)

            login_res = major_login(access_token, open_id, lang)

            account_data = {
                "uid": int(uid),
                "password": password,
                "account_id": login_res["account_id"] if login_res else "N/A",
                "name": name,
                "region": region,
                "date_created": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "jwt_token": login_res.get("jwt_token", "") if login_res else ""
            }

            bio_success = False
            if account_data.get('jwt_token'):
                time.sleep(0.5)
                get_login_data(account_data['jwt_token'])
                bio_success = set_account_bio(account_data['jwt_token'], BIO_TEXT)
                if bio_success:
                    global BIO_SET_COUNTER
                    BIO_SET_COUNTER += 1
            account_data['bio_status'] = bio_success

            save_account_to_json(account_data)

            with LOCK:
                if SUCCESS_COUNT >= TARGET_COUNT:
                    return None
                SUCCESS_COUNT += 1

            return account_data
        except Exception as e:
            time.sleep(0.3)
    return None

def worker(region, prefix, thread_id):
    while not EXIT:
        with LOCK:
            if SUCCESS_COUNT >= TARGET_COUNT:
                break

        acc = create_account(region, prefix, thread_id)
        if acc:
            bio_status = "bio: success" if acc.get('bio_status', False) else "bio: null"
            print(f"BOT = {acc['account_id']} | UiD = {acc['uid']} | PassWord = {acc['password']} | NamE = {acc['name']} | ReGioN = {acc['region']} | {bio_status} | Progress: {SUCCESS_COUNT}/{TARGET_COUNT}")
            sys.stdout.flush()
        else:
            time.sleep(0.3)


def run_generation(region, prefix, count, threads_count=None):
    global TARGET_COUNT, SUCCESS_COUNT
    TARGET_COUNT = int(count)
    SUCCESS_COUNT = 0

    if threads_count is None:
        threads_count = min(3, TARGET_COUNT)

    print(f"\n[⚡] Starting with {threads_count} threads, target: {TARGET_COUNT} accounts")
    print(f"[⚡] Region: {region} | Prefix: {prefix}")
    print("[⚡] Starting generation...\n")
    sys.stdout.flush()

    threads = []
    for i in range(threads_count):
        t = threading.Thread(target=worker, args=(region, prefix, i + 1))
        t.daemon = True
        t.start()
        threads.append(t)

    try:
        while any(t.is_alive() for t in threads):
            time.sleep(0.5)
            with LOCK:
                if SUCCESS_COUNT >= TARGET_COUNT:
                    break
    except KeyboardInterrupt:
        safe_exit()

    print(f"\n- Done! Created {SUCCESS_COUNT} accounts")
    print(f"- Bio changed for {BIO_SET_COUNTER} accounts")
    sys.stdout.flush()
    return SUCCESS_COUNT

def _resolve_region_from_input(choice):
    region_map = {
        "1": "BD", "2": "IND", "3": "PK", "4": "SG",
        "5": "ID", "6": "ME", "7": "VN", "8": "TW"
    }
    return region_map.get(choice.lower(), None)


def main():
    parser = argparse.ArgumentParser(description="FF Account Generator")
    parser.add_argument("--region", type=str, default=None, help="Region code (ME, IND, BD, ...)")
    parser.add_argument("--prefix", type=str, default=None, help="Name prefix (e.g. hello__)")
    parser.add_argument("--count", type=int, default=None, help="Number of accounts to create")
    parser.add_argument("--threads", type=int, default=None, help="Number of threads")
    args = parser.parse_args()
    region = os.environ.get("FF_REGION") or args.region
    prefix = os.environ.get("FF_PREFIX") or args.prefix
    count_env = os.environ.get("FF_COUNT")
    count = int(count_env) if (count_env and count_env.isdigit()) else args.count
    threads = args.threads or (int(os.environ["FF_THREADS"]) if os.environ.get("FF_THREADS", "").isdigit() else None)

    if not region:
        print("[1] BD | [2] IND | [3] PK | [4] SG | [5] ID | [6] ME | [7] VN | [8] TW")
        choice = input("- Server : ").strip().lower()
        region = _resolve_region_from_input(choice)
        if not region:
            print("Err - in server")
            return

    if not prefix:
        prefix = input("- Name : ").strip() or "hello__"

    if not count:
        try:
            count = int(input("- Count : "))
        except:
            return

    run_generation(region=region, prefix=prefix, count=count, threads_count=threads)


if __name__ == "__main__":
    main()