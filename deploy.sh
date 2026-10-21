#!/bin/bash
set -euo pipefail
cd /home/agentuser/coder
TS=$(date +%s)
cp server.py "server.py.bak.$TS"
cp openapi.json "openapi.json.bak.$TS" 2>/dev/null || echo "{}" > /dev/null
mv server.py.new server.py
[ -f openapi.json.new ] && mv openapi.json.new openapi.json
PID=$(ss -ltnp 2>/dev/null | awk '/:8795 /{print $NF}' | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2 || true)
echo "listener_pid=${PID:-none}"
if [ -n "${PID:-}" ]; then kill "$PID"; fi
for i in $(seq 1 20); do ss -ltn 2>/dev/null | grep -q ':8795 ' || break; sleep 0.5; done
setsid env X402_PAY_TO=0x27EbD1DDCB6607bE8641784A1bf654623Fc8290e PORT=8795 nohup python3 /home/agentuser/coder/server.py >> /home/agentuser/coder/server.log 2>&1 &
sleep 2
ss -ltnp 2>/dev/null | grep ':8795 ' || echo "NOT LISTENING"
curl -s -o /dev/null -w 'local_health=%{http_code}\n' http://127.0.0.1:8795/health
