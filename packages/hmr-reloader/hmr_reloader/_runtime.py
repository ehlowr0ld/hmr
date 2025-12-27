from __future__ import annotations

from pathlib import Path

RUNTIME_JS = Path(__file__).with_name("runtime.js").read_text("utf-8")
INJECTION = f"\n\n<script>\n{RUNTIME_JS}\n</script>".encode()
