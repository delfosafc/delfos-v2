# delfos

Python library for controlling the Delfos geophysical equipment (Central + UASGs)
over a serial port. Sucessor of `SB64_dash/switch.py`, redesigned as an importable
library with thin CLI and TUI frontends; a graphical UI lives in separate
consumer projects.

See [`CLAUDE.md`](CLAUDE.md) for architecture and conventions, and
[`PLAN.md`](PLAN.md) for the implementation roadmap. Protocol reference in
[`protocol.md`](protocol.md), implementation in [`delfos/protocol.py`](delfos/protocol.py).

## Setup

```bash
uv sync --all-extras
uv run pytest
```
