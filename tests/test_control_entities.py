from types import SimpleNamespace

from cube_test.control_entity import add_supported_controls
from cube_test.controls import CONTROLS, SELECTS
from cube_test.select import CubeSelect
from cube_test.switch import CubeSwitch


def coordinator(data):
    return SimpleNamespace(
        data=data,
        last_update_success=True,
        client=SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Home", serial="SERIAL"),
    )


def test_switches_and_fan_decode_official_flags():
    c = coordinator({"rFunBool": 2, "rFunBool2": 0x17})
    assert CubeSwitch(c, CONTROLS["ac_output"]).is_on is True
    assert CubeSwitch(c, CONTROLS["dc_output"]).is_on is False
    assert CubeSwitch(c, CONTROLS["r_drive"]).is_on is True
    assert CubeSwitch(c, CONTROLS["ups"]).is_on is True
    assert CubeSwitch(c, CONTROLS["button_tone"]).is_on is False
    assert CubeSelect(c, CONTROLS["fan_mode"]).current_option == "active_cooling"


def test_charging_select_reflects_model_and_keeps_unknown_value_unknown():
    c = coordinator({"rFunSupBool": 0xFEEE, "rACInputPowerLimit": 700})
    entity = CubeSelect(c, CONTROLS["ac_charge_limit"])
    assert entity.available
    assert entity.current_option == "700 W"
    assert entity.options[-1] == "1650 W"
    c.data["rACInputPowerLimit"] = 1600
    assert entity.current_option is None


def test_supported_entities_are_added_after_capability_poll_without_duplicates():
    added, callbacks, unloads = [], [], []
    c = coordinator({})

    def subscribe(callback):
        callbacks.append(callback)
        return lambda: callbacks.remove(callback)

    c.async_add_listener = subscribe
    entry = SimpleNamespace(runtime_data=c, async_on_unload=unloads.append)
    add_supported_controls(entry, added.extend, SELECTS, lambda c, d: d.key)
    assert added == ["fan_mode"]
    c.data = {"rFunSupBool": 0xFEEE}
    callbacks[0]()
    assert "ac_charge_limit" in added and "screen_timeout" in added
    assert "ac_frequency" not in added
    count = len(added)
    callbacks[0]()
    assert len(added) == count
    unloads[0]()
    assert callbacks == []
