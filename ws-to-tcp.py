import asyncio
import json
import websockets

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
    # Numpad
    ':37':55,  # KP*
    ':47':71,':48':72,':49':73,':4a':74,  # 7 8 9 -
    ':4b':75,':4c':76,':4d':77,':4e':78,  # 4 5 6 +
    ':4f':79,':50':80,':51':81,           # 1 2 3
    ':52':82,':53':83,                    # 0 .
    ':60':96,                             # KP Enter
    ':62':98,                             # KP /
    ':45':69,                             # NumLock
}

kd_reader = None
kd_writer = None
kd_port = 8064
kd_host = None  # Track last used host for auto-reconnect

# All active browser WebSocket connections — used to broadcast reconnect status
active_browsers = set()

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
    await asyncio.sleep(0.1)  # Brief pause to let OS release the socket

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
    """Check if the kd TCP connection is still healthy."""
    global kd_writer
    if kd_writer is None:
        return False
    if kd_writer.is_closing():
        return False
    try:
        # Probe the transport directly — no data sent, just checks socket state
        transport = kd_writer.transport
        if transport and transport.is_closing():
            return False
    except Exception:
        return False
    return True

async def kd_watchdog():
    """Background task — detects dead kd connection and auto-reconnects."""
    while True:
        await asyncio.sleep(3)
        if kd_host is None:
            continue  # Never connected yet, nothing to watch
        if not await kd_is_alive():
            print(f'KD connection lost — reconnecting to {kd_host}...')
            success = await kd_connect(kd_host)
            # Notify all connected browsers of reconnect status
            msg = json.dumps({
                'type': 'status',
                'ok': success,
                'msg': f'KD reconnected to {kd_host}:{kd_port}' if success
                       else f'KD reconnect failed — retrying...'
            })
            dead = set()
            for ws in active_browsers:
                try:
                    await ws.send(msg)
                except Exception:
                    dead.add(ws)
            active_browsers.difference_update(dead)

def parse_mbc_seq(seq):
    commands = []
    i = 0
    while i < len(seq):
        c = seq[i]
        if c == '{':
            hex_code = seq[i+1:i+3]
            code = KEY_CODES.get(hex_code)
            if code: commands.append(f'd {code}')
            i += 3
        elif c == '}':
            hex_code = seq[i+1:i+3]
            code = KEY_CODES.get(hex_code)
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

async def handle(ws):
    print('Browser connected to proxy')
    active_browsers.add(ws)
    try:
        async for msg in ws:
            try:
                d = json.loads(msg)

                if d['type'] == 'connect':
                    host = d['host']
                    success = await kd_connect(host)
                    if success:
                        await ws.send(json.dumps({'type':'status','ok':True,'msg':f'KD connected to {host}:{kd_port}'}))
                    else:
                        await ws.send(json.dumps({'type':'status','ok':False,'msg':f'KD connect failed — is MiSTer active at {host}?'}))

                elif d['type'] == 'key':
                    for cmd in parse_mbc_seq(d['seq']):
                        await kd_send(cmd)

                elif d['type'] == 'mouse_move':
                    await kd_send(f"m {d['dx']} {d['dy']}")

                elif d['type'] == 'mouse_btn':
                    btn = d['btn']
                    state = d['state']
                    await kd_send(f"mb{btn} {state}")

                elif d['type'] == 'mouse_scroll':
                    await kd_send(f"ms {d['delta']}")

            except Exception as e:
                print(f'Proxy handle error: {e}')
    finally:
        active_browsers.discard(ws)

async def main():
    print('MiSTer Keyboard proxy on ws://127.0.0.1:4568')
    asyncio.ensure_future(kd_watchdog())
    async with websockets.serve(handle, '127.0.0.1', 4568):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
