import paramiko, sys

sys.stdout.reconfigure(encoding='utf-8')

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect('23.95.78.148', port=22, username='root', password='TANGlidong24ban', timeout=10)

cmds = """
echo '=== Python version ==='
python3 --version

echo '=== Test socket access chain ==='
python3 -c "
import urllib.request, sys
# Check what urllib.response.addinfourl looks like
u = urllib.request
print('urllib.request version:', sys.version)

# Check if http.client.HTTPResponse has fp and raw
import http.client
resp = http.client.HTTPResponse
print('HTTPResponse has fp:', hasattr(resp, 'fp'))

# Check io.SocketIO _sock attribute
import io
sio = io.SocketIO
print('SocketIO has _sock:', hasattr(sio, '_sock'))
"

echo '=== Check current keepalive code ==='
grep -n 'sock = ' /opt/glm2api/src/glm2api/services/glm_client.py | head -5
grep -n 'KEEPALIVE_INTERVAL' /opt/glm2api/src/glm2api/services/glm_client.py
grep -n 'settimeout' /opt/glm2api/src/glm2api/services/glm_client.py | head -10

echo '=== Check if keepalive is being logged ==='
journalctl -u glm2api --since '5 min ago' --no-pager 2>/dev/null | grep -i 'keepalive\|timeout\|stall' | tail -20 || echo '(no keepalive log entries)'
"""

stdin, stdout, stderr = client.exec_command(cmds)
print(stdout.read().decode('utf-8', errors='replace'))
err = stderr.read().decode().strip()
if err:
    print(f'STDERR: {err[:500]}')

client.close()
