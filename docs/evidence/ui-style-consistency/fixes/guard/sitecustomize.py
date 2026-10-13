import os, socket, sys
_original_bind = socket.socket.bind
_original_connect = socket.socket.connect
_original_connect_ex = socket.socket.connect_ex

def bind(sock, address):
    if isinstance(address, tuple) and (address[0] not in ('127.0.0.1', '::1', 'localhost') or address[1] != 0):
        raise RuntimeError('AUDIT blocked non-ephemeral bind')
    result = _original_bind(sock, address)
    if isinstance(address, tuple):
        ports=set(filter(None,os.environ.get('AUDIT_TEST_PORTS','').split(',')))
        ports.add(str(sock.getsockname()[1]));os.environ['AUDIT_TEST_PORTS']=','.join(ports)
    return result

def check(address):
    if isinstance(address, tuple) and not (address[0] in ('127.0.0.1','::1','localhost') and str(address[1]) in os.environ.get('AUDIT_TEST_PORTS','').split(',')):
        raise RuntimeError('AUDIT blocked network connection')

def connect(sock,address):
    check(address);return _original_connect(sock,address)
def connect_ex(sock,address):
    check(address);return _original_connect_ex(sock,address)
socket.socket.bind=bind;socket.socket.connect=connect;socket.socket.connect_ex=connect_ex

def audit(event,args):
    if event=='subprocess.Popen':
        executable=str(args[0])
        if 'python' not in executable and not (os.path.basename(executable)=='node' and len(args[1])==2 and str(args[1][1]).endswith('/scripts/superdoc-engine.mjs')):
            raise RuntimeError('AUDIT blocked non-Python subprocess')
    if event=='open' and isinstance(args[0],(str,bytes)):
        path=os.path.abspath(os.fsdecode(args[0]))
        if path.startswith(('/Users/dicam/CodeDir/OpenHarvey/data/','/Users/dicam/.codex/auth','/Users/dicam/.aws/')) or os.path.basename(path)=='.env':
            raise RuntimeError('AUDIT blocked private data read')
sys.addaudithook(audit)
