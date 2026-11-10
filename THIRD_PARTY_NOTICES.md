# Third-party notices

All application code in this repository was written for Perry. No source code was copied
from the projects studied in `docs/ARCHITECTURE_RESEARCH.md` (OpenFelix, OpenComputer, pan-agent,
browser-use, browser-harness, MCP, Cua, Pipecat); they informed design only.

## Services

| Service | Use | Terms |
|---|---|---|
| Gnani AI Speech APIs: Prisma v2.5 (STT), Timbre v2.5 (TTS) | Voice input and output | Gnani API terms (app.gnani.ai) |
| OpenAI API (optional) | Planner for free-form commands (gpt-5.4-mini) | OpenAI terms |
| Gnani Evon v3.3 (optional, self-hosted) | Alternative planner via OpenAI-compatible server | Apache-2.0 (model card) |
| Cloudflare quick tunnels (demo tooling, not bundled) | Public HTTPS URL for local demos | Cloudflare Online Services Terms |

## Python dependencies

| Package | Licence |
|---|---|
| fastapi | MIT |
| uvicorn | BSD-3-Clause |
| pydantic, pydantic-settings | MIT |
| httpx | BSD-3-Clause |
| python-multipart | Apache-2.0 |
| jsonschema | MIT |
| websockets | BSD-3-Clause |
| qrcode | BSD-3-Clause |
| pytest, pytest-asyncio (dev) | MIT / Apache-2.0 |

## JavaScript dependencies

| Package | Licence |
|---|---|
| react, react-dom | MIT |
| motion | MIT |
| vite, @vitejs/plugin-react | MIT |
| tailwindcss, @tailwindcss/vite | MIT |
| typescript | Apache-2.0 |

Full licence texts ship with each package in `.venv/` and `web/node_modules/`.
