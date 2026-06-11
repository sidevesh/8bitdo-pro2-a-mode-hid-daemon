#!/usr/bin/python3
# SPDX-License-Identifier: MIT
#
# 8BitDo Pro 2 A-mode Bluetooth HID to uinput daemon
#
# Copyright (c) 2026 Swapnil Devesh <me@sidevesh.com>

import sys, os, socket, struct, fcntl, time, signal, logging, select

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('8bitdo')

# ── HCI ───────────────────────────────────────────────────────────────────────
BTPROTO_HCI = socket.BTPROTO_HCI
SOL_HCI     = socket.SOL_HCI
HCI_FILTER  = 2
HCI_ACL_PKT = 0x02
HCI_EVT_PKT = 0x04
EVT_DISCONN_COMPLETE = 0x05

RECONNECT_DELAY = 3
IDLE_TIMEOUT = 2.0

DEVICE_NAME = '8BitDo Pro 2'

# ── uinput ────────────────────────────────────────────────────────────────────
UINPUT_PATH    = '/dev/uinput'
UI_SET_EVBIT   = 0x40045564
UI_SET_KEYBIT  = 0x40045565
UI_SET_ABSBIT  = 0x40045567
UI_DEV_CREATE  = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN=0x00; EV_KEY=0x01; EV_ABS=0x03; SYN_REPORT=0

ABS_X=0x00; ABS_Y=0x01; ABS_Z=0x02; ABS_RX=0x03; ABS_RY=0x04; ABS_RZ=0x05
ABS_HAT0X=0x10; ABS_HAT0Y=0x11

BTN_SOUTH=0x130; BTN_EAST=0x131; BTN_NORTH=0x133; BTN_WEST=0x134
BTN_TL=0x136;   BTN_TR=0x137;   BTN_TL2=0x138;   BTN_TR2=0x139
BTN_SELECT=0x13a; BTN_START=0x13b; BTN_MODE=0x13c
BTN_THUMBL=0x13d; BTN_THUMBR=0x13e

ALL_BUTTONS = [BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST,
               BTN_TL, BTN_TR, BTN_TL2, BTN_TR2,
               BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR]
ALL_AXES = [ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ, ABS_HAT0X, ABS_HAT0Y]

UINPUT_DEV_FMT  = '80sHHHHI' + 'i' * 256
INPUT_EVENT_FMT = 'QQHHi'

HAT_MAP = {
    0: ( 0, -1),  1: ( 1, -1),  2: ( 1,  0),  3: ( 1,  1),
    4: ( 0,  1),  5: (-1,  1),  6: (-1,  0),  7: (-1, -1),
    8: ( 0,  0),
}

# ── uinput device ─────────────────────────────────────────────────────────────

class UInputDevice:
    def __init__(self, name=DEVICE_NAME):
        self._fd = os.open(UINPUT_PATH, os.O_WRONLY | os.O_NONBLOCK)
        self._prev = {}
        self._setup(name)

    def _ioctl(self, req, arg=0):
        fcntl.ioctl(self._fd, req, arg)

    def _setup(self, name):
        self._ioctl(UI_SET_EVBIT, EV_KEY)
        for btn in ALL_BUTTONS:
            self._ioctl(UI_SET_KEYBIT, btn)
        self._ioctl(UI_SET_EVBIT, EV_ABS)
        for ax in ALL_AXES:
            self._ioctl(UI_SET_ABSBIT, ax)
        self._ioctl(UI_SET_EVBIT, EV_SYN)

        absmax=[0]*64; absmin=[0]*64; absfuzz=[0]*64; absflat=[0]*64
        for ax in (ABS_X, ABS_Y, ABS_RX, ABS_RY):
            absmax[ax]=255; absfuzz[ax]=2; absflat[ax]=8
        for ax in (ABS_Z, ABS_RZ):
            absmax[ax]=255
        for ax in (ABS_HAT0X, ABS_HAT0Y):
            absmax[ax]=1; absmin[ax]=-1

        udev = struct.pack(UINPUT_DEV_FMT,
            name.encode()[:79], 5, 0x054c, 0x05c4, 0x0100, 0,
            *absmax, *absmin, *absfuzz, *absflat)
        os.write(self._fd, udev)
        self._ioctl(UI_DEV_CREATE)
        time.sleep(0.2)
        log.info('uinput device created: %s', name)

    def _emit(self, ev_type, code, value):
        os.write(self._fd, struct.pack(INPUT_EVENT_FMT, 0, 0, ev_type, code, value))

    def sync(self):
        self._emit(EV_SYN, SYN_REPORT, 0)

    def key(self, code, value):
        if self._prev.get(('k', code)) != value:
            self._emit(EV_KEY, code, value)
            self._prev[('k', code)] = value

    def abs(self, code, value):
        if self._prev.get(('a', code)) != value:
            self._emit(EV_ABS, code, value)
            self._prev[('a', code)] = value

    def close(self):
        try: self._ioctl(UI_DEV_DESTROY)
        except OSError: pass
        os.close(self._fd)
        log.info('uinput device destroyed')

# ── HID report parser ─────────────────────────────────────────────────────────

def parse_and_emit(data, udev):
    """
    8BitDo Pro 2 A-mode report (confirmed from packet capture):
    [a1] 01  lx  ly  lt  rt  b0  b1  b2  rx  ry
    b0: dpad(3:0) A(4) B(5) Y(6) X(7)   dpad: 0=U 2=R 4=D 6=L 8=C
    b1: L1(0) R1(1) L2(2) R2(3) Sel(4) Sta(5) Home(6) L3(7)
    b2: R3(0)
    """
    if data[0] == 0xa1:
        data = data[1:]
    if len(data) < 10 or data[0] != 0x01:
        return

    lx,ly,lt,rt = data[1],data[2],data[3],data[4]
    b0,b1,b2    = data[5],data[6],data[7]
    rx,ry       = data[8],data[9]

    udev.abs(ABS_X,  lx);  udev.abs(ABS_Y,  ly)
    udev.abs(ABS_RX, rx);  udev.abs(ABS_RY, ry)
    udev.abs(ABS_Z,  lt);  udev.abs(ABS_RZ, rt)

    hx, hy = HAT_MAP.get(b0 & 0x0f, (0, 0))
    udev.abs(ABS_HAT0X, hx); udev.abs(ABS_HAT0Y, hy)

    udev.key(BTN_SOUTH,  int(bool(b0 & 0x10)))
    udev.key(BTN_EAST,   int(bool(b0 & 0x20)))
    udev.key(BTN_WEST,   int(bool(b0 & 0x80)))
    udev.key(BTN_NORTH,  int(bool(b0 & 0x40)))
    udev.key(BTN_TL,     int(bool(b1 & 0x01)))
    udev.key(BTN_TR,     int(bool(b1 & 0x02)))
    udev.key(BTN_TL2,    int(bool(b1 & 0x04)))
    udev.key(BTN_TR2,    int(bool(b1 & 0x08)))
    udev.key(BTN_SELECT, int(bool(b1 & 0x10)))
    udev.key(BTN_START,  int(bool(b1 & 0x20)))
    udev.key(BTN_THUMBL, int(bool(b1 & 0x80)))
    udev.key(BTN_THUMBR, int(bool(b2 & 0x01)))
    udev.key(BTN_MODE,   int(bool(b1 & 0x40)))

    udev.sync()

# ── packet parsing ────────────────────────────────────────────────────────────

def is_hid_report(raw):
    """
    Return ACL handle if this packet contains our HID report, else None.
    Packet: 02 hh hh ll ll ll ll cc cc a1 01 ...
    """
    if len(raw) < 10 or raw[0] != HCI_ACL_PKT:
        return None
    payload = raw[9:]
    if len(payload) >= 2 and payload[0] == 0xa1 and payload[1] == 0x01:
        return struct.unpack_from('<H', raw, 1)[0] & 0x0fff
    return None

def get_disconnect_handle(raw):
    """
    Return ACL handle if this is EVT_DISCONN_COMPLETE(success), else None.
    EVT_DISCONN_COMPLETE: 04 05 04 status handle(2LE) reason
    """
    if len(raw) < 7 or raw[0] != HCI_EVT_PKT or raw[1] != EVT_DISCONN_COMPLETE:
        return None
    if raw[3] != 0x00:   # status != success
        return None
    return struct.unpack_from('<H', raw, 4)[0] & 0x0fff

# ── HCI socket ────────────────────────────────────────────────────────────────

def open_hci_socket(hci_dev):
    s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, BTPROTO_HCI)
    filt = struct.pack('IQH', 0xffffffff, 0xffffffffffffffff, 0)
    s.setsockopt(SOL_HCI, HCI_FILTER, filt)
    s.bind((hci_dev,))
    return s

def list_hci_adapters():
    adapters = []
    try:
        for name in os.listdir('/sys/class/bluetooth'):
            if name.startswith('hci') and name[3:].isdigit():
                adapters.append(int(name[3:]))
    except OSError:
        pass
    return sorted(adapters)

def choose_hci_adapters():
    adapters = list_hci_adapters()
    if not adapters:
        raise RuntimeError('No HCI adapters found under /sys/class/bluetooth')
    return adapters

# ── main loop ─────────────────────────────────────────────────────────────────

def run():
    running = True
    hci_devs = choose_hci_adapters()

    def _stop(sig, frame):
        nonlocal running
        log.info('Signal %d — shutting down', sig)
        running = False

    signal.signal(signal.SIGINT,  _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info('Monitoring HCI adapters: %s', ', '.join(f'hci{d}' for d in hci_devs))
    log.info('Controllers can be connected before or after starting this daemon')

    while running:
        hci_socks = {}
        sock_to_dev = {}
        sessions  = {}
        free_slots = set()
        next_slot = 1

        try:
            for dev in hci_devs:
                s = open_hci_socket(dev)
                hci_socks[dev] = s
                sock_to_dev[s] = dev

            log.info('Waiting for HID reports ...')

            while running:
                ready, _, _ = select.select(list(hci_socks.values()), [], [], 1.0)
                if not ready:
                    now = time.monotonic()
                    stale_keys = [
                        key for key, state in sessions.items()
                        if now - state['last_hid_time'] > IDLE_TIMEOUT
                    ]
                    for key in stale_keys:
                        state = sessions[key]
                        log.info('hci%d handle %d idle timeout — controller disconnected', state['hci_dev'], state['handle'])
                        free_slots.add(state['slot'])
                        state['udev'].close()
                        del sessions[key]
                    continue

                for rsock in ready:
                    hci_dev_for_pkt = sock_to_dev[rsock]
                    raw = rsock.recv(1024)

                    # ── watch for disconnect ──────────────────────────────
                    disc_handle = get_disconnect_handle(raw)
                    disc_key = (hci_dev_for_pkt, disc_handle) if disc_handle is not None else None
                    if disc_key is not None and disc_key in sessions:
                        log.info('Controller disconnected on hci%d ACL handle %d', hci_dev_for_pkt, disc_handle)
                        free_slots.add(sessions[disc_key]['slot'])
                        sessions[disc_key]['udev'].close()
                        del sessions[disc_key]
                        continue

                    # ── process matching HID report ───────────────────────
                    handle = is_hid_report(raw)
                    if handle is None:
                        continue
                    session_key = (hci_dev_for_pkt, handle)

                    if session_key not in sessions:
                        if free_slots:
                            slot = min(free_slots)
                            free_slots.remove(slot)
                        else:
                            slot = next_slot
                            next_slot += 1

                        name = DEVICE_NAME if slot == 1 else f'{DEVICE_NAME} #{slot}'
                        sessions[session_key] = {
                            'udev': UInputDevice(name),
                            'slot': slot,
                            'last_hid_time': time.monotonic(),
                            'hci_dev': hci_dev_for_pkt,
                            'handle': handle,
                        }
                        log.info('Controller detected on hci%d ACL handle %d (slot %d)', hci_dev_for_pkt, handle, slot)

                    sessions[session_key]['last_hid_time'] = time.monotonic()
                    parse_and_emit(raw[9:], sessions[session_key]['udev'])

        except OSError as e:
            log.error('HCI error: %s', e)

        finally:
            for s in hci_socks.values():
                try: s.close()
                except OSError: pass
            for state in sessions.values():
                state['udev'].close()
            sessions.clear()

        if running:
            log.info('Restarting in %ds ...', RECONNECT_DELAY)
            time.sleep(RECONNECT_DELAY)

    log.info('Daemon exited cleanly')


def main():
    if os.geteuid() != 0:
        sys.exit('Must run as root')
    run()

if __name__ == '__main__':
    main()
