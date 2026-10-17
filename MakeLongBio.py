import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

# Protocol buffer imports and definitions
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
bio = input("Enter Bio: ")
if len(bio) >= 180:
  print("YOU NEED TO USE MESSAGE LEN 180")
  exit()
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
key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
data = Data()
data.field_2 = 17
data.field_5.CopyFrom(EmptyMessage())
data.field_6.CopyFrom(EmptyMessage())
data.field_8 = bio
data.field_9 = 1
data.field_11.CopyFrom(EmptyMessage())
data.field_12.CopyFrom(EmptyMessage())
data_bytes = data.SerializeToString()
padded_data = pad(data_bytes, AES.block_size)
cipher = AES.new(key, AES.MODE_CBC, iv)
encrypted_data = cipher.encrypt(padded_data)
formatted_encrypted_data = ' '.join([f"{byte:02X}" for byte in encrypted_data])
print("Encrypted data in the desired format:")
print(formatted_encrypted_data)
url = "https://clientbp.ggblueshark.com/UpdateSocialBasicInfo"
data_hex = formatted_encrypted_data
token = input("Enter Token: ")
data_bytes = bytes.fromhex(data_hex.replace(" ", ""))
headers = {
    "Expect": "100-continue",
    "Authorization": f"Bearer {token}",
    "X-Unity-Version": "2018.4.11f1",
    "X-GA": "v1 1",
    "ReleaseVersion": "OB54",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)",
    "Host": "clientbp.ggblueshark.com",
    "Connection": "Keep-Alive",
    "Accept-Encoding": "gzip"
}
response = requests.post(url, headers=headers, data=data_bytes)
print(response.status_code)