#!/bin/sh
# Wrapper Hermes runs for the bernice-edge skill.
# Loads EDGE_URL / EDGE_TOKEN from ~/.env_secrets without printing them.
#   edge.sh status
#   edge.sh generate "<visual description>"
set -e
[ -f "$HOME/.env_secrets" ] && . "$HOME/.env_secrets"
CLIENT="${BERNICE_EDGE_REPO:-$HOME/bernice-edge}/spark-integration/edge_client.py"
[ -n "$EDGE_TOKEN" ] || { echo "EDGE_TOKEN is not set in ~/.env_secrets"; exit 2; }
exec python3 "$CLIENT" "$@"
