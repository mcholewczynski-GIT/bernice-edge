#!/bin/sh
# Install the Bernice Edge job service as a systemd user service on the Collab Compute.
# Safe to re-run: keeps an existing token.
set -e
CONF="$HOME/.config/bernice-edge"
ENV="$CONF/edge.env"
REPO="$HOME/bernice-edge"

mkdir -p "$CONF" "$HOME/.config/systemd/user"
if [ ! -f "$ENV" ]; then
  TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  TSIP=$(tailscale ip -4 2>/dev/null | head -n1)
  [ -n "$TSIP" ] || { echo "Tailscale address not found; is Tailscale up?"; exit 1; }
  umask 077
  printf 'EDGE_TOKEN=%s\nEDGE_BIND=%s\nEDGE_PORT=8790\n' "$TOKEN" "$TSIP" > "$ENV"
  echo "Created $ENV (mode 600)."
fi
chmod 600 "$ENV"

cp "$REPO/collab-compute/deployment/bernice-edge.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now bernice-edge.service
sudo loginctl enable-linger "$USER"
sleep 1
systemctl --user --no-pager status bernice-edge.service | head -n 5
echo
echo "Copy this token to the Spark's ~/.env_secrets as EDGE_TOKEN:"
grep '^EDGE_TOKEN=' "$ENV" | cut -d= -f2-
