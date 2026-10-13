"""Cube Encryption2 framing. No Home Assistant dependencies."""

from dataclasses import dataclass

BLE_BOARD = 0x12
MCU_BOARD = 0x06
MANUFACTURERS = (16974, 20034, 16975, 20035)


class ProtocolError(Exception):
    """Invalid or unauthenticated protocol frame."""


class PasswordRequired(ProtocolError):
    """Station requires a missing key or explicitly rejected the supplied key."""


class PairingRequired(ProtocolError):
    """Station has no password; explicit pairing is required."""


@dataclass(frozen=True)
class Frame:
    board: int
    command: int
    index: int
    data: bytes


def build_frame(board: int, command: int, index: int, data: bytes = b"", sync: int = 0xA5) -> bytes:
    if len(data) > 255 or sync not in (0xA5, 0xB5):
        raise ValueError("Invalid frame")
    return bytes((0x5A, sync, len(data), 0x3E, board, command, index)) + data


def parse_frame(data: bytes) -> Frame:
    if len(data) < 7 or data[0] != 0x5A or data[1] not in (0xA5, 0xB5) or data[4] != 0x3E or len(data) != data[2] + 7:
        raise ProtocolError("Invalid response frame")
    return Frame(data[3], data[5], data[6], data[7:])


class FrameBuffer:
    """Reassemble fragmented/coalesced GATT notifications."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 3:
            pos = next(
                (
                    i
                    for i in range(len(self.buffer) - 1)
                    if self.buffer[i] == 0x5A and self.buffer[i + 1] in (0xA5, 0xB5)
                ),
                -1,
            )
            if pos < 0:
                self.buffer = self.buffer[-1:] if self.buffer[-1] == 0x5A else bytearray()
                break
            del self.buffer[:pos]
            if len(self.buffer) < 3:
                break
            total = self.buffer[2] + 13
            if len(self.buffer) < total:
                break
            frames.append(bytes(self.buffer[:total]))
            del self.buffer[:total]
        return frames


def is_cube(manufacturer_data: dict[int, bytes]) -> bool:
    for manufacturer, payload in manufacturer_data.items():
        if manufacturer in (16974, 20034) and len(payload) >= 2 and payload[0] == 208:
            return True
        if manufacturer in (16975, 20035) and len(payload) >= 3 and payload[:2] == b"\xd0\x00":
            return True
    return False


def parse_password(value: str) -> bytes | None:
    value = value.strip()
    if not value:
        return None
    try:
        result = bytes.fromhex(value)
    except ValueError as err:
        raise ValueError("Password must be 32 hexadecimal characters") from err
    if len(result) != 16:
        raise ValueError("Password must contain 16 bytes")
    return result
