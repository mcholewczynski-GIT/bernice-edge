# Spark integration (Bernice Edge)

| File | Purpose |
|---|---|
| `edge_client.py` | HTTP client for the edge job API; also a CLI test |
| `edge_intent.py` | Regex intent match for image requests (same pattern as `hdmi_intent.py`) |
| `edge_skill.py` | Routed-loop skill: submits the job, speaks at once, follows progress in a thread |

The routed loop imports these from `/home/admin` (as it does `hdmi_intent.py`).
The skill is **off** unless `BERNICE_EDGE_ENABLED=1`; if the files are missing,
the loop behaves exactly as before.

## Settings — `/home/admin/.config/bernice-edge/spark.env` (mode 600, no `export`)

```
BERNICE_EDGE_ENABLED=1
EDGE_URL=http://bernice-edge-01:8790
EDGE_TOKEN=<token>
```

Turn the skill off: set `BERNICE_EDGE_ENABLED=0` and restart `bernice-routed-loop`.

## Example phrases

"Bernice, create a visualization of how sound travels through a classroom."
"Show me an image of a coral reef." · "Make a diagram of the water cycle."
