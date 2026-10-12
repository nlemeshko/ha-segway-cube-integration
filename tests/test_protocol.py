import pytest
from cube_test.crypto import FW_DATA, NbCrypto, derive_key
from cube_test.protocol import FrameBuffer, ProtocolError, build_frame, is_cube, parse_frame, parse_password
from cube_test.registers import BY_KEY, REGISTERS, WRITABLE


def context(counter=False):
    crypto = NbCrypto(FW_DATA)
    crypto.set_key(b"CubeTest", FW_DATA)
    crypto.set_auth_param(bytes(range(16)))
    if counter:
        crypto.start_sn()
    return crypto


@pytest.mark.parametrize("counter", [False, True])
@pytest.mark.parametrize("size", [0, 1, 14, 16, 32, 240])
def test_crypto_roundtrip_and_integrity(counter, size):
    plain = build_frame(18, 0x5B, 0, bytes(range(size)))
    wire = context(counter).encrypt(plain)
    assert len(wire) == size + 13
    assert context().decrypt(wire) == (plain, 0)
    broken = bytearray(wire)
    broken[3] ^= 0x10
    assert context().decrypt(bytes(broken))[1] != 0


def test_key_padding_is_exactly_16_bytes():
    assert derive_key(b"name", b"seed") == derive_key(b"name" + bytes(12), b"seed" + bytes(12))
    assert derive_key(b"n" * 16 + b"extra", None) == derive_key(b"n" * 16, bytes(16))


def test_crypto_matches_pinned_upstream_vectors():
    # Public synthetic data from reference CLI bb6f3d325237fa91e683df27f2197f9cb771e841.
    plain = bytes.fromhex("5aa5013e06013002")
    assert context().encrypt(plain).hex() == "5aa501ffe96af425000088ff0000"
    assert context(True).encrypt(plain).hex() == "5aa5012b517accef1e64e9950002"


def test_fragmented_and_coalesced_frames_with_noise():
    first = context().encrypt(build_frame(18, 0x5B, 0, bytes(30)))
    second = context().encrypt(build_frame(6, 1, 0x30, b"\x02"))
    buffer = FrameBuffer()
    assert buffer.feed(b"garbage\x5a") == []
    assert buffer.feed(first[1:9]) == []
    assert buffer.feed(first[9:] + second) == [first, second]
    assert buffer.buffer == b""


@pytest.mark.parametrize(
    "plain", [b"", b"\x5a\xa5", b"\x5a\xa5\x02\x06\x3e\x04\x30\x01", b"\x5a\xa5\x00\x06\x00\x04\x30"]
)
def test_response_rejects_truncation_and_wrong_destination(plain):
    with pytest.raises(ProtocolError):
        parse_frame(plain)


def test_cube_frame_addresses_are_not_scooter_defaults():
    assert build_frame(18, 0x5B, 0).hex() == "5aa5003e125b00"
    assert build_frame(6, 1, 0x30, b"\x02").hex() == "5aa5013e06013002"
    f = parse_frame(bytes.fromhex("5aa502063e04300100"))
    assert (f.board, f.command, f.index, f.data) == (6, 4, 48, b"\x01\x00")


def test_discovery_matches_cube_hardware_only():
    assert is_cube({16974: bytes.fromhex("d0020000002d")})
    assert not is_cube({16974: bytes.fromhex("82020000002d")})
    assert not is_cube({76: bytes.fromhex("d002")})


def test_password_validation():
    assert parse_password("") is None
    assert parse_password("ab" * 16) == b"\xab" * 16
    for value in ["bad", "ab" * 15, "ab" * 17, "zz" * 16]:
        with pytest.raises(ValueError):
            parse_password(value)


def test_registers_are_unique_and_control_does_not_write_packed_flags():
    assert len(REGISTERS) == 67
    assert len({(r.board, r.index, r.length) for r in REGISTERS}) == len(REGISTERS)
    assert "rFunBool" not in WRITABLE
    assert "rFunBool2" not in WRITABLE
    assert BY_KEY["rSocTemp"].decode(b"\x5a\x19") == 6490  # packed value retained, not guessed
    assert BY_KEY["rInputPower"].decode(b"\x20\x03") == 800
