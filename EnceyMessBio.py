import json
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import data_pb2
key = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
iv = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])
data = data_pb2.Data()
data.field_2 = 17
data.field_5.CopyFrom(data_pb2.EmptyMessage())
data.field_6.CopyFrom(data_pb2.EmptyMessage())
data.field_8 = """[b][c][00FF00] █▀▀[00FF20] █▀▀█[00FF40] █          █[00FF60] █▀▀[00FF80] █▀▀[00FF90] █
[FFFF00]█▀▀ [FFFF20]█▄▄█[FFFF40] █▄▄█ [FFFF60]█          [FFFF80]█▀▀[FFFF90] █
[FF0000]▀          [FF0020] ▀        ▀ [FF0040] ▄▄▄█ [FF0060]▀▀▀ [FF0080]▀▀▀[FF0090] ▀▀▀"""
data.field_9 = 1
data.field_11.CopyFrom(data_pb2.EmptyMessage())
data.field_12.CopyFrom(data_pb2.EmptyMessage())
data_bytes = data.SerializeToString()
padded_data = pad(data_bytes, AES.block_size)
cipher = AES.new(key, AES.MODE_CBC, iv)
encrypted_data = cipher.encrypt(padded_data)
formatted_encrypted_data = ' '.join([f"{byte:02X}" for byte in encrypted_data])
print("Encrypted data in the desired format:")
print(formatted_encrypted_data)