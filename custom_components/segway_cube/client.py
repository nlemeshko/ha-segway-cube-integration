"""Short BLE sessions via Home Assistant's selected local or remote adapter."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .adapter import SourceLockedBleakClient
from .crypto import FW_DATA, NbCrypto
from .protocol import (
    BLE_BOARD,
    Frame,
    FrameBuffer,
    PairingRequired,
    PasswordRequired,
    ProtocolError,
    build_frame,
    parse_frame,
)

_LOGGER = logging.getLogger(__name__)
PROFILES = {
    "gen2": (0xA5, FW_DATA, FW_DATA),
    "gen3": (0xB5, None, bytes(16)),
    "gen2_zero": (0xA5, None, bytes(16)),
}
CHARACTERISTICS = (
    ("6e400002-0000-0000-006e-696e65626f74", "6e400004-0000-0000-006e-696e65626f74"),
    ("6e400002-b5a3-f393-e0a9-e50e24dcca9e", "6e400003-b5a3-f393-e0a9-e50e24dcca9e"),
)
DEVICE_NAME = "00002a00-0000-1000-8000-00805f9b34fb"


class Session:
    """One authenticated connection, with strict response correlation."""

    def __init__(self, client: BleakClient, write_char, notify_char, profile: str):
        self.client = client
        self.write_char = write_char
        self.notify_char = notify_char
        self.profile = profile
        self.sync, self.initial_key2, ecb = PROFILES[profile]
        self.crypto = NbCrypto(ecb_input=ecb)
        self.queue = asyncio.Queue(maxsize=64)
        self.buffer = FrameBuffer()
        self.serial = ""
        self.name = ""
        self.bound = False
        self.password = None
        self._rx_counter = 0
        self.lock = asyncio.Lock()

    def notification(self, _sender, data):
        for frame in self.buffer.feed(data):
            if self.queue.full():
                self.queue.get_nowait()
            self.queue.put_nowait(frame)

    async def send(self, plain: bytes):
        wire = self.crypto.encrypt(plain)
        # 20-byte chunks are valid even with a larger negotiated MTU, including ESPHome.
        for offset in range(0, len(wire), 20):
            await self.client.write_gatt_char(self.write_char, wire[offset : offset + 20], response=False)
            if offset + 20 < len(wire):
                await asyncio.sleep(0.01)

    async def receive(self, board: int, command: int, index: int | None = None, timeout=8.0) -> Frame:
        async with asyncio.timeout(timeout):
            while True:
                wire = await self.queue.get()
                plain, status = self.crypto.decrypt(wire)
                if status:
                    raise ProtocolError("Response integrity check failed")
                counter = int.from_bytes(wire[-2:], "big")
                if counter and counter <= self._rx_counter:
                    continue
                frame = parse_frame(plain)
                if counter:
                    self._rx_counter = counter
                if frame.board == board and frame.command == command and (index is None or frame.index == index):
                    return frame

    async def pre_comm(self, name: str):
        self.name = name
        self.crypto.reset_sn()
        self.crypto.set_key(name.encode(), self.initial_key2)
        await self.send(build_frame(BLE_BOARD, 0x5B, 0, sync=self.sync))
        result = await self.receive(BLE_BOARD, 0x5B, timeout=5)
        if len(result.data) < 30:
            raise ProtocolError("Incomplete authentication challenge")
        auth, serial = result.data[:16], result.data[16:30]
        self.serial = serial.rstrip(b"\x00").decode("ascii", errors="replace")
        self.bound = result.index != 0
        self.crypto.set_auth_param(auth)
        self.crypto.start_sn()
        return auth, serial

    async def authenticate(
        self,
        auth: bytes,
        serial: bytes,
        password: bytes | None,
        pair: bool,
        *,
        replace=False,
        on_key=None,
        on_pairing=None,
    ):
        if password is None:
            if self.bound and not (pair and replace):
                raise PasswordRequired("Station is bound; provide its BLE key or confirm a new binding")
            if not pair:
                raise PairingRequired("Enable pairing and confirm on the station")
            password = secrets.token_bytes(16)
            # Journal before the first SET_PWD, including when setup is cancelled.
            if on_key is not None:
                await on_key(self.serial, password, False)
            self.crypto.set_key(self.name.encode(), auth)
            if on_pairing is not None:
                on_pairing()
            deadline = asyncio.get_running_loop().time() + 60
            accepted = False
            while (remaining := deadline - asyncio.get_running_loop().time()) > 0:
                await self.send(build_frame(BLE_BOARD, 0x5C, 0, password, self.sync))
                attempt_deadline = asyncio.get_running_loop().time() + min(2, remaining)
                while (wait := attempt_deadline - asyncio.get_running_loop().time()) > 0:
                    try:
                        result = await self.receive(BLE_BOARD, 0x5C, timeout=wait)
                    except TimeoutError:
                        break
                    if result.index == 1:
                        accepted = True
                        break
                    if result.index != 0:
                        raise PairingRequired("Station rejected pairing")
                if accepted:
                    break
            if not accepted:
                raise PairingRequired("Button confirmation timed out; try pairing again")
            if on_key is not None:
                await on_key(self.serial, password, True)
        self.crypto.set_key(password, auth)
        await self.send(build_frame(BLE_BOARD, 0x5D, 0, serial, self.sync))
        # A missing or corrupt reply does not prove that the key is invalid.
        # Keep transport errors retryable; only an intact negative reply may
        # request reauthentication (which stops HA's periodic polling).
        result = await self.receive(BLE_BOARD, 0x5D, timeout=8)
        if result.index != 1:
            raise PasswordRequired("Bluetooth password was rejected")
        self.password = password

    async def read(self, board: int, index: int, length: int = 2) -> bytes:
        async with self.lock:
            await self.send(build_frame(board, 1, index, bytes((length,)), self.sync))
            result = await self.receive(board, 4, index, timeout=3)
            if len(result.data) != length:
                raise ProtocolError(f"Expected {length} bytes at {board:02x}:{index:02x}, got {len(result.data)}")
            return result.data

    async def write_u16(self, index: int, value: int):
        async with self.lock:
            await self.send(build_frame(6, 3, index, value.to_bytes(2, "little"), self.sync))
        for _ in range(3):
            await asyncio.sleep(0.2)
            readback = int.from_bytes(await self.read(6, index), "little")
            if readback == value:
                return readback
        raise ProtocolError("Station did not confirm the requested setting")


class CubeClient:
    def __init__(self, hass: HomeAssistant, address: str, name="", password=None, profile="auto", source="auto"):
        self.hass = hass
        self.address = address
        self.name = name.rstrip("\x00")
        self.password = password
        self.profile = profile
        self.serial = ""
        self.last_probe = {}
        self.source = source
        self.last_connection_source = None

    def _device(self):
        if self.source == "auto":
            return bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        return next(
            (
                candidate.ble_device
                for candidate in bluetooth.async_scanner_devices_by_address(self.hass, self.address, connectable=True)
                if candidate.scanner.source == self.source
            ),
            None,
        )

    def rssi(self):
        if self.source != "auto":
            return next(
                (
                    candidate.advertisement.rssi
                    for candidate in bluetooth.async_scanner_devices_by_address(
                        self.hass, self.address, connectable=True
                    )
                    if candidate.scanner.source == self.source
                ),
                None,
            )
        info = bluetooth.async_last_service_info(self.hass, self.address, connectable=True)
        return info.rssi if info else None

    @asynccontextmanager
    async def session(
        self,
        *,
        pair=False,
        probe=False,
        replace=False,
        on_key=None,
        on_pairing=None,
        recovery=False,
        expected_serial=None,
    ):
        profiles = list(PROFILES) if self.profile == "auto" else [self.profile]
        failure = None
        session = None
        client = None
        for profile in profiles:
            try:
                device = self._device()
                if device is None:
                    raise BleakError("Station unavailable through an active Bluetooth adapter")
                client = await establish_connection(
                    BleakClientWithServiceCache if self.source == "auto" else SourceLockedBleakClient,
                    device,
                    "Segway Cube",
                    max_attempts=2,
                    ble_device_callback=self._device,
                    **({"cube_source": self.source} if self.source != "auto" else {}),
                )
                scanner = getattr(client, "_connected_scanner", None)
                self.last_connection_source = scanner.source if scanner is not None else None
                if self.source != "auto" and self.last_connection_source != self.source:
                    raise ProtocolError("The selected Bluetooth adapter lock could not be verified")
                selected = next(
                    (
                        (client.services.get_characteristic(w), client.services.get_characteristic(n))
                        for w, n in CHARACTERISTICS
                        if client.services.get_characteristic(w) and client.services.get_characteristic(n)
                    ),
                    None,
                )
                if selected is None:
                    raise ProtocolError("No supported Segway UART characteristics")
                name = self.name
                try:
                    gatt_name = (await client.read_gatt_char(DEVICE_NAME)).decode("ascii").rstrip("\x00")
                    if gatt_name:
                        name = gatt_name
                except BleakError, UnicodeDecodeError:
                    pass
                if not name:
                    raise ProtocolError("Device name is needed for authentication")
                session = Session(client, *selected, profile)
                await client.start_notify(session.notify_char, session.notification)
                auth, serial = await session.pre_comm(name)
                self.last_probe = {
                    "profile": profile,
                    "name": name,
                    "serial": session.serial,
                    "bound": session.bound,
                    "services": [str(s.uuid) for s in client.services],
                }
                self.profile = profile
                self.name = name
                self.serial = session.serial
                if not probe:
                    if expected_serial and session.serial != expected_serial:
                        raise ProtocolError("Station serial differs from the saved pairing record")
                    try:
                        await session.authenticate(
                            auth,
                            serial,
                            self.password,
                            pair,
                            replace=replace,
                            on_key=on_key,
                            on_pairing=on_pairing,
                        )
                    except PasswordRequired:
                        if not (recovery and pair and replace):
                            raise
                        await session.authenticate(
                            auth,
                            serial,
                            None,
                            True,
                            replace=True,
                            on_key=on_key,
                            on_pairing=on_pairing,
                        )
                    self.password = session.password
                break
            except PasswordRequired, PairingRequired:
                if client is not None and client.is_connected:
                    await client.disconnect()
                raise
            except (BleakError, TimeoutError, ProtocolError) as err:
                failure = err
                _LOGGER.debug("Cube protocol profile %s failed: %s", profile, err)
                connected = client is not None and client.is_connected
                if client is not None and client.is_connected:
                    await client.disconnect()
                session = None
                if not connected:
                    # A failed radio link cannot be fixed by changing packet encryption.
                    raise ProtocolError(
                        (
                            "Selected Bluetooth adapter is unavailable or could not connect; waiting for that adapter"
                            if self.source != "auto"
                            else "Bluetooth connection failed; check proxy range and close the phone app"
                        )
                    ) from err
            except BaseException:
                # Cancellation during setup must release the proxy's scarce connection slot.
                if client is not None and client.is_connected:
                    await client.disconnect()
                raise
        if session is None:
            raise ProtocolError("Unable to establish Cube session") from failure
        try:
            yield session
        finally:
            if client is not None and client.is_connected:
                await client.disconnect()

    async def probe(self):
        async with self.session(probe=True):
            return self.last_probe
