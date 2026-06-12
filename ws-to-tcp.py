import asyncio
import json
import websockets
import socket

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

kd_sock = None
kd_port = 8064

def kd_connect(host):
    global kd_sock
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.connect((host, kd_port))
    kd_sock = s
    print(f'KD connected to {host}:{kd_port}')

def kd_send(cmd):
    global kd_sock
    if kd_sock is None: return False
    try:
        kd_sock.sendall((cmd + '\n').encode())
        return True
    except Exception as e:
        print(f'KD error: {e}')
        kd_sock = None
        return False

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
    global kd_sock
    print('Browser connected')
    async for msg in ws:
        try:
            d = json.loads(msg)

            if d['type'] == 'connect':
                host = d['host']
                try:
                    kd_connect(host)
                    await ws.send(json.dumps({'type':'status','ok':True,'msg':f'KD connected to {host}:{kd_port}'}))
                except Exception as e:
                    await ws.send(json.dumps({'type':'status','ok':False,'msg':f'KD connect failed: {e} — is kd running on MiSTer?'}))

            elif d['type'] == 'key':
                for cmd in parse_mbc_seq(d['seq']):
                    kd_send(cmd)

            elif d['type'] == 'mouse_move':
                kd_send(f"m {d['dx']} {d['dy']}")

            elif d['type'] == 'mouse_btn':
                btn = d['btn']   # 0=left, 1=right, 2=middle
                state = d['state']  # 'd' or 'u'
                kd_send(f"mb{btn} {state}")

            elif d['type'] == 'mouse_scroll':
                kd_send(f"ms {d['delta']}")

        except Exception as e:
            print(f'Error: {e}')

async def main():
    print('MiSTer Keyboard proxy on ws://localhost:4568')
    async with websockets.serve(handle, 'localhost', 4568):
        await asyncio.Future()

asyncio.run(main())
