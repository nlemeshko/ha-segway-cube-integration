"""User settings derived from Segway's Cube UI configuration (server ID 1112)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Control:
    key: str
    register: str
    icon: str
    mask: int = 0
    support_mask: int = 0
    options: tuple[tuple[str, int], ...] = ()

    def supported(self, data):
        if self.key == "ac_charge_limit":
            return charge_limit(data) is not None
        return not self.support_mask or bool((data.get("rFunSupBool") or 0) & self.support_mask)

    def choices(self, data):
        if self.key == "ac_charge_limit":
            maximum = charge_limit(data)
            if maximum is None:
                return {}
            values = (*range(200, maximum - 50, 100), maximum)
            return {f"{value} W": value for value in values}
        return dict(self.options)


def charge_limit(data):
    # The official app chooses its 1250 W / 1650 W page from these bits.
    return {0x100: 1250, 0x200: 1650}.get((data.get("rFunSupBool") or 0) & 0x300)


STANDBY = (
    ("never", 0),
    ("15_minutes", 15),
    ("30_minutes", 30),
    ("1_hour", 60),
    ("2_hours", 120),
    ("6_hours", 360),
    ("12_hours", 720),
    ("24_hours", 1440),
)
SWITCHES = (
    Control("ac_output", "rFunBool", "mdi:power-socket-eu", mask=0x02),
    Control("dc_output", "rFunBool", "mdi:current-dc", mask=0x01),
    Control("r_drive", "rFunBool2", "mdi:lightning-bolt", mask=0x04),
    Control("ups", "rFunBool2", "mdi:power-plug-battery", mask=0x02),
    Control("button_tone", "rFunBool2", "mdi:volume-high", mask=0x08),
)
SELECTS = (
    Control("ac_charge_limit", "rACInputPowerLimit", "mdi:battery-charging"),
    Control("fan_mode", "rFunBool2", "mdi:fan", mask=0x10, options=(("active_cooling", 0x10), ("silent", 0))),
    Control("ac_standby", "rACStandbyTime", "mdi:timer-outline", support_mask=0x0800, options=STANDBY),
    Control("dc_standby", "rDCStandbyTime", "mdi:timer-outline", support_mask=0x1000, options=STANDBY),
    Control("device_standby", "rDeviceStandbyTime", "mdi:timer-outline", support_mask=0x2000, options=STANDBY),
    Control(
        "screen_timeout",
        "rScreenDisplayTime",
        "mdi:monitor",
        support_mask=0x4000,
        options=(("always_on", 0), ("1_minute", 1), ("5_minutes", 5), ("15_minutes", 15), ("30_minutes", 30)),
    ),
    Control(
        "ac_frequency",
        "rFrequencySwitchValue",
        "mdi:sine-wave",
        support_mask=0x01,
        options=(("50 Hz", 50), ("60 Hz", 60)),
    ),
)
CONTROLS = {control.key: control for control in (*SWITCHES, *SELECTS)}
CONTROL_REGISTERS = {control.register for control in CONTROLS.values()}
