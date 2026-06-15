# MiSTer Keyboard

A desktop app for relaying keyboard, mouse, and gamepad inputs to your MiSTer FPGA over the network. Built around MiSTer's `kd` (keyboard daemon), it wraps a virtual input interface and Python backend into a single standalone executable — no batch files, browser configuration, or separate script launches required.

## Features

- **Single executable** — one `.exe` bundles the UI and backend with no external dependencies
- **Normal mode** — on-screen keyboard, mouse pad, and gamepad UI send inputs via WebSocket while the app is focused; physical keyboard also works when the app window is in focus
- **Background relay mode** — minimizes the app and captures all physical keyboard and mouse input system-wide, routing it to MiSTer transparently
- **Auto-reconnect** — detects and recovers from dropped kd connections automatically
- **Persistent IP** — remembers the last MiSTer IP address between sessions
- **Mouse relay** — joystick-style mouse pad with adjustable sensitivity; left, middle, and right click; scroll
- **Game controller** — D-pad, action buttons, shoulders, spinner wheel, COIN/SERVICE, turbo mode; supports PC/DOS and Console (RetroPad) layouts
- **Shortcuts** — one-click combos for common actions (Start Menu, Task Manager, Alt+Tab, Copy, Paste, Cut, Undo, Select All, Save, MiSTer OSD)

## Hotkeys

| Combo | Action |
|---|---|
| `Ctrl+Alt+Shift+M` | Toggle background relay mode on/off |
| `Ctrl+Alt+Shift+F` | Open MiSTer OSD (Win+F12 substitute for background mode) |

## Architecture

```
┌──────────────────────────────────────┐              ┌─────────────────┐
│           Desktop App (app.exe)      │              │   MiSTer FPGA   │
│                                      │              │                 │
│  ┌─────────────────────────────────┐ │              │  ┌───────────┐  │
│  │   HTML UI (mister-keyboard.html)│ │              │  │ kd daemon │  │
│  │   WebSocket → ws://127.0.0.1   │ │  TCP :8064   │  │ :8064     │  │
│  └──────────────┬──────────────────┘ ├─────────────►│  └───────────┘  │
│                 │                    │              │                 │
│  ┌──────────────▼──────────────────┐ │              └─────────────────┘
│  │  Python backend (asyncio)       │ │
│  │  - Embedded WebSocket proxy     │ │
│  │  - kd TCP connection + watchdog │ │
│  │  - pynput keyboard/mouse relay  │ │
│  │  - Window management (Win32)    │ │
│  └─────────────────────────────────┘ │
└──────────────────────────────────────┘
```

## Setup

### 1. MiSTer FPGA

The app requires the `kd` binary to be running on your MiSTer.

1. Obtain the `kd` binary and place it at `/media/fat/linux/kd`
2. Make it executable: `chmod +x /media/fat/linux/kd`
3. Add it to your startup script so it launches automatically at boot:

```sh
# /media/fat/linux/user-startup.sh
# Add this line — the sleep gives uinput time to initialize first
sleep 5 && /media/fat/linux/kd &
```

4. Verify it's running: `ps aux | grep kd`
5. Test it manually: `echo "t 30" | nc 127.0.0.1 8064` — an `a` should appear on screen

### 2. Windows

Download the latest `app.exe` from [Releases](../../releases) and run it. No installation required.

## Usage

1. Launch `app.exe`
2. Enter your MiSTer's IP address in the **MISTER IP** field
3. Click **Connect** — the dot turns green when connected
4. Use the on-screen keyboard, mouse pad, or gamepad controls
5. For physical keyboard/mouse relay, click any on-screen key first to focus the keyboard area, then type freely
6. Press **Go Background Mode** (or `Ctrl+Alt+Shift+M`) to minimize and relay all input system-wide

## Building from Source

### Prerequisites

```
pip install websockets pynput pyinstaller
```

### Dependencies

| Package | Purpose |
|---|---|
| `websockets` | WebSocket server for browser↔Python communication |
| `pynput` | Global keyboard and mouse capture |
| `pyinstaller` | Packaging into a standalone executable |

### Run without compiling

```sh
python app.py
```

### Compile on Windows

```sh
pyinstaller --clean --onefile --noconsole \
  --hidden-import pynput.keyboard._win32 \
  --hidden-import pynput.mouse._win32 \
  --add-data "mister-keyboard.html;." \
  app.py
```

The compiled executable will be in the `dist/` folder.

### Compile on macOS / Linux

```sh
pyinstaller --clean --onefile --noconsole \
  --hidden-import pynput.keyboard._xorg \
  --hidden-import pynput.mouse._xorg \
  --add-data "mister-keyboard.html:." \
  app.py
```

> **Note:** The app uses Win32 APIs for window management and focus stealing — full functionality is only supported on Windows. macOS/Linux builds will relay inputs but window minimize/restore behavior may differ.

## Troubleshooting

**Can't connect / stays on Connect button**
- Verify `kd` is running on the MiSTer: `ps aux | grep kd`
- Check the IP address is correct: `ip addr | grep 192.168`
- Make sure nothing else is using port 8064 on the MiSTer: `netstat -tlnp | grep 8064`
- Try sending a test input directly: `echo "t 30" | nc 127.0.0.1 8064`

**Keys stop working after multiple mode switches**
- Disconnect and reconnect in the UI to reset the kd connection
- If kd becomes unresponsive, restart it on the MiSTer: `kill $(pgrep kd) && /media/fat/linux/kd &`

**App doesn't close after clicking Quit**
- Must be connected to MiSTer for the Quit button to send the shutdown signal
- Force close via Task Manager if needed, then relaunch

**Win+F12 doesn't open the MiSTer OSD in background mode**
- Windows intercepts the Win key before pynput can capture it
- Use `Ctrl+Alt+Shift+F` instead — this sends the equivalent Win+F12 signal to the MiSTer

**MiSTer IP keeps changing**
- Set a DHCP reservation in your router to give your MiSTer a fixed IP (bind by MAC address)
- Find your MiSTer's MAC: `ip link show eth0` or `ip link show wlan0`
