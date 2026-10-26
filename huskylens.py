"""HuskyLens 1 (original) driver for ESP32 MicroPython, UART and I2C.

Wire protocol version 0.5.1: https://github.com/HuskyLens/HUSKYLENSArduino
No dependencies beyond MicroPython's machine/time modules.

The device does not expose raw camera frames through this protocol.
"""
from machine import Pin, UART, I2C
from time import ticks_ms, ticks_diff, sleep_ms

__version__ = '1.0.0-rc2'

ALGORITHMS = {
    'FACE_RECOGNITION': 0,
    'OBJECT_TRACKING': 1,
    'OBJECT_RECOGNITION': 2,
    'LINE_TRACKING': 3,
    'COLOR_RECOGNITION': 4,
    'TAG_RECOGNITION': 5,
    'OBJECT_CLASSIFICATION': 6,
}

# Official serial packet commands (NOT the HuskyLens 2 protocol).
CMD_REQUEST = 0x20
CMD_BLOCKS = 0x21
CMD_ARROWS = 0x22
CMD_LEARNED = 0x23
CMD_LEARNED_BLOCKS = 0x24
CMD_LEARNED_ARROWS = 0x25
CMD_BY_ID = 0x26
CMD_BLOCKS_BY_ID = 0x27
CMD_ARROWS_BY_ID = 0x28
RET_INFO = 0x29
RET_BLOCK = 0x2A
RET_ARROW = 0x2B
CMD_KNOCK = 0x2C
CMD_ALGORITHM = 0x2D
RET_OK = 0x2E
CMD_CUSTOM_NAME = 0x2F
CMD_PHOTO = 0x30
CMD_SAVE_MODEL = 0x32
CMD_LOAD_MODEL = 0x33
CMD_CUSTOM_TEXT = 0x34
CMD_CLEAR_TEXT = 0x35
CMD_LEARN = 0x36
CMD_FORGET = 0x37
CMD_SCREENSHOT = 0x39
CMD_IS_PRO = 0x3B
CMD_FIRMWARE_HANDSHAKE = 0x3C
RET_BUSY = 0x3D
RET_NEED_PRO = 0x3E

_HEADER = b'\x55\xaa\x11'
_QUERY_COMMANDS = {
    'all': (CMD_REQUEST, CMD_BY_ID),
    'blocks': (CMD_BLOCKS, CMD_BLOCKS_BY_ID),
    'arrows': (CMD_ARROWS, CMD_ARROWS_BY_ID),
    'learned': (CMD_LEARNED, None),
    'learned_blocks': (CMD_LEARNED_BLOCKS, None),
    'learned_arrows': (CMD_LEARNED_ARROWS, None),
}


def _u16(buf, offset=0):
    return buf[offset] | (buf[offset + 1] << 8)


def _word(value, label='valor'):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0 or value > 65535:
        raise ValueError('{} deve estar entre 0 e 65535'.format(label))
    return bytes((value & 255, (value >> 8) & 255))


def _byte(value, label='valor'):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 255:
        raise ValueError('{} deve estar entre 0 e 255'.format(label))
    return value


def _ascii(text, maximum, label):
    if not isinstance(text, str):
        raise ValueError('{} precisa ser texto'.format(label))
    try:
        encoded = text.encode('ascii')
    except UnicodeError:
        raise ValueError('{}: use apenas caracteres ASCII'.format(label))
    if not encoded or len(encoded) > maximum or b'\x00' in encoded:
        raise ValueError('{}: use de 1 a {} caracteres ASCII'.format(label, maximum))
    return encoded


class HuskyLensError(OSError):
    """Communication/protocol fault."""


class HuskyLensTimeout(HuskyLensError):
    """No complete response received in the configured interval."""


class HuskyLensBusy(HuskyLensError):
    """Camera returned BUSY more times than the configured retry limit."""


class HuskyLensNeedPro(HuskyLensError):
    """Camera rejects a Pro-only command."""


class Block:
    """Recognized rectangle. x/y are its CENTER, not top-left."""
    def __init__(self, data):
        self.x = _u16(data, 0)
        self.y = _u16(data, 2)
        self.width = _u16(data, 4)
        self.height = _u16(data, 6)
        self.id = _u16(data, 8)

    @property
    def x_center(self):
        return self.x

    @property
    def y_center(self):
        return self.y

    def __repr__(self):
        return 'Block(id={}, x={}, y={}, width={}, height={})'.format(
            self.id, self.x, self.y, self.width, self.height)


class Arrow:
    """Line-tracking vector in the camera's 320x240 coordinate system."""
    def __init__(self, data):
        self.x_origin = _u16(data, 0)
        self.y_origin = _u16(data, 2)
        self.x_target = _u16(data, 4)
        self.y_target = _u16(data, 6)
        self.id = _u16(data, 8)

    def __repr__(self):
        return 'Arrow(id={}, from=({}, {}), to=({}, {}))'.format(
            self.id, self.x_origin, self.y_origin, self.x_target, self.y_target)


class HuskyLens:
    """Original HuskyLens using UART (default) or I2C.

    Examples:
      camera = HuskyLens(tx=17, rx=16)              # UART2/9600
      camera = HuskyLens(interface='i2c', sda=21, scl=22)
      camera = HuskyLens(uart=my_uart)               # already configured UART
      camera = HuskyLens(i2c=my_i2c)                 # already configured I2C

    NOTE: set the camera's 'Protocol Type' to the same transport in its menu.
    """
    HEADER = _HEADER
    I2C_ADDRESS = 0x32

    def __init__(self, tx=17, rx=16, uart_id=2, baudrate=9600,
                 timeout=700, interface='uart', sda=21, scl=22,
                 i2c_id=0, i2c_freq=100000, address=0x32,
                 uart=None, i2c=None, retries=1, max_results=64,
                 i2c_chunk_size=16):
        if timeout <= 0 or retries < 0 or max_results < 1:
            raise ValueError('timeout, retries ou max_results invalidos')
        if not 1 <= i2c_chunk_size <= 32:
            raise ValueError('i2c_chunk_size deve estar entre 1 e 32')
        self.timeout = timeout
        self.retries = retries
        self.max_results = max_results
        self.i2c_chunk_size = i2c_chunk_size
        self.address = _byte(address, 'address')
        if uart is not None and i2c is not None:
            raise ValueError('use apenas um transporte')
        if i2c is not None:
            interface = 'i2c'
        elif uart is not None:
            interface = 'uart'
        self.interface = interface.lower()
        if self.interface == 'uart':
            self.uart = uart if uart is not None else UART(
                uart_id, baudrate=baudrate, tx=Pin(tx), rx=Pin(rx), timeout=0)
            self.i2c = None
        elif self.interface == 'i2c':
            self.uart = None
            self.i2c = i2c if i2c is not None else I2C(
                i2c_id, sda=Pin(sda), scl=Pin(scl), freq=i2c_freq)
        else:
            raise ValueError('interface deve ser uart ou i2c')
        self._rx = bytearray()
        self.blocks = []
        self.arrows = []
        self.results = []
        self.learned_count = 0
        self.frame = 0
        self.algorithm = None  # last algorithm selected through this driver
        self.last_command = None
        self.last_payload = None
        self.bad_checksums = 0

    @staticmethod
    def pack(command, payload=b''):
        """Build official wire frame (also useful for protocol diagnostics)."""
        _byte(command, 'command')
        payload = bytes(payload)
        if len(payload) > 255:
            raise ValueError('payload deve ter no maximo 255 bytes')
        frame = _HEADER + bytes((len(payload), command)) + payload
        return frame + bytes((sum(frame) & 0xFF,))

    def _write(self, packet):
        try:
            if self.interface == 'uart':
                written = self.uart.write(packet)
                if written is not None and written != len(packet):
                    raise HuskyLensError('escrita UART incompleta')
            else:
                self.i2c.writeto(self.address, packet)
        except OSError as err:
            if isinstance(err, HuskyLensError):
                raise
            raise HuskyLensError('falha ao escrever {}: {}'.format(self.interface, err))

    def _read_data(self):
        if self.interface == 'uart':
            available = self.uart.any()
            if available:
                return self.uart.read(min(available, 256)) or b''
            return b''
        # As in the official Arduino driver, read 16 bytes per transaction.
        # Camera firmware may return zero padding; the parser discards it.
        try:
            return self.i2c.readfrom(self.address, self.i2c_chunk_size)
        except OSError:
            # I2C may NACK briefly while a recognition frame is being prepared.
            return b''

    def _prepare(self):
        self._rx = bytearray()
        if self.interface == 'uart':
            # Drop bytes from an earlier/incomplete transaction.
            remaining = 1024
            while remaining > 0:
                available = self.uart.any()
                if not available:
                    break
                count = min(available, remaining, 256)
                self.uart.read(count)
                remaining -= count
        # I2C has no portable FIFO-flush command, so do not read preemptively.

    def _unpack_available(self):
        buf = self._rx
        while len(buf) >= 3:
            if buf[0:3] != _HEADER:
                # MicroPython bytearray may not support item deletion.
                # Rebind the unread suffix instead of using `del`.
                buf = buf[1:]
                self._rx = buf
                continue
            if len(buf) < 6:
                return None
            length = buf[3]
            full = length + 6
            if len(buf) < full:
                return None
            if (sum(buf[:full - 1]) & 0xFF) != buf[full - 1]:
                self.bad_checksums += 1
                # Search next header without bytearray item deletion.
                buf = buf[1:]
                self._rx = buf
                continue
            command = buf[4]
            payload = bytes(buf[5:full - 1])
            self._rx = buf[full:]
            return command, payload
        return None

    def _read_packet(self, timeout=None):
        if timeout is None:
            timeout = self.timeout
        start = ticks_ms()
        while ticks_diff(ticks_ms(), start) < timeout:
            packet = self._unpack_available()
            if packet is not None:
                self.last_command, self.last_payload = packet
                return packet
            new = self._read_data()
            if new:
                self._rx.extend(new)
                # Bound buffering for broken/noisy link. Keep plausible tails.
                if len(self._rx) > 768:
                    self._rx = self._rx[-260:]
            else:
                sleep_ms(2)
            if self.interface == 'i2c':
                sleep_ms(2)
        raise HuskyLensTimeout('HuskyLens: timeout {}'.format(self.interface.upper()))

    def _first_response(self, command, payload=b''):
        """Send one request; retry ONLY on explicit BUSY responses."""
        for attempt in range(self.retries + 1):
            self._prepare()
            self._write(self.pack(command, payload))
            reply_cmd, reply_data = self._read_packet()
            if reply_cmd == RET_NEED_PRO:
                raise HuskyLensNeedPro('comando exige HuskyLens Pro')
            if reply_cmd == RET_BUSY:
                if attempt < self.retries:
                    sleep_ms(30)
                    continue
                raise HuskyLensBusy('HuskyLens ocupada')
            return reply_cmd, reply_data
        raise HuskyLensBusy('HuskyLens ocupada')

    def _ok(self, command, payload=b''):
        response, data = self._first_response(command, payload)
        if response != RET_OK or data:
            raise HuskyLensError('resposta inesperada: 0x{:02x}'.format(response))
        return True

    def ping(self):
        try:
            return self._ok(CMD_KNOCK)
        except HuskyLensError:
            return False

    def set_algorithm(self, algorithm):
        """Choose any of the 7 native detection algorithms by name or 0..6."""
        if isinstance(algorithm, str):
            key = algorithm.upper().replace(' ', '_').replace('-', '_')
            if key.startswith('ALGORITHM_'):
                key = key[10:]
            if key not in ALGORITHMS:
                raise ValueError('algoritmo invalido: {}'.format(algorithm))
            algorithm = ALGORITHMS[key]
        if not isinstance(algorithm, int) or isinstance(algorithm, bool) or not 0 <= algorithm <= 6:
            raise ValueError('algoritmo deve ser 0..6')
        self._ok(CMD_ALGORITHM, _word(algorithm))
        self.algorithm = algorithm
        return True

    def request(self, kind='all', object_id=None):
        """Fetch detections; updates .blocks, .arrows, .results, .frame, .learned_count.

        kind: all, blocks, arrows, learned, learned_blocks, learned_arrows
        object_id: 0..65535 when kind is all/blocks/arrows.
        The return ordering matches the camera's reported sequence.
        """
        if kind not in _QUERY_COMMANDS:
            raise ValueError('consulta desconhecida: {}'.format(kind))
        normal, by_id = _QUERY_COMMANDS[kind]
        if object_id is not None and by_id is None:
            raise ValueError('filtro por ID nao disponivel para {}'.format(kind))
        command = normal if object_id is None else by_id
        payload = b'' if object_id is None else _word(object_id, 'object_id')
        # Failed queries must not leave stale detections.
        self.blocks = []
        self.arrows = []
        self.results = []
        self.learned_count = 0
        self.frame = 0
        response, data = self._first_response(command, payload)
        if response != RET_INFO or len(data) != 10:
            raise HuskyLensError('cabecalho de resultados invalido 0x{:02x}'.format(response))
        count = _u16(data, 0)
        learned_count = _u16(data, 2)
        frame = _u16(data, 4)
        if count > self.max_results:
            raise HuskyLensError('numero de resultados {} maior que {}'.format(count, self.max_results))
        items = []
        blocks = []
        arrows = []
        for _ in range(count):
            item_cmd, item_data = self._read_packet()
            if len(item_data) != 10:
                raise HuskyLensError('payload de deteccao invalido')
            if item_cmd == RET_BLOCK:
                item = Block(item_data)
                blocks.append(item)
            elif item_cmd == RET_ARROW:
                item = Arrow(item_data)
                arrows.append(item)
            else:
                raise HuskyLensError('tipo de deteccao inesperado 0x{:02x}'.format(item_cmd))
            items.append(item)
        # Commit only after complete response.
        self.blocks, self.arrows, self.results = blocks, arrows, items
        self.learned_count, self.frame = learned_count, frame
        return self.results

    def get_blocks(self, object_id=None):
        self.request('blocks', object_id)
        return self.blocks

    def get_arrows(self, object_id=None):
        self.request('arrows', object_id)
        return self.arrows

    def get_learned(self):
        return self.request('learned')

    def get_learned_blocks(self):
        self.request('learned_blocks')
        return self.blocks

    def get_learned_arrows(self):
        self.request('learned_arrows')
        return self.arrows

    def count(self):
        """Number of detections in the most recent successful request."""
        return len(self.results)

    def count_blocks(self):
        return len(self.blocks)

    def count_arrows(self):
        return len(self.arrows)

    def is_learned(self, object_id=None):
        """Metadata of the last query; learned count is not object detection."""
        if object_id is None:
            return self.learned_count > 0
        _word(object_id, 'object_id')
        return 1 <= object_id <= self.learned_count

    def has_id(self, object_id):
        """True if latest results include a detection with this ID."""
        _word(object_id, 'object_id')
        return any(item.id == object_id for item in self.results)

    def learn(self, object_id):
        return self._ok(CMD_LEARN, _word(object_id, 'object_id'))

    def forget(self):
        """Erase learned IDs of the *currently selected algorithm*."""
        return self._ok(CMD_FORGET)

    def set_custom_name(self, object_id, name):
        """Assign an ASCII name to a learned ID (1..255, max 20 bytes)."""
        object_id = _byte(object_id, 'object_id')
        if object_id == 0:
            raise ValueError('object_id deve ser maior que zero')
        encoded = _ascii(name, 20, 'nome')
        data = bytes((object_id, len(encoded) + 1)) + encoded + b'\x00'
        return self._ok(CMD_CUSTOM_NAME, data)

    def custom_text(self, text, x=0, y=0):
        """Overlay ASCII text (<=20 bytes) on HuskyLens screen, up to 10 labels.

        Coordinates of label: x 0..319, y 0..239.
        Official x encoding uses FF+remainder modulo 255 when x>=255.
        """
        encoded = _ascii(text, 20, 'texto')
        if not isinstance(x, int) or isinstance(x, bool) or not 0 <= x <= 319:
            raise ValueError('x deve estar entre 0 e 319')
        if not isinstance(y, int) or isinstance(y, bool) or not 0 <= y <= 239:
            raise ValueError('y deve estar entre 0 e 239')
        flag = 255 if x >= 255 else 0
        data = bytes((len(encoded), flag, x % 255, y)) + encoded
        return self._ok(CMD_CUSTOM_TEXT, data)

    def clear_text(self):
        return self._ok(CMD_CLEAR_TEXT)

    def save_photo(self):
        """Capture scene photo to camera's microSD (not transfer to ESP32)."""
        return self._ok(CMD_PHOTO)

    def save_screenshot(self):
        """Save HuskyLens screen/UI screenshot to camera's microSD."""
        return self._ok(CMD_SCREENSHOT)

    def save_model(self, slot=1):
        """Back up current algorithm model to camera microSD, slot 0..65535."""
        return self._ok(CMD_SAVE_MODEL, _word(slot, 'slot'))

    def load_model(self, slot=1):
        """Restore current algorithm model from camera microSD, slot 0..65535."""
        return self._ok(CMD_LOAD_MODEL, _word(slot, 'slot'))

    def is_pro(self):
        """Check Pro model. Relevant only if supported by camera firmware.

        Official protocol specifies a 0x3B response carrying a 16-bit flag;
        some versions may return a different sequence or no reply.
        """
        response, data = self._first_response(CMD_IS_PRO)
        if response == RET_INFO:
            # Arduino implementation waits for INFO then a separate 0x3B.
            response, data = self._read_packet()
        if response != CMD_IS_PRO or len(data) != 2:
            raise HuskyLensError('resposta IS_PRO desconhecida (0x{:02x})'.format(response))
        return _u16(data) != 0

    def firmware_handshake(self, expected_version):
        """EXPERIMENTAL 0x3C handshake found in official Arduino source.

        Sends an EXPECTED version string; DOES NOT read the installed firmware
        version and DOES NOT update firmware. Older original HuskyLens firmware
        may ignore this command. Use for diagnostics only.
        """
        encoded = _ascii(expected_version, 20, 'expected_version')
        return self._ok(CMD_FIRMWARE_HANDSHAKE,
                        bytes((len(encoded),)) + encoded)

    def raw_command(self, command, payload=b''):
        """Advanced: send a protocol command and return (reply_cmd, bytes).

        Not a means of accessing undocumented configuration registers.
        Unsafe/unknown commands are the caller's responsibility.
        """
        return self._first_response(command, payload)

