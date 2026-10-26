"""Offline protocol tests: python -m unittest discover -s tests -v"""
import sys
import os
import types
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Emulate only the MicroPython interfaces the module uses.
if 'machine' not in sys.modules:
    machine = types.ModuleType('machine')
    machine.Pin = lambda pin: pin
    machine.UART = lambda *args, **kwargs: None
    machine.I2C = lambda *args, **kwargs: None
    sys.modules['machine'] = machine
if not hasattr(time, 'ticks_ms'):
    time.ticks_ms = lambda: int(time.monotonic() * 1000)
    time.ticks_diff = lambda a, b: a - b
    time.sleep_ms = lambda ms: time.sleep(ms / 1000)

import huskylens as h


def word(v):
    return bytes((v & 255, v >> 8))


def info(count=0, learned=0, frame=11):
    return h.HuskyLens.pack(h.RET_INFO, word(count) + word(learned) + word(frame) + b'\x00' * 4)


def block(x=100, y=150, w=20, he=30, obj_id=1):
    return h.HuskyLens.pack(h.RET_BLOCK,
                            word(x) + word(y) + word(w) + word(he) + word(obj_id))


def arrow(x0=1, y0=2, x1=3, y1=4, obj_id=5):
    return h.HuskyLens.pack(h.RET_ARROW,
                            word(x0) + word(y0) + word(x1) + word(y1) + word(obj_id))


ACK = h.HuskyLens.pack(h.RET_OK)
BUSY = h.HuskyLens.pack(h.RET_BUSY)


class FakeUART:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.incoming = bytearray()
        self.sent = []
        self.max_read = 5  # intentionally fragmented serial chunks

    def write(self, data):
        self.sent.append(bytes(data))
        if self.responses:
            self.incoming.extend(self.responses.pop(0))
        return len(data)

    def any(self):
        return len(self.incoming)

    def read(self, n=None):
        if n is None:
            n = len(self.incoming)
        n = min(n, self.max_read)
        data = bytes(self.incoming[:n])
        del self.incoming[:n]
        return data


class FakeI2C:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.incoming = bytearray()
        self.sent = []
        self.reads = []

    def writeto(self, addr, frame):
        self.sent.append((addr, bytes(frame)))
        if self.responses:
            self.incoming.extend(self.responses.pop(0))
        return len(frame)

    def readfrom(self, addr, n):
        self.reads.append((addr, n))
        data = bytes(self.incoming[:n])
        del self.incoming[:n]
        return data + bytes(n - len(data))


class TestProtocol(unittest.TestCase):
    def make_uart(self, *responses, **kw):
        bus = FakeUART(responses)
        return h.HuskyLens(uart=bus, timeout=35, **kw), bus

    def test_knock_packet(self):
        self.assertEqual(h.HuskyLens.pack(h.CMD_KNOCK), b'\x55\xaa\x11\x00\x2c\x3c')

    def test_algorithm_packet(self):
        self.assertEqual(h.HuskyLens.pack(h.CMD_ALGORITHM, word(1)),
                         b'\x55\xaa\x11\x02\x2d\x01\x00\x40')

    def test_ping(self):
        cam, bus = self.make_uart(ACK)
        self.assertTrue(cam.ping())
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_KNOCK))

    def test_ping_timeout_false(self):
        cam, _ = self.make_uart()
        self.assertFalse(cam.ping())

    def test_algorithms(self):
        for name, number in h.ALGORITHMS.items():
            cam, bus = self.make_uart(ACK)
            self.assertTrue(cam.set_algorithm(name.lower()))
            self.assertEqual(cam.algorithm, number)
            self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_ALGORITHM, word(number)))

    def test_invalid_algorithm(self):
        cam, _ = self.make_uart()
        with self.assertRaises(ValueError):
            cam.set_algorithm('linefollowing-42')
        with self.assertRaises(ValueError):
            cam.set_algorithm(7)

    def test_query_order_and_data(self):
        cam, bus = self.make_uart(info(3, 4, 65000) + block() + arrow() + block(2, 3, 4, 5, 0))
        found = cam.request()
        self.assertEqual([type(x) for x in found], [h.Block, h.Arrow, h.Block])
        self.assertEqual(cam.frame, 65000)
        self.assertEqual(cam.learned_count, 4)
        self.assertEqual(cam.blocks[0].x, 100)
        self.assertEqual(cam.blocks[0].x_center, 100)
        self.assertEqual(cam.arrows[0].x_target, 3)
        self.assertTrue(cam.has_id(5))
        self.assertTrue(cam.is_learned(4))
        self.assertEqual(cam.count(), 3)
        self.assertEqual(cam.count_blocks(), 2)
        self.assertEqual(cam.count_arrows(), 1)
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_REQUEST))

    def test_zero_results(self):
        cam, _ = self.make_uart(info(0, 0, 77))
        self.assertEqual(cam.get_arrows(), [])
        self.assertEqual(cam.frame, 77)

    def test_by_id_query(self):
        cam, bus = self.make_uart(info())
        self.assertEqual(cam.get_blocks(257), [])
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_BLOCKS_BY_ID, word(257)))

    def test_learned_queries(self):
        for kind, code in [('learned', 0x23), ('learned_blocks', 0x24), ('learned_arrows', 0x25)]:
            cam, bus = self.make_uart(info())
            cam.request(kind)
            self.assertEqual(bus.sent[0], h.HuskyLens.pack(code))

    def test_learned_by_id_not_allowed(self):
        cam, _ = self.make_uart()
        with self.assertRaises(ValueError):
            cam.request('learned', 1)

    def test_checksum_resync(self):
        invalid = bytearray(ACK)
        invalid[-1] ^= 0xFF
        cam, _ = self.make_uart(b'noise' + invalid + ACK)
        self.assertTrue(cam.ping())
        self.assertEqual(cam.bad_checksums, 1)

    def test_fragmented_info_and_records(self):
        cam, _ = self.make_uart(info(2) + arrow() + block())
        self.assertEqual(len(cam.request()), 2)

    def test_busy_retry(self):
        cam, bus = self.make_uart(BUSY, ACK, retries=1)
        self.assertTrue(cam.set_algorithm(3))
        self.assertEqual(len(bus.sent), 2)

    def test_busy_no_retry(self):
        cam, bus = self.make_uart(BUSY, retries=0)
        with self.assertRaises(h.HuskyLensBusy):
            cam.forget()
        self.assertEqual(len(bus.sent), 1)

    def test_need_pro(self):
        cam, _ = self.make_uart(h.HuskyLens.pack(h.RET_NEED_PRO))
        with self.assertRaises(h.HuskyLensNeedPro):
            cam.set_algorithm(2)

    def test_partial_results_no_stale(self):
        cam, bus = self.make_uart(info(1, 3) + block(), info(2, 3) + block())
        self.assertEqual(len(cam.request()), 1)
        with self.assertRaises(h.HuskyLensTimeout):
            cam.request()
        self.assertEqual(cam.results, [])
        self.assertEqual(cam.blocks, [])
        self.assertEqual(cam.frame, 0)

    def test_count_limit(self):
        cam, _ = self.make_uart(info(65))
        with self.assertRaises(h.HuskyLensError):
            cam.request()

    def test_all_management_commands(self):
        commands = (
            ('learn', (2,), h.CMD_LEARN, word(2)),
            ('forget', (), h.CMD_FORGET, b''),
            ('save_photo', (), h.CMD_PHOTO, b''),
            ('save_screenshot', (), h.CMD_SCREENSHOT, b''),
            ('save_model', (12,), h.CMD_SAVE_MODEL, word(12)),
            ('load_model', (12,), h.CMD_LOAD_MODEL, word(12)),
            ('clear_text', (), h.CMD_CLEAR_TEXT, b''),
        )
        for method, args, opcode, payload in commands:
            cam, bus = self.make_uart(ACK)
            self.assertTrue(getattr(cam, method)(*args))
            self.assertEqual(bus.sent[0], h.HuskyLens.pack(opcode, payload))

    def test_custom_name(self):
        cam, bus = self.make_uart(ACK)
        self.assertTrue(cam.set_custom_name(1, 'TEST'))
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_CUSTOM_NAME, b'\x01\x05TEST\x00'))

    def test_custom_text_regular(self):
        cam, bus = self.make_uart(ACK)
        cam.custom_text('TEST_1', 120, 120)
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_CUSTOM_TEXT, b'\x06\x00\x78\x78TEST_1'))

    def test_custom_text_x319(self):
        cam, bus = self.make_uart(ACK)
        cam.custom_text('HELLO', 319, 239)
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(h.CMD_CUSTOM_TEXT, b'\x05\xff\x40\xefHELLO'))

    def test_name_validation(self):
        cam, _ = self.make_uart()
        for args in [(0, 'X'), (256, 'X'), (1, 'a' * 21), (1, ''), (1, 'AÇÃO')]:
            with self.assertRaises(ValueError):
                cam.set_custom_name(*args)

    def test_text_validation(self):
        cam, _ = self.make_uart()
        for args in [('x', -1, 0), ('x', 320, 0), ('x', 0, 240), ('', 0, 0), ('É', 0, 0)]:
            with self.assertRaises(ValueError):
                cam.custom_text(*args)

    def test_is_pro_direct(self):
        cam, _ = self.make_uart(h.HuskyLens.pack(h.CMD_IS_PRO, word(0)))
        self.assertFalse(cam.is_pro())

    def test_is_pro_with_info(self):
        cam, _ = self.make_uart(info(0) + h.HuskyLens.pack(h.CMD_IS_PRO, word(1)))
        self.assertTrue(cam.is_pro())

    def test_firmware_handshake_experimental(self):
        cam, bus = self.make_uart(ACK)
        self.assertTrue(cam.firmware_handshake('0.4.1'))
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(0x3C, b'\x050.4.1'))

    def test_algorithm_prefix_compatibility(self):
        cam, _ = self.make_uart(ACK)
        self.assertTrue(cam.set_algorithm('ALGORITHM_LINE_TRACKING'))

    def test_custom_raw_command(self):
        cam, bus = self.make_uart(ACK)
        self.assertEqual(cam.raw_command(0x2C), (h.RET_OK, b''))
        self.assertEqual(bus.sent[0], h.HuskyLens.pack(0x2C))

    def test_i2c_ping(self):
        bus = FakeI2C([ACK])
        cam = h.HuskyLens(i2c=bus, timeout=50)
        self.assertTrue(cam.ping())
        self.assertEqual(bus.sent[0], (0x32, h.HuskyLens.pack(0x2C)))
        self.assertEqual(bus.reads[0], (0x32, 16))

    def test_i2c_multiple_packets_with_padding(self):
        bus = FakeI2C([info(2, 1) + block() + arrow()])
        cam = h.HuskyLens(i2c=bus, timeout=50)
        self.assertEqual(len(cam.request()), 2)
        self.assertEqual(cam.count_arrows(), 1)

    def test_i2c_bad_checksum(self):
        bad = bytearray(ACK)
        bad[-1] += 1
        bus = FakeI2C([bytes(bad) + ACK])
        cam = h.HuskyLens(i2c=bus, timeout=50)
        self.assertTrue(cam.ping())
        self.assertEqual(cam.bad_checksums, 1)

    def test_error_early_on_wrong_ack(self):
        cam, _ = self.make_uart(info())
        with self.assertRaises(h.HuskyLensError):
            cam.forget()


if __name__ == '__main__':
    unittest.main()
