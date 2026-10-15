#!/bin/sh
# Full-screen room display for Bernice Edge. Run inside the desktop session
# (autostart), or from SSH: it finds the logged-in session itself.
URL="${EDGE_DISPLAY_URL:-http://127.0.0.1:8791/display}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
[ -n "$WAYLAND_DISPLAY" ] || [ -n "$DISPLAY" ] || {
  if [ -S "$XDG_RUNTIME_DIR/wayland-0" ]; then export WAYLAND_DISPLAY=wayland-0; else export DISPLAY=:0; fi
}
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
# Keep the screen on and unlocked for the room display.
gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null
gsettings set org.gnome.desktop.notifications show-banners false 2>/dev/null
# Wait for the edge service, then open the display.
for i in $(seq 1 60); do curl -s -o /dev/null "$URL" && break; sleep 2; done
pkill -f "firefox.*--kiosk" 2>/dev/null; sleep 1
exec firefox --kiosk --private-window "$URL" >/dev/null 2>&1
