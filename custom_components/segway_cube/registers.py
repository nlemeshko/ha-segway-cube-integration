"""Cube register catalogue; opaque/packed values remain raw until validated."""

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Register:
    key: str
    board: int
    index: int
    length: int
    module: str

    @property
    def dynamic(self):
        return self.key in {
            "rSocTemp",
            "rCapacity",
            "rInputPower",
            "rOutputPower",
            "rRemainTime",
            "rBool",
            "rErrorCode",
            "rWarnCode",
            "rOutputInfo",
            "rTemp",
            "rBmsCount",
        } or self.key in {"rFunBool", "rFunBool2", "rACInputPowerLimit"} or self.key.startswith("rBattery")

    def decode(self, raw: bytes):
        if len(raw) != self.length:
            raise ValueError("Unexpected register length")
        if self.length in (2, 4):
            return int.from_bytes(raw, "little")
        if self.key.endswith(("Pn", "Sn")) or self.key == "rSN":
            return raw.rstrip(b"\x00").decode("ascii", errors="replace")
        return raw.hex()


REGISTERS = tuple(Register(**item) for item in json.loads(Path(__file__).with_name("registers.json").read_text()))
BY_KEY = {r.key: r for r in REGISTERS}


def battery_count_from_raw(raw: bytes) -> int | None:
    """Accept legacy scalar counts and the matching pair verified on Cube.

    The tested station returns 03 03 and has three physical modules. Unequal
    packed fields remain uninterpreted so we never exclude a possible module.
    """
    if len(raw) != 2:
        return None
    scalar = int.from_bytes(raw, "little")
    if 1 <= scalar <= 5:
        return scalar
    if raw[0] == raw[1] and 1 <= raw[0] <= 5:
        return raw[0]
    return None


# Scalar settings only. Packed AC/DC switches must not be guessed.
WRITABLE = {
    "rACInputPowerLimit": 0xD0,
    "rACStandbyTime": 0xD4,
    "rDCStandbyTime": 0xD5,
    "rDeviceStandbyTime": 0xD3,
    "rScreenDisplayTime": 0xDC,
    "rLedMode": 0xDD,
    "rAtmosphereMode": 0xDE,
    "rRhythmMode": 0xE3,
}
