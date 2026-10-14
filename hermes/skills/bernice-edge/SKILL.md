---
name: bernice-edge
description: Generate an image on the Bernice Edge room display node (Crestron Collab Compute) and check that node's status. Use when someone asks Bernice to create, draw, render or show an image, picture, illustration, visualization or diagram for the room display.
---

# bernice-edge — Room Display Image Generation

## Role

You delegate visual jobs from the Spark to the Bernice Edge node, a Crestron
Collab Compute in the room. The edge renders the image on its own Intel GPU and
drives the room display. You do not generate images yourself and you do not
log in to the edge.

## When to use

- "Create / generate / make / draw / show me an image / picture / visualization / diagram of ..."
- "Put a picture of ... on the room display"
- "Is the display node up?" / "What can the edge node run?"

Do not use this skill for HDMI routing, Vertex cues, lighting or audio. Those are
separate device-control paths.

## Tools

- terminal — run only the script below. Never print, echo or cat `~/.env_secrets`.

## Commands

Check the edge node:

    ~/.hermes/skills/bernice-edge/scripts/edge.sh status

Generate an image (waits for completion, about 3 s today):

    ~/.hermes/skills/bernice-edge/scripts/edge.sh generate "<visual description>"

## Writing the visual description

Turn the request into one clear, concrete sentence describing the picture:
subject, setting, viewpoint and style. Keep it under 300 characters, plain text,
no quotation marks inside it. Example: request "show how sound travels in a
classroom" → `cutaway illustration of a lecture hall with sound waves spreading
from the speaker and reflecting off the walls and ceiling, clean educational style`.

## Reading the result

The script prints JSON. Report back briefly:

1. Outcome — `status` (completed, failed, rejected, timed_out).
2. Timing — `ack_ms` (edge acknowledgement) and `total_ms`.
3. Where it ran — `model` and `device`.
4. The saved image path from the last line (`/tmp/<job_id>.png` on the Spark).

If `status` is `rejected` with `queue full`, say the display node is busy and to try again shortly.
If the script reports a connection error, say the room display node is unreachable;
do not retry more than once.

## Current limits (Sprint 1)

- The edge returns a **test pattern**, not a real image. Say so plainly if asked
  what was generated. Real image generation arrives in Sprint 2.
- Sizes: 512 x 512 by default (256, 512 or 768 allowed by the edge).
- The image is not yet shown on the room display automatically.

## Scope

Read-only toward everything except the edge job API. No other commands, no file
changes, no network calls beyond the script.
