import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('23.95.78.148', port=22, username='root', password='TANGlidong24ban', timeout=10)

# Detailed test of the socket access chain
cmds = """
python3 -c "
import urllib.request, urllib.response, http.client, socket

# Create a real connection to test the chain
req = urllib.request.Request('https://chatglm.cn/chatglm/backend-api/assistant/stream')
# We just need to check the object structure
# Let's check addinfourl
from urllib.response import addinfourl

# Check what HTTPResponse.fp looks like in practice
# HTTPResponse is created by http.client.HTTPConnection.getresponse()
import http.client
conn = http.client.HTTPSConnection('chatglm.cn', timeout=10)
try:
    conn.request('GET', '/')
    resp = conn.getresponse()
    print('=== Response type:', type(resp).__name__)
    print('Has fp attr:', hasattr(resp, 'fp'))
    print('fp type:', type(resp.fp).__name__ if hasattr(resp, 'fp') else 'N/A')
    
    if hasattr(resp, 'fp'):
        inner = resp.fp
        print('fp.fp:', hasattr(inner, 'fp'))
        if hasattr(inner, 'fp'):
            inner2 = inner.fp
            print('fp.fp type:', type(inner2).__name__)
            print('fp.fp has raw:', hasattr(inner2, 'raw'))
            if hasattr(inner2, 'raw'):
                print('fp.fp.raw type:', type(inner2.raw).__name__)
                print('fp.fp.raw has _sock:', hasattr(inner2.raw, '_sock'))
                if hasattr(inner2.raw, '_sock'):
                    sock = inner2.raw._sock
                    print('fp.fp.raw._sock type:', type(sock).__name__)
                    print('Has settimeout:', hasattr(sock, 'settimeout'))
                    print('Current timeout:', sock.gettimeout())
                    sock.settimeout(30)
                    print('After settimeout(30):', sock.gettimeout())
        elif hasattr(inner, 'raw'):
            print('inner has raw:', True)
            print('inner.raw type:', type(inner.raw).__name__)
            print('inner.raw has _sock:', hasattr(inner.raw, '_sock'))
            if hasattr(inner.raw, '_sock'):
                sock = inner.raw._sock
                print('_sock has settimeout:', hasattr(sock, 'settimeout'))
                print('Original timeout:', sock.gettimeout())
                sock.settimeout(30)
                print('After settimeout:', sock.gettimeout())
    resp.close()
except Exception as e:
    print(f'Connection error: {e}')
finally:
    conn.close()
"
"""

stdin, stdout, stderr = client.exec_command(cmds)
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode().strip()
if err:
    print(f'STDERR: {err[:500]}')

client.close()
