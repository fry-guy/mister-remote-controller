# MiSTer Remote Input App

# MiSTer Input Link

A lightweight desktop application that allows you to relay keyboard, mouse, and macro inputs to your MiSTer FPGA over the network using WebSockets and the MiSTer keyboard daemon (kd).

This app wraps a sleek, low-latency HTML virtual interface and an asynchronous Python backend proxy into a single standalone executable—eliminating the need for custom batch files, browser configurations, or separate script launches.

## Features

* Unified Application: Runs as a single `.exe` or desktop app window with an embedded UI.
* Low-Latency Input Relay: Captures typing, mouse movements, mouse button clicks, and scrolls, immediately streaming them via WebSockets to MiSTer's TCP layer.
* Hardware Profile Toggle: Easily switch between a standard PC layout mapping and specialized core layouts (e.g., Amiga).
* Persistent Settings: Automatically retains your Target IP, passwords, and custom proxy port designations across app restarts (no private/incognito reset loop).
* Integrated Hardware Macros: One-click shortcuts for frequent core actions like opening the system menu (F1) or triggering a hardware reset (F10).

## Architecture

```
┌─────────────────────────────────┐                 ┌─────────────┐
│       Desktop App Window        │                 │             │
│  (HTML UI + LocalStorage Memory) │                 │   MiSTer    │
│                │                │                 │    FPGA     │
│       (Local WebSockets)        │                 │             │
│                ▼                │   (TCP Socket)  │  ┌───────┐  │
│         Python Backend          ├────────────────►│  │  kd   │  │
│  (AsyncIO Server Proxy Tunnel)  │   Port 8064     │  │Daemon │  │
└─────────────────────────────────┘                 │  └───────┘  │
                                                    └─────────────┘

```

## Setup and Prerequisites

### 1. On your MiSTer FPGA

The application requires the keyboard daemon binary (`kd`) to be active on your console.

* Download or compile the `kd` binary.
* Place the `kd` binary file explicitly inside the `/media/fat/linux/` directory on your MiSTer SD card.
* Ensure the daemon is running and active. It listens on TCP port 8064 by default to intercept and inject the raw network inputs.

### 2. Running Locally (Development Mode)

If you want to run or modify the source code directly:

```bash
# Clone the repository and navigate inside
git clone https://github.com/yourusername/mister-input-link.git
cd mister-input-link

# Install dependencies
pip install websockets pywebview pyinstaller

# Launch the app
python main.py

```

## Packaging into a Standalone Executable

To bundle the Python backend and HTML interface into a clean, zero-dependency executable (`.exe`) that runs without an open terminal window:

### On Windows

```bash
pyinstaller --clean --noconsole --onefile --add-data "mister-keyboard.html;." main.py

```

### On macOS / Linux

```bash
pyinstaller --clean --noconsole --onefile --add-data "mister-keyboard.html:." main.py

```

After compilation, navigate to the generated `dist/` directory and double-click the executable to launch the app instantly.

## Configuration and Usage

1. Launch the compiled application executable.
2. Enter your MiSTer's Target IP address in the configuration panel.
3. Click Connect Link.
4. The system link dot status will turn Green upon establishing a secure handshake with the MiSTer network. You can now use the trackpad, visual buttons, or your physical keyboard to control the remote core environment seamlessly.
