# SE ContentEdge Tools — Web UI

A web interface for ContentEdge administration tasks, starting with **Archiving Policy Generation**.

## Architecture

```
se_ce_tools/
├── backend/          Python FastAPI backend (port 8500)
│   ├── server.py     API endpoints + policy builder
│   └── requirements.txt
├── frontend/         Node.js + Express frontend (port 3000)
│   ├── server.js     Static file server + API proxy
│   ├── package.json
│   └── public/       Static assets (HTML, CSS, JS)
│       ├── index.html
│       ├── css/styles.css
│       └── js/app.js
├── start.cmd         Start both services
└── stop.cmd          Stop both services
```

## Quick Start

```bash
cd se_ce_tools
start.cmd
```

Open **http://localhost:3000** in your browser.

## Generate Archiving Policy — 4-Step Wizard

1. **Define Fields** — Select a source file, define fields (name, line, column, length, date format). The file viewer shows line/column indicators.
2. **Verify Extraction** — Preview extracted values from the first 3 pages.
3. **SECTION & VERSION** — Map fields to SECTION (multi-select, concatenated) and VERSION (single, usually a date).
4. **Name & Register** — Name the policy, view existing policies, and generate the Mobius-format JSON.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/files` | List available files in workspace/tmp/ |
| POST | `/api/files/upload` | Upload a sample file |
| GET | `/api/files/{name}/content` | Read file with page/line metadata |
| POST | `/api/extract` | Extract field values from file |
| GET | `/api/policies` | List existing archiving policies |
| POST | `/api/policies/generate` | Generate Mobius policy JSON |
| POST | `/api/policies/register` | Register policy in Mobius |
| GET | `/api/health` | Health check |

## Design

UI follows the [Rocket Software](https://www.rocketsoftware.com/) visual identity:
- Dark navy header with red accent
- Inter font family
- Red primary actions, clean card-based layout
- 4-step stepper with progress indicators
