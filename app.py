import sys
import os
import threading
import asyncio
import json
import ctypes
import subprocess
import time
import websockets
from pynput import keyboard, mouse

# ─── CONFIG ───
PROXY_HOST = "127.0.0.1"
PROXY_PORT = 4568
MISTER_IP  = "192.168.4.39"
MISTER_PW  = "1"

RELAY_MOUSE_SENSITIVITY = 3.3

# ─── GLOBAL STATE ───
is_relaying = False
connected_clients = set()
main_loop = None
keyboard_listener = None
mouse_listener = None
active_mods = set()
app_hwnd = None
pressed_physical_keys = set()
last_mouse_x = None
last_mouse_y = None
mouse_accum_x = 0.0
mouse_accum_y = 0.0

SW_MINIMIZE = 6
SW_RESTORE  = 9

# ─── KEY MAP ───
KEY_MAP = {
    'a':'a','b':'b','c':'c','d':'d','e':'e','f':'f','g':'g','h':'h',
    'i':'i','j':'j','k':'k','l':'l','m':'m','n':'n','o':'o','p':'p',
    'q':'q','r':'r','s':'s','t':'t','u':'u','v':'v','w':'w','x':'x',
    'y':'y','z':'z',
    '1':'1','2':'2','3':'3','4':'4','5':'5',
    '6':'6','7':'7','8':'8','9':'9','0':'0',
    'esc':':01','backspace':':0e','tab':':0f','enter':':1c','space':':39',
    'caps_lock':':3a',
    'f1':':3b','f2':':3c','f3':':3d','f4':':3e','f5':':3f',
    'f6':':40','f7':':41','f8':':42','f9':':43','f10':':44','f11':':57','f12':':58',
    'up':':67','left':':69','right':':6a','down':':6c',
    'page_up':':68','page_down':':6d','insert':':6e','delete':':6f',
    '-':':0c','=':':0d','[':':1a',']':':1b','\\':':2b',
    ';':':27',"'":':28',',':':33','.':':34','/':':35','`':':29',
}

# ─── MOD MAP ───
MOD_MAP = {
    'shift':   '2a',
    'shift_r': '36',
    'ctrl':    '1d',
    'ctrl_r':  '61',
    'alt':     '38',
    'alt_r':   '64',
    'cmd':     'db',  # Left Win key
    'cmd_r':   'db',  # Right Win key
}

# ═══════════════════════════════════════════════════════
# ─── EMBEDDED PROXY (formerly ws-to-tcp.py) ───
# ═══════════════════════════════════════════════════════

KEY_CODES = {
    'a':30,'b':48,'c':46,'d':32,'e':18,'f':33,'g':34,'h':35,
    'i':23,'j':36,'k':37,'l':38,'m':50,'n':49,'o':24,'p':25,
    'q':16,'r':19,'s':31,'t':20,'u':22,'v':47,'w':17,'x':45,
    'y':21,'z':44,
    '1':2,'2':3,'3':4,'4':5,'5':6,'6':7,'7':8,'8':9,'9':10,'0':11,
    ':01':1,':0e':14,':0f':15,':1c':28,':39':57,':3a':58,
    ':3b':59,':3c':60,':3d':61,':3e':62,':3f':63,
    ':40':64,':41':65,':42':66,':43':67,':44':68,
    ':57':87,':58':88,
    ':67':103,':69':105,':6a':106,':6c':108,
    ':68':104,':6d':109,':6e':110,':6f':111,
    ':0c':12,':0d':13,':1a':26,':1b':27,
    ':2b':43,':27':39,':28':40,
    ':33':51,':34':52,':35':53,':29':41,
    '1d':29,'2a':42,'36':54,'38':56,'61':97,'64':100,'db':125,
    ':37':55,
    ':47':71,':48':72,':49':73,':4a':74,
    ':4b':75,':4c':76,':4d':77,':4e':78,
    ':4f':79,':50':80,':51':81,
    ':52':82,':53':83,
    ':60':96,
    ':62':98,
    ':45':69,
}

kd_port = 8064
kd_host = None
kd_reader = None
kd_writer = None
proxy_browsers = set()  # Active browser WebSocket connections to the proxy server

async def kd_connect(host):
    global kd_reader, kd_writer, kd_host
    await kd_disconnect()
    try:
        kd_reader, kd_writer = await asyncio.wait_for(
            asyncio.open_connection(host, kd_port),
            timeout=3.0
        )
        kd_host = host
        print(f'KD connected to {host}:{kd_port}')
        return True
    except Exception as e:
        print(f'KD connection failed to {host}:{kd_port} -> {e}')
        kd_reader, kd_writer = None, None
        return False

async def kd_disconnect():
    global kd_reader, kd_writer
    if kd_writer:
        try:
            kd_writer.close()
            await asyncio.wait_for(kd_writer.wait_closed(), timeout=2.0)
        except Exception:
            pass
    kd_reader = None
    kd_writer = None
    await asyncio.sleep(0.1)

async def kd_send(cmd):
    global kd_writer
    if kd_writer is None:
        return False
    try:
        kd_writer.write((cmd + '\n').encode())
        await kd_writer.drain()
        return True
    except Exception as e:
        print(f'KD send error: {e}')
        await kd_disconnect()
        return False

async def kd_is_alive():
    global kd_writer
    if kd_writer is None:
        return False
    if kd_writer.is_closing():
        return False
    try:
        if kd_writer.transport and kd_writer.transport.is_closing():
            return False
    except Exception:
        return False
    return True

async def kd_watchdog():
    """Detects dead kd connection and auto-reconnects every 3 seconds."""
    while True:
        await asyncio.sleep(3)
        if kd_host is None:
            continue
        if not await kd_is_alive():
            print(f'KD connection lost — reconnecting to {kd_host}...')
            success = await kd_connect(kd_host)
            msg = json.dumps({
                'type': 'status',
                'ok': success,
                'msg': f'KD reconnected to {kd_host}:{kd_port}' if success
                       else 'KD reconnect failed — retrying...'
            })
            dead = set()
            for ws in proxy_browsers:
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            proxy_browsers.difference_update(dead)

def parse_mbc_seq(seq):
    commands = []
    i = 0
    while i < len(seq):
        c = seq[i]
        if c == '{':
            hex_code = seq[i+1:i+3]
            # Try direct lookup first, then with colon prefix
            code = KEY_CODES.get(hex_code) or KEY_CODES.get(f':{hex_code}')
            if code: commands.append(f'd {code}')
            i += 3
        elif c == '}':
            hex_code = seq[i+1:i+3]
            code = KEY_CODES.get(hex_code) or KEY_CODES.get(f':{hex_code}')
            if code: commands.append(f'u {code}')
            i += 3
        elif c == ':':
            hex_key = seq[i:i+3]
            code = KEY_CODES.get(hex_key)
            if code: commands.append(f't {code}')
            i += 3
        elif c.isalnum():
            code = KEY_CODES.get(c)
            if code: commands.append(f't {code}')
            i += 1
        else:
            i += 1
    return commands

async def handle_proxy_client(ws):
    """Handle a browser WebSocket connection to the embedded proxy."""
    print('Browser connected to proxy')
    proxy_browsers.add(ws)
    try:
        async for msg in ws:
            try:
                d = json.loads(msg)
                if d['type'] == 'connect':
                    host = d['host']
                    save_config({'last_ip': host})  # Remember last used IP
                    success = await kd_connect(host)
                    if success:
                        await ws.send(json.dumps({'type':'status','ok':True,'msg':f'KD connected to {host}:{kd_port}'}))
                    else:
                        await ws.send(json.dumps({'type':'status','ok':False,'msg':f'KD connect failed — is MiSTer active at {host}?'}))
                elif d['type'] == 'disconnect':
                    await kd_disconnect()
                    print('KD disconnected cleanly')
                elif d['type'] == 'toggle_background':
                    toggle_relay_state()
                elif d['type'] == 'quit':
                    print("Quit requested via proxy")
                    threading.Thread(target=do_quit, daemon=True).start()
                elif d['type'] == 'key':
                    for cmd in parse_mbc_seq(d['seq']):
                        await kd_send(cmd)
                elif d['type'] == 'mouse_move':
                    await kd_send(f"m {d['dx']} {d['dy']}")
                elif d['type'] == 'mouse_btn':
                    await kd_send(f"mb{d['btn']} {d['state']}")
                elif d['type'] == 'mouse_scroll':
                    await kd_send(f"ms {d['delta']}")
            except Exception as e:
                print(f'Proxy handle error: {e}')
    finally:
        proxy_browsers.discard(ws)

# ═══════════════════════════════════════════════════════
# ─── APP WINDOW ───
# ═══════════════════════════════════════════════════════

def get_resource_path(filename):
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, filename)

def get_config_path():
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, 'mister-keyboard.json')

def load_config():
    try:
        with open(get_config_path(), 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(data):
    try:
        with open(get_config_path(), 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Config save error: {e}")

def find_browser():
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None

def launch_app_window():
    html_path = get_resource_path("mister-keyboard.html")
    url = f"file:///{html_path.replace(os.sep, '/')}"
    browser = find_browser()
    if browser:
        subprocess.Popen([browser, f"--app={url}", "--window-size=1200,900",
                         "--disable-extensions",
                         "--allow-file-access-from-files",
                         "--disable-web-security"])
        print(f"Launched app window: {url}")
    else:
        import webbrowser
        webbrowser.open(url)
        print(f"No Chrome/Edge found — opened in default browser: {url}")

def find_app_hwnd():
    found = []
    def callback(hwnd, _):
        if ctypes.windll.user32.IsWindowVisible(hwnd):
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buff, length + 1)
            if "MiSTer Keyboard" in buff.value:
                found.append(hwnd)
        return True
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    ctypes.windll.user32.EnumWindows(WNDENUMPROC(callback), 0)
    return found[0] if found else None

def locate_window_with_retry(retries=10, delay=0.5):
    global app_hwnd
    for _ in range(retries):
        hwnd = find_app_hwnd()
        if hwnd:
            app_hwnd = hwnd
            print(f"App window found: hwnd={hwnd}")
            return
        time.sleep(delay)
    print("Warning: could not find app window handle")

def minimize_app():
    global app_hwnd
    app_hwnd = find_app_hwnd()  # Always fresh lookup
    if app_hwnd:
        ctypes.windll.user32.ShowWindow(app_hwnd, SW_MINIMIZE)
    else:
        print("Warning: could not find app window to minimize")

def restore_app():
    global app_hwnd
    app_hwnd = find_app_hwnd()
    if app_hwnd:
        # Workaround for Windows blocking SetForegroundWindow from fullscreen apps
        ctypes.windll.user32.ShowWindow(app_hwnd, SW_RESTORE)
        # Attach to foreground thread to allow focus steal
        fg_thread = ctypes.windll.user32.GetWindowThreadProcessId(
            ctypes.windll.user32.GetForegroundWindow(), None)
        app_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        if fg_thread != app_thread:
            ctypes.windll.user32.AttachThreadInput(fg_thread, app_thread, True)
            ctypes.windll.user32.SetForegroundWindow(app_hwnd)
            ctypes.windll.user32.AttachThreadInput(fg_thread, app_thread, False)
        else:
            ctypes.windll.user32.SetForegroundWindow(app_hwnd)
        ctypes.windll.user32.BringWindowToTop(app_hwnd)
    else:
        print("Warning: could not find app window to restore")

# ═══════════════════════════════════════════════════════
# ─── WIN+F12 HOTKEY REGISTRATION ───
# pynput cannot capture Win key under suppress=True — use Windows RegisterHotKey instead
WIN_F12_HOTKEY_ID = 1
MOD_WIN = 0x0008
VK_F12  = 0x7B

def register_win_f12():
    """Register Win+F12 as a system hotkey so we can capture it even in relay mode."""
    import ctypes.wintypes
    hwnd = None  # NULL = message-only, use thread message loop
    ok = ctypes.windll.user32.RegisterHotKey(hwnd, WIN_F12_HOTKEY_ID, MOD_WIN, VK_F12)
    if ok:
        print("Win+F12 registered as system hotkey")
    else:
        print("Win+F12 registration failed (may already be registered)")

def win_f12_listener():
    """Message loop that fires when Win+F12 is pressed."""
    import ctypes.wintypes
    register_win_f12()
    msg = ctypes.wintypes.MSG()
    WM_HOTKEY = 0x0312
    while True:
        if ctypes.windll.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == WM_HOTKEY and msg.wParam == WIN_F12_HOTKEY_ID:
                # Send Win+F12 sequence to kd
                send_to_kd({"type": "key", "seq": "{db:58}db"})
        else:
            break
# ═══════════════════════════════════════════════════════

def send_to_kd(payload: dict):
    """Send a key/mouse payload directly to kd via the embedded proxy."""
    if not main_loop:
        return
    asyncio.run_coroutine_threadsafe(_send_to_kd_async(payload), main_loop)

async def _send_to_kd_async(payload: dict):
    t = payload.get('type')
    if t == 'key':
        for cmd in parse_mbc_seq(payload['seq']):
            await kd_send(cmd)
    elif t == 'mouse_move':
        await kd_send(f"m {payload['dx']} {payload['dy']}")
    elif t == 'mouse_btn':
        await kd_send(f"mb{payload['btn']} {payload['state']}")
    elif t == 'mouse_scroll':
        await kd_send(f"ms {payload['delta']}")

def broadcast(payload: dict):
    if not connected_clients or not main_loop:
        return
    data = json.dumps(payload)
    asyncio.run_coroutine_threadsafe(
        asyncio.gather(*[c.send(data) for c in connected_clients], return_exceptions=True),
        main_loop
    )

async def _broadcast_status_async():
    if not connected_clients:
        return
    data = json.dumps({"type": "STATUS", "active": is_relaying})
    dead = set()
    for c in connected_clients:
        try:
            await c.send(data)
        except Exception:
            dead.add(c)
    connected_clients.difference_update(dead)

def broadcast_status():
    if main_loop:
        asyncio.run_coroutine_threadsafe(_broadcast_status_async(), main_loop)

def clear_mouse_state():
    global last_mouse_x, last_mouse_y, mouse_accum_x, mouse_accum_y
    last_mouse_x = None
    last_mouse_y = None
    mouse_accum_x = 0.0
    mouse_accum_y = 0.0

def _execute_relay_toggle():
    global is_relaying, mouse_listener, keyboard_listener, last_mouse_x, last_mouse_y

    is_relaying = not is_relaying
    clear_mouse_state()
    pressed_physical_keys.clear()
    pending_mods.clear()

    # Release any held mods and keys on MiSTer before clearing state
    for hex_code in list(active_mods):
        send_to_kd({"type": "key", "seq": f"}}{hex_code}"})
    active_mods.clear()
    for hex_code in list(held_relay_keys.values()):
        send_to_kd({"type": "key", "seq": f"}}{hex_code}"})
    held_relay_keys.clear()

    # Stop old listeners
    if keyboard_listener:
        try: keyboard_listener.stop()
        except: pass
    if mouse_listener:
        try: mouse_listener.stop()
        except: pass

    time.sleep(0.1)  # Let Windows fully uninstall old hooks

    # Restart listeners with correct suppress state BEFORE minimize/restore
    # so the hotkey can be detected immediately after
    keyboard_listener = keyboard.Listener(
        on_press=handle_global_press,
        on_release=handle_global_release,
        suppress=is_relaying
    )
    mouse_listener = mouse.Listener(
        on_move=handle_mouse_move,
        on_click=handle_mouse_click,
        on_scroll=handle_mouse_scroll,
        suppress=is_relaying
    )
    keyboard_listener.start()
    mouse_listener.start()

    if is_relaying:
        print("Relay Active")
        try:
            ctypes.windll.user32.SetCursorPos(500, 500)
            last_mouse_x = 500
            last_mouse_y = 500
        except Exception:
            pass
        minimize_app()
    else:
        print("Local Control Restored")
        # Small delay to ensure window is ready to restore
        time.sleep(0.1)
        restore_app()

    broadcast_status()

_last_toggle_time = 0.0

def toggle_relay_state():
    global _last_toggle_time
    now = time.time()
    if now - _last_toggle_time < 0.5:
        return  # Debounce — ignore rapid double-fires
    _last_toggle_time = now
    threading.Thread(target=_execute_relay_toggle, daemon=True).start()

# Keys that should use hold-down/release instead of tap
HOLD_KEYS = {
    'page_up', 'page_down', 'insert', 'delete',
    'backspace', 'tab', 'space', 'esc',
    'f1','f2','f3','f4','f5','f6','f7','f8','f9','f10','f11','f12',
}

# Keys currently held down in relay mode (for proper hold/release)
held_relay_keys = {}  # key_id -> hex_code

# Guard to ignore key events immediately after toggling relay
_relay_toggle_grace = False

def _clear_relay_grace():
    global _relay_toggle_grace
    time.sleep(0.05)  # 50ms grace — just enough to swallow hotkey key-ups
    _relay_toggle_grace = False

def resolve_key(key):
    if hasattr(key, 'char') and key.char:
        ch = key.char.lower()
        if ch in KEY_MAP:
            return KEY_MAP[ch]
    if hasattr(key, 'vk') and key.vk is not None:
        if 65 <= key.vk <= 90:
            ch = chr(key.vk).lower()
            if ch in KEY_MAP:
                return KEY_MAP[ch]
        elif 48 <= key.vk <= 57:
            ch = chr(key.vk)
            if ch in KEY_MAP:
                return KEY_MAP[ch]
        # Punctuation — char is None under suppress=True, use VK codes
        VK_PUNCT = {
            191: ':35',  # /
            190: ':34',  # .
            188: ':33',  # ,
            186: ':27',  # ;
            222: ':28',  # '
            219: ':1a',  # [
            221: ':1b',  # ]
            220: ':2b',  # \
            192: ':29',  # `
            189: ':0c',  # -
            187: ':0d',  # =
        }
        if key.vk in VK_PUNCT:
            return VK_PUNCT[key.vk]
    if hasattr(key, 'name') and key.name:
        name = key.name.lower()
        if name in ['ctrl_l', 'ctrl_r', 'alt_l', 'alt_r', 'shift_l', 'shift_r']:
            return None
        if name in KEY_MAP:
            return KEY_MAP[name]
    return None

def get_mod_name(key):
    if hasattr(key, 'name') and key.name:
        name = key.name.lower()
        if name in ['ctrl', 'ctrl_l']: return 'ctrl'
        if name in ['ctrl_r']: return 'ctrl_r'
        if name in ['alt', 'alt_l']: return 'alt'
        if name in ['alt_r', 'alt_gr']: return 'alt_r'
        if name in ['shift', 'shift_l']: return 'shift'
        if name in ['shift_r']: return 'shift_r'
        if name in ['cmd', 'cmd_l', 'super', 'super_l']: return 'cmd'
        if name in ['cmd_r', 'super_r']: return 'cmd_r'
    return None

def get_normalized_physical_id(key):
    if hasattr(key, 'name') and key.name:
        return key.name.lower()
    if hasattr(key, 'vk') and key.vk is not None:
        return key.vk
    if hasattr(key, 'char') and key.char:
        return key.char.lower()
    return None

pending_mods = {}  # hex_code -> True, held until we confirm not the hotkey

def flush_pending_mods():
    for hex_code in list(pending_mods.keys()):
        if hex_code not in active_mods:
            active_mods.add(hex_code)
            send_to_kd({"type": "key", "seq": f"{{{hex_code}"})
    pending_mods.clear()

def handle_global_press(key):
    global pressed_physical_keys
    k_id = get_normalized_physical_id(key)
    if k_id:
        pressed_physical_keys.add(k_id)

    ctrl_down  = any(x in pressed_physical_keys for x in ['ctrl', 'ctrl_l', 'ctrl_r'])
    alt_down   = any(x in pressed_physical_keys for x in ['alt', 'alt_l', 'alt_r', 'alt_gr'])
    shift_down = any(x in pressed_physical_keys for x in ['shift', 'shift_l', 'shift_r'])
    m_down     = ('m' in pressed_physical_keys) or (77 in pressed_physical_keys)
    f_down     = ('f' in pressed_physical_keys) or (70 in pressed_physical_keys)

    if ctrl_down and alt_down and shift_down and m_down:
        pending_mods.clear()
        for k in ['ctrl','ctrl_l','ctrl_r','alt','alt_l','alt_r','alt_gr',
                  'shift','shift_l','shift_r','m']:
            pressed_physical_keys.discard(k)
        pressed_physical_keys.discard(77)
        toggle_relay_state()
        return

    # Ctrl+Alt+Shift+F = MiSTer OSD (Win+F12 substitute for background mode)
    if ctrl_down and alt_down and shift_down and f_down and is_relaying:
        pending_mods.clear()
        for k in ['ctrl','ctrl_l','ctrl_r','alt','alt_l','alt_r','alt_gr',
                  'shift','shift_l','shift_r','f']:
            pressed_physical_keys.discard(k)
        pressed_physical_keys.discard(70)
        send_to_kd({"type": "key", "seq": "{db:58}db"})
        return

    if not is_relaying:
        return

    mod = get_mod_name(key)
    if mod:
        hex_code = MOD_MAP[mod]
        # Stage mod as pending — only flush when a real key follows
        pending_mods[hex_code] = True
        return

    # Real key pressed — flush any staged mods first
    flush_pending_mods()

    seq = resolve_key(key)
    if not seq:
        return

    key_name = key.name.lower() if hasattr(key, 'name') and key.name else None

    if key_name in HOLD_KEYS:
        if seq.startswith(':'):
            hex_code = seq[1:]
        else:
            hex_code = seq
        if f':{hex_code}' in KEY_CODES or hex_code in KEY_CODES:
            if k_id not in held_relay_keys:
                held_relay_keys[k_id] = hex_code
                send_to_kd({"type": "key", "seq": f"{{{hex_code}"})
        else:
            send_to_kd({"type": "key", "seq": seq})
    else:
        send_to_kd({"type": "key", "seq": seq})

def handle_global_release(key):
    global pressed_physical_keys
    k_id = get_normalized_physical_id(key)
    if k_id in pressed_physical_keys:
        pressed_physical_keys.discard(k_id)

    if not is_relaying:
        return

    mod = get_mod_name(key)
    if mod:
        hex_code = MOD_MAP[mod]
        if hex_code in pending_mods:
            # Was never sent — just discard
            del pending_mods[hex_code]
        elif hex_code in active_mods:
            active_mods.discard(hex_code)
            send_to_kd({"type": "key", "seq": f"}}{hex_code}"})
        return

    # Release held keys
    if k_id in held_relay_keys:
        hex_code = held_relay_keys.pop(k_id)
        send_to_kd({"type": "key", "seq": f"}}{hex_code}"})

def handle_mouse_move(x, y):
    global last_mouse_x, last_mouse_y, mouse_accum_x, mouse_accum_y
    if not is_relaying:
        last_mouse_x = x
        last_mouse_y = y
        return
    if last_mouse_x is None or last_mouse_y is None:
        last_mouse_x = x
        last_mouse_y = y
        return
    dx = x - last_mouse_x
    dy = y - last_mouse_y
    if dx == 0 and dy == 0:
        return
    mouse_accum_x += dx * RELAY_MOUSE_SENSITIVITY
    mouse_accum_y += dy * RELAY_MOUSE_SENSITIVITY
    sx = int(mouse_accum_x)
    sy = int(mouse_accum_y)
    mouse_accum_x -= sx
    mouse_accum_y -= sy
    if sx != 0 or sy != 0:
        send_to_kd({"type": "mouse_move", "dx": sx, "dy": sy})

def handle_mouse_click(x, y, button, pressed):
    if not is_relaying:
        return
    state = 'd' if pressed else 'u'
    if button == mouse.Button.left:
        send_to_kd({"type": "mouse_btn", "btn": 0, "state": state})
    elif button == mouse.Button.right:
        send_to_kd({"type": "mouse_btn", "btn": 1, "state": state})
    elif button == mouse.Button.middle:
        send_to_kd({"type": "mouse_btn", "btn": 2, "state": state})

def handle_mouse_scroll(x, y, dx, dy):
    if not is_relaying:
        return
    delta = 1 if dy < 0 else -1
    send_to_kd({"type": "mouse_scroll", "delta": delta})

def start_input_listeners():
    global keyboard_listener, mouse_listener
    keyboard_listener = keyboard.Listener(
        on_press=handle_global_press,
        on_release=handle_global_release,
        suppress=False
    )
    keyboard_listener.start()
    print(f"Keyboard listener started, alive={keyboard_listener.is_alive()}")
    mouse_listener = mouse.Listener(
        on_move=handle_mouse_move,
        on_click=handle_mouse_click,
        on_scroll=handle_mouse_scroll,
        suppress=False
    )
    mouse_listener.start()
    print(f"Mouse listener started, alive={mouse_listener.is_alive()}")

# ═══════════════════════════════════════════════════════
# ─── WEBSOCKET CONTROL SERVER (port 8001) ───
# ═══════════════════════════════════════════════════════

async def handle_client(websocket, path=None):
    connected_clients.add(websocket)
    config = load_config()
    await websocket.send(json.dumps({
        "type": "STATUS",
        "active": is_relaying,
        "last_ip": config.get('last_ip', '')
    }))
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get("type") == "TOGGLE_BACKGROUND_MODE":
                toggle_relay_state()
            elif data.get("type") == "QUIT":
                print("Quit requested by UI")
                threading.Thread(target=do_quit, daemon=True).start()
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        connected_clients.discard(websocket)

# ═══════════════════════════════════════════════════════
# ─── SHUTDOWN ───
# ═══════════════════════════════════════════════════════

def shutdown():
    print("Shutting down...")
    clear_mouse_state()
    if keyboard_listener:
        try: keyboard_listener.stop()
        except: pass
    if mouse_listener:
        try: mouse_listener.stop()
        except: pass

def do_quit():
    shutdown()
    # Kill the browser window
    hwnd = app_hwnd or find_app_hwnd()
    if hwnd:
        pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value:
            h = ctypes.windll.kernel32.OpenProcess(1, False, pid.value)
            if h:
                ctypes.windll.kernel32.TerminateProcess(h, 0)
                ctypes.windll.kernel32.CloseHandle(h)
    time.sleep(0.2)
    os._exit(0)

# ═══════════════════════════════════════════════════════
# ─── MAIN ───
# ═══════════════════════════════════════════════════════

async def main():
    global main_loop
    main_loop = asyncio.get_running_loop()
    start_input_listeners()
    threading.Thread(target=win_f12_listener, daemon=True).start()

    # Start embedded proxy server (replaces ws-to-tcp.py subprocess)
    proxy_server = await websockets.serve(
        handle_proxy_client, '127.0.0.1', PROXY_PORT,
        reuse_address=True
    )
    print(f'Embedded proxy listening on ws://127.0.0.1:{PROXY_PORT}')

    # Start kd watchdog
    asyncio.ensure_future(kd_watchdog())

    # Start control server
    control_server = await websockets.serve(
        handle_client, '127.0.0.1', 8001,
        reuse_address=True
    )
    print('Control server listening on ws://127.0.0.1:8001')

    launch_app_window()
    threading.Thread(target=locate_window_with_retry, daemon=True).start()

    try:
        await asyncio.Future()
    except asyncio.CancelledError:
        pass
    finally:
        proxy_server.close()
        control_server.close()
        await proxy_server.wait_closed()
        await control_server.wait_closed()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    finally:
        shutdown()
