from types import SimpleNamespace

from cube_test.sensor import CubeStatusSensor


def test_verified_status_fields_and_invalid_charge():
    coordinator = SimpleNamespace(
        client=SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Home", serial=""),
        data={"rSocTemp": 0x2064},
        battery_count=3,
        last_update_success=True,
    )
    battery = CubeStatusSensor(coordinator, "battery")
    temperature = CubeStatusSensor(coordinator, "temperature")
    modules = CubeStatusSensor(coordinator, "battery_modules")
    assert battery.native_value == 100
    assert temperature.native_value == 32
    assert modules.native_value == 3
    coordinator.data["rSocTemp"] = 0x20FF
    assert not battery.available
    coordinator.data.clear()
    assert not temperature.available
