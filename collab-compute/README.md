# Bernice Edge (Crestron Collab Compute)

Edge side of Bernice Edge. The Spark keeps speech, reasoning and AV control;
this node runs delegated visual jobs and drives the room display.

## Layout

| Path | Purpose |
|---|---|
| `agent-bridge/edge_service.py` | Authenticated job API (standard library only) |
| `deployment/bernice-edge.service` | systemd user unit |
| `deployment/install.sh` | Creates token/config, installs and starts the service |
| `../spark-integration/edge_client.py` | Spark-side client and CLI test |

## Sprint 1 status

The generator is a dummy that renders a test pattern. This proves the
Spark-to-edge job lifecycle before any model is added (Sprint 2).

## Install (on the edge)

```
cd ~/bernice-edge && git pull
sh collab-compute/deployment/install.sh
```

Config lives in `~/.config/bernice-edge/edge.env` (mode 600):
`EDGE_TOKEN`, `EDGE_BIND` (the edge's Tailscale address), `EDGE_PORT` (8790).

## Test (from the Spark)

Add to `~/.env_secrets`:

```
export EDGE_URL=http://bernice-edge-01:8790
export EDGE_TOKEN=<token printed by install.sh>
```

Then:

```
. ~/.env_secrets
python3 spark-integration/edge_client.py status
python3 spark-integration/edge_client.py generate "sound waves in a lecture hall"
```

## API

All requests need `Authorization: Bearer <EDGE_TOKEN>`.

| Method | Path | Notes |
|---|---|---|
| GET | `/status` | Health, OpenVINO devices, queue, job counts |
| POST | `/jobs/generate_image` | `prompt` (≤1000 chars), `width`/`height` in 256, 512, 768, `session_id` |
| GET | `/jobs/<job_id>` | `queued` → `running` → `completed` / `failed` / `cancelled` / `rejected` |
| POST | `/jobs/<job_id>/cancel` | Queued jobs only |
| GET | `/artifacts/<job_id>` | PNG |

## Safety

- Listens only on the Tailscale address; every request needs the token.
- Bounded inputs, fixed sizes, queue cap of 8.
- No shell execution or arbitrary file paths are reachable from the API.
