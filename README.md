# 8BitDo Pro 2 A-mode HID Daemon

This daemon listens to Bluetooth HCI ACL traffic for 8BitDo Pro 2 A-mode HID
reports and exposes one or more virtual gamepad devices through `/dev/uinput`.

## Runtime requirements

- Linux with Bluetooth stack enabled.
- `systemd`.
- `/dev/uinput` available.
- Root privileges (required by the daemon).

## Install from AUR

```bash
yay -S 8bitdo-pro2-a-mode-hid-daemon
```

or:

```bash
paru -S 8bitdo-pro2-a-mode-hid-daemon
```

## Manual setup

Run directly:

```bash
sudo python 8bitdo-pro2-a-mode-hid-daemon.py
```

Or install along with systemd service:

```bash
sudo install -Dm755 8bitdo-pro2-a-mode-hid-daemon.py /usr/bin/8bitdo-pro2-a-mode-hid-daemon
sudo cp 8bitdo-pro2-a-mode-hid-daemon.service /etc/systemd/system/8bitdo-pro2-a-mode-hid-daemon.service
sudo systemctl daemon-reload
sudo systemctl enable --now 8bitdo-pro2-a-mode-hid-daemon.service
```
