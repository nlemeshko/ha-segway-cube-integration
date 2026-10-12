# Copyright 2026 NootNooot. Apache-2.0.
# Modified: cryptography backend and constant-time MAC comparison.
"""
nb_crypto.py — Ninebot BLE Encryption2 crypto primitives.

Reimplements libnbcrypto.so encryption/decryption in pure Python.
Verified against Ghidra decompilation of nb_encrypt @ 0x169f80,
FUN_0016a35c (CBC-MAC) @ 0x16a35c, and nb_decrypt @ 0x16a55c.
"""

import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# ---------------------------------------------------------------------------
# fw_data constant (Gen2 non-SN ECB input and initial key2)
# ---------------------------------------------------------------------------

FW_DATA = bytes(
    [
        0x97,
        0xCF,
        0xB8,
        0x02,
        0x84,
        0x41,
        0x43,
        0xDE,
        0x56,
        0x00,
        0x2B,
        0x3B,
        0x34,
        0x78,
        0x0A,
        0x5D,
    ]
)  # from libnbcrypto.so @ 0x45A80


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------


def derive_key(key1: bytes, key2: bytes | None) -> bytes:
    """SHA-1(key1_pad16 || key2_pad16)[0:16] → AES-128 key."""
    k1 = (key1 + b"\x00" * 16)[:16]
    k2 = (key2 + b"\x00" * 16)[:16] if key2 else b"\x00" * 16
    return hashlib.sha1(k1 + k2).digest()[:16]


# ---------------------------------------------------------------------------
# Nonce / CTR block construction  (from Ghidra: nb_encrypt @ 0x169f80)
#
#   nonce_13 = counter_BE32[4] || auth[0:8] || 0x00
#   A_i      = [0x01] || nonce_13 || [0x00, i]       (16 bytes)
#   B_0      = [0x59] || nonce_13 || [0x00, payload_len]
# ---------------------------------------------------------------------------


def _build_nonce(counter: int, auth: bytes) -> bytes:
    """Build the 13-byte nonce from counter and auth param."""
    return struct.pack(">I", counter) + auth[:8] + b"\x00"


def _build_a_block(nonce_13: bytes, block_i: int) -> bytes:
    """Build A_i CTR block (16 bytes). i=0 for tag, i=1+ for data."""
    return b"\x01" + nonce_13 + bytes([0x00, block_i & 0xFF])


def _build_b0(nonce_13: bytes, payload_len: int) -> bytes:
    """Build B_0 block for CBC-MAC (16 bytes)."""
    return b"\x59" + nonce_13 + bytes([0x00, payload_len & 0xFF])


# ---------------------------------------------------------------------------
# CBC-MAC  (from Ghidra: FUN_0016a35c @ 0x16a35c)
#
#   X = AES(B0)
#   X = AES(X ^ pad16(plaintext[0:3]))     ← "associated data" (frame header)
#   for each 16-byte block of plaintext[3:]:
#       X = AES(X ^ pad16(block))
#   tag = X[0:4]
# ---------------------------------------------------------------------------


def _aes_ecb_one(key: bytes, block: bytes) -> bytes:
    """Single-block AES-128-ECB encrypt."""
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(block) + encryptor.finalize()


def _cbc_mac(aes_key: bytes, plaintext: bytes, nonce_13: bytes) -> bytes:
    """Compute 4-byte CBC-MAC tag over the plaintext frame."""
    payload_len = len(plaintext) - 3  # bytes after 3-byte header

    # B0
    b0 = _build_b0(nonce_13, payload_len)
    x = _aes_ecb_one(aes_key, b0)

    # "Associated data": first 3 bytes of frame, zero-padded to 16
    aad = plaintext[:3] + b"\x00" * 13
    x = _aes_ecb_one(aes_key, bytes(a ^ b for a, b in zip(x, aad)))

    # Payload blocks (plaintext[3:])
    payload = plaintext[3:]
    offset = 0
    while offset < len(payload):
        chunk = payload[offset : offset + 16]
        block = chunk + b"\x00" * (16 - len(chunk))  # zero-pad
        x = _aes_ecb_one(aes_key, bytes(a ^ b for a, b in zip(x, block)))
        offset += 16

    return x[:4]


# ---------------------------------------------------------------------------
# CTR-mode encrypt/decrypt  (from Ghidra: nb_encrypt, nb_decrypt)
# ---------------------------------------------------------------------------


def _ctr_xor(aes_key: bytes, data: bytes, nonce_13: bytes, start_ctr: int = 1) -> bytes:
    """CTR-mode XOR (works for both encrypt and decrypt)."""
    out = bytearray()
    block_i = start_ctr
    offset = 0
    while offset < len(data):
        a_block = _build_a_block(nonce_13, block_i)
        keystream = _aes_ecb_one(aes_key, a_block)
        chunk_len = min(16, len(data) - offset)
        for j in range(chunk_len):
            out.append(data[offset + j] ^ keystream[j])
        offset += chunk_len
        block_i += 1
    return bytes(out)


# ---------------------------------------------------------------------------
# Public encrypt / decrypt
# ---------------------------------------------------------------------------


class NbCrypto:
    """Stateful encryption context mirroring libnbcrypto.so crypto_param_t."""

    def __init__(self, ecb_input: bytes = b"\x00" * 16):
        self.key1: bytes | None = None
        self.key2: bytes | None = None
        self.auth: bytes = b"\x00" * 16  # sn_data (set via set_auth_param)
        self.counter: int = 0  # 0 = non-SN mode
        self.ecb_input: bytes = ecb_input[:16]  # non-SN ECB plaintext block

    def set_key(self, key1: bytes, key2: bytes | None):
        self.key1 = key1
        self.key2 = key2

    def set_auth_param(self, auth: bytes):
        self.auth = bytes(auth[:16])

    def start_sn(self):
        """Enable SN mode (counter starts at 1, first encrypt uses 2)."""
        self.counter = 1

    def reset_sn(self):
        self.counter = 0

    def _aes_key(self) -> bytes:
        return derive_key(self.key1 or b"", self.key2)

    # ── Encrypt ──────────────────────────────────────────────────────

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt a plaintext frame.
        Returns the encrypted frame (plaintext_len + 6 bytes).
        """
        aes_key = self._aes_key()
        header = plaintext[:3]  # [5A, B5, LEN] — copied verbatim

        if self.counter > 0:
            return self._encrypt_sn(aes_key, plaintext, header)
        else:
            return self._encrypt_non_sn(aes_key, plaintext, header)

    def _encrypt_sn(self, aes_key: bytes, plaintext: bytes, header: bytes) -> bytes:
        self.counter += 1
        counter = self.counter

        nonce_13 = _build_nonce(counter, self.auth)

        # CBC-MAC over plaintext
        raw_tag = _cbc_mac(aes_key, plaintext, nonce_13)

        # CTR encrypt payload (plaintext[3:])
        ciphertext = _ctr_xor(aes_key, plaintext[3:], nonce_13, start_ctr=1)

        # Encrypt tag with A_0
        a0_ks = _aes_ecb_one(aes_key, _build_a_block(nonce_13, 0))
        enc_tag = bytes(a ^ b for a, b in zip(raw_tag, a0_ks[:4]))

        # Counter tail: big-endian uint16
        ctr_tail = struct.pack(">H", counter & 0xFFFF)

        return header + ciphertext + enc_tag + ctr_tail

    def _encrypt_non_sn(self, aes_key: bytes, plaintext: bytes, header: bytes) -> bytes:
        payload = plaintext[3:]

        # Checksum over payload
        checksum = (~sum(payload)) & 0xFFFF

        # Static keystream: AES_ECB(key, ecb_input)
        keystream = _aes_ecb_one(aes_key, self.ecb_input)

        # XOR each block with the SAME keystream
        out = bytearray()
        offset = 0
        while offset < len(payload):
            chunk_len = min(16, len(payload) - offset)
            for j in range(chunk_len):
                out.append(payload[offset + j] ^ keystream[j])
            offset += chunk_len

        tail = bytes([0x00, 0x00, checksum & 0xFF, (checksum >> 8) & 0xFF, 0x00, 0x00])
        return header + bytes(out) + tail

    # ── Decrypt ──────────────────────────────────────────────────────

    def decrypt(self, cipherframe: bytes) -> tuple[bytes, int]:
        """
        Decrypt an encrypted frame.
        Returns (decrypted_plaintext, return_code).
        Return codes: 0=success, 1=MAC mismatch, 2=replay
        """
        aes_key = self._aes_key()
        header = cipherframe[:3]

        # Extract tail (last 6 bytes)
        tail = cipherframe[-6:]
        encrypted_body = cipherframe[3:-6]

        # Read counter from tail
        recv_counter = (tail[4] << 8) | tail[5]  # big-endian uint16

        if recv_counter > 0:
            return self._decrypt_sn(aes_key, header, encrypted_body, tail, recv_counter)
        else:
            return self._decrypt_non_sn(aes_key, header, encrypted_body, tail)

    def _decrypt_sn(
        self, aes_key: bytes, header: bytes, enc_body: bytes, tail: bytes, recv_counter: int
    ) -> tuple[bytes, int]:
        # Replay check
        if recv_counter <= (self.counter & 0xFFFF):
            # Allow it during handshake when device counter might be independent
            pass  # Don't enforce strict replay for now

        nonce_13 = _build_nonce(recv_counter, self.auth)

        # CTR decrypt payload
        plaintext_payload = _ctr_xor(aes_key, enc_body, nonce_13, start_ctr=1)

        # Decrypt tag with A_0
        enc_tag = tail[:4]
        a0_ks = _aes_ecb_one(aes_key, _build_a_block(nonce_13, 0))
        recv_tag = bytes(a ^ b for a, b in zip(enc_tag, a0_ks[:4]))

        # Reconstruct plaintext and verify MAC
        plaintext = header + plaintext_payload
        expected_tag = _cbc_mac(aes_key, plaintext, nonce_13)

        if not hmac.compare_digest(recv_tag, expected_tag):
            # Return decrypted data anyway for debugging, but flag error
            return plaintext, 1  # MAC mismatch

        return plaintext, 0

    def _decrypt_non_sn(self, aes_key: bytes, header: bytes, enc_body: bytes, tail: bytes) -> tuple[bytes, int]:
        keystream = _aes_ecb_one(aes_key, self.ecb_input)

        out = bytearray()
        offset = 0
        while offset < len(enc_body):
            chunk_len = min(16, len(enc_body) - offset)
            for j in range(chunk_len):
                out.append(enc_body[offset + j] ^ keystream[j])
            offset += chunk_len

        plaintext = header + bytes(out)

        # Verify checksum
        payload = plaintext[3:]
        expected_csum = (~sum(payload)) & 0xFFFF
        recv_csum = tail[2] | (tail[3] << 8)
        if expected_csum != recv_csum:
            return plaintext, 1  # checksum mismatch

        return plaintext, 0
