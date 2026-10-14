#!/bin/sh
set -eu
if [ ! -s "${BDC_VNC_PASSWORD_FILE:-/run/secrets/bdc_vnc_password}" ]; then
  echo "VNC password file missing or empty" >&2
  exit 1
fi
umask 077
mkdir -p /tmp/bdc-vnc
x11vnc -storepasswd "$(cat "$BDC_VNC_PASSWORD_FILE")" /tmp/bdc-vnc/passwd >/dev/null
Xvfb :99 -screen 0 1440x900x24 -nolisten tcp &
fluxbox >/tmp/fluxbox.log 2>&1 &
x11vnc -display :99 -rfbauth /tmp/bdc-vnc/passwd -rfbport 5900 -localhost -forever -shared -noxdamage >/tmp/x11vnc.log 2>&1 &
websockify --web /usr/share/novnc/ 0.0.0.0:6080 localhost:5900 >/tmp/websockify.log 2>&1 &
exec python app.py --no-browser-ui
