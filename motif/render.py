"""Render a compiled scene to a single self-contained HTML file.

The HTML embeds the compiled tracks as JSON plus a ~150-line SVG player
(player.js). No server, no dependencies: open the file in any browser.

The player also exposes `window.motif.seek(t)` so a headless browser
(Playwright) can step through frames to export a video later.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

PLAYER_JS = (Path(__file__).parent / "player.js").read_text()

TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: dark; }}
  body {{ margin: 0; background: #08090c; color: #ddd; font: 14px system-ui, sans-serif;
         display: flex; flex-direction: column; align-items: center; gap: 12px; padding: 16px; }}
  #stage {{ width: min(100%, 1100px); aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden;
           box-shadow: 0 8px 30px #0008; }}
  #stage svg {{ width: 100%; height: 100%; display: block; }}
  .controls {{ width: min(100%, 1100px); display: flex; gap: 12px; align-items: center; }}
  button {{ background: #1d2230; color: #eee; border: 1px solid #333a4d; border-radius: 6px;
           padding: 6px 14px; cursor: pointer; font: inherit; }}
  input[type=range] {{ flex: 1; }}
  #time {{ font-variant-numeric: tabular-nums; min-width: 90px; text-align: right; }}
  h1 {{ font-size: 15px; font-weight: 500; margin: 0; width: min(100%, 1100px); color: #aab; }}
</style>
</head>
<body>
<h1>{title}</h1>
<div id="stage"></div>
<div class="controls">
  <button id="play">Pause</button>
  <button id="restart">Restart</button>
  <input id="scrub" type="range" min="0" max="1000" value="0">
  <span id="time">0.00s</span>
</div>
<script id="motif-data" type="application/json">{data}</script>
<script>
{player}
</script>
</body>
</html>
"""


def to_html(compiled: dict) -> str:
    data = json.dumps(compiled, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.format(title=html.escape(compiled["title"]), data=data, player=PLAYER_JS)
