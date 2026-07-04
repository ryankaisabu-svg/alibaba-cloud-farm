# Alibaba Cloud Farm — Multi-Provider API Key Harvesting Suite

Bulk-register accounts and harvest free API keys across multiple AI providers. Each account gets **free tokens** for their respective models.

## Providers

| Provider | Free Tokens | Engine | Status |
|----------|-----------|--------|--------|
| **Alibaba Cloud** (Qwen) | 1M tokens/account | Camoufox (Firefox anti-detect) | ✅ Stable |
| **SiliconFlow** | Variable per model | Patchright + Nodriver | ✅ Stable |
| **WaveSpeed.ai** | Variable | **Nodriver only** (CF bypass) | ✅ v31 |
| **Mistral AI** | Variable | Playwright/Patchright | ✅ |
| **Xiaomi** | Variable | Playwright/Patchright | ✅ |

## Architecture

```
alibaba-cloud-farm/
├── core/                    # Shared modules
│   ├── browser_engine.py    # Browser management (Camoufox, Nodriver, Playwright)
│   ├── captcha_solver.py    # CAPTCHA/slider solving strategies
│   ├── config.py            # .env loader & defaults
│   ├── email_providers.py   # IMAP OTP reading (Gmail, Outlook, custom)
│   ├── helpers.py           # Utilities (humanizer, delays, retry)
│   └── registry.py          # Farm registry / discovery
├── farms/                   # Farm implementations
├── gui/                     # CustomTkinter GUI app
│   ├── app.py               # Main window
│   ├── base_tab.py          # Base tab class
│   └── tabs.py              # Per-provider tabs
├── utils/                   # Shared utilities
│   ├── humanizer.py         # Text/behavior humanization
│   └── proxy_manager.py     # Proxy rotation
├── wavespeed_farm.py        # WaveSpeed farm (Nodriver, CF bypass)
├── siliconflow_farm.py      # SiliconFlow farm
├── mistral_farm.py          # Mistral AI farm
├── mistral_register.py      # Mistral account registration
├── alibaba_farm.py          # Alibaba/Qwen main farm
├── alibaba_register.py      # Alibaba account registration
├── xiaomi_farm.py           # Xiaomi farm
├── xiaomi_register.py       # Xiaomi account registration
├── email_farm.py            # Email/alias management
├── farm.py                  # CLI entry point (headless)
├── farm_gui.py              # GUI entry point
├── farm_headless.py         # Headless batch mode
├── config/config_solver.json# Solver preferences
├── .env                     # Credentials (gitignored!)
└── data/                    # Results (gitignored!)
```

## Quick Start

```bash
git clone https://github.com/ryankaisabu-svg/alibaba-cloud-farm.git
cd alibaba-cloud-farm

pip install -r requirements.txt

cp .env.example .env   # or create .env with your creds
```

Edit `.env`:

```env
# Gmail IMAP (for OTP verification)
IMAP_USER=your@gmail.com
IMAP_PASS=abcd efgh ijkl mnop    # App Password, NOT regular password
EMAIL_DOMAIN=your-catchall-domain.com

# Optional: CapSolver for reCAPTCHA
CAPSOLVER_API_KEY=CAP-xxxxx
```

## Usage

### WaveSpeed Farm (Nodriver — CF Bypass)

```bash
# Single account
python wavespeed_farm.py --email user@domain.com --pass PASSWORD --show

# Multiple accounts from file (format: email|password per line)
python wavespeed_farm.py --accounts-file gsuite_accounts.txt --count 10 --show

# Headless (no browser window)
python wavespeed_farm.py --email user@domain.com --pass PASSWORD
```

**Flow:** CF Turnstile (~120s) → Google OAuth → Email → Password → Speedbump/TOS → Consent → Dashboard → `/accesskey` → Generate API Key (`wsk_live_...`)

> ⚠️ Only **Nodriver** engine bypasses WaveSpeed's Cloudflare Turnstile. Patchright/Playwright get token=0.

### SiliconFlow Farm

```bash
python siliconflow_farm.py --email user@gsuite.com --pass xxxxx --show --debug
python siliconflow_farm.py --accounts-file sf_accounts.txt --count 50
```

### Alibaba Cloud / Qwen Farm

```bash
# GUI
python farm_gui.py

# Headless
python farm.py --provider alibaba --gmail user@gmail.com --apppass '**** **** **** ****'

# With display (slider solver needs screen)
xvfb-run -a python farm.py
```

### Mistral Farm

```bash
python mistral_farm.py --gmail user@gmail.com --apppass xxxx --count 5
```

### Xiaomi Farm

```bash
python xiaomi_farm.py --email user@domain.com --pass PASSWORD --show
```

## GUI

```bash
python farm_gui.py
```

CustomTkinter desktop app with tabs for each provider. Features:
- Real-time progress monitoring
- Per-account status tracking
- Start/Stop/Pause controls
- Batch processing with configurable concurrency

## Config Reference

| Variable | Required | Default | Description |
|---|---|---|---|
| `IMAP_USER` | ✅* | — | Gmail address for OTP reading |
| `IMAP_PASS` | ✅* | — | Gmail App Password (16 chars) |
| `EMAIL_DOMAIN` | ✅* | — | Catch-all domain for alias emails |
| `IMAP_HOST` | ❌ | `imap.gmail.com` | IMAP server hostname |
| `IMAP_PORT` | ❌ | `993` | IMAP port |
| `CAPSOLVER_API_KEY` | ❌ | — | CapSolver API key for reCAPTCHA |

*Required for providers that use email verification (Alibaba, Mistral, etc.)

## Prerequisites

### Catch-all Domain

You need a domain with **catch-all email forwarding** — any `*@yourdomain.com` lands in your inbox.

Options:
- **Cloudflare Email Routing** (free) — catch-all rule → forward to Gmail
- **ImprovMX** (free tier) — MX records → forward to your email
- **Self-hosted** — any mail server with catch-all alias

### Gmail App Password (for OTP)

1. Enable [2-Step Verification](https://myaccount.google.com/security)
2. Generate [App Password](https://myaccount.google.com/apppasswords)
3. Copy the 16-char password: `abcd efgh ijkl mnop`

## Results

Each provider saves results to its own JSON file under `data/<provider>/`:

```json
[
  {
    "email": "user@domain.com",
    "api_key": "wsk_live_xxxx" || "sk-xxxxx",
    "status": "complete",
    "timestamp": "2026-07-04 12:00:00"
  }
]
```

| File | Provider |
|---|---|
| `data/alibaba/alibaba_results.json` | Alibaba/Qwen |
| `data/siliconflow/siliconflow_results.json` | SiliconFlow |
| `data/wavespeed/wavespeed_results.json` | WaveSpeed |
| `data/mistral/` | Mistral AI |
| `data/xiaomi/` | Xiaomi |

> All `data/` files are **gitignored** — never committed.

## Notes

- **Cloudflare Turnstile** on WaveSpeed requires **Nodriver** engine only (~120s solve time). Other engines fail.
- **Slider captcha** appears ~50% on datacenter IPs for Alibaba. Script auto-skips and retries.
- **OTP extraction** uses regex on `<span>` tags, not CSS color codes (more reliable).
- **No proxy needed** for most providers — direct IP works.
- **Domain restriction**: Some providers (e.g., WaveSpeed) may restrict certain email domains.

## Security

- `.env` is gitignored — never commit credentials
- `data/` directory is gitignored — contains accounts, passwords, and API keys
- No hardcoded credentials in any source file
- All credentials passed via CLI args or environment variables

## License

MIT
