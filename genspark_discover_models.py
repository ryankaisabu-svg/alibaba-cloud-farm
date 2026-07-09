#!/usr/bin/env python3
"""Discover genspark chat/LLM models — intercept API + JS analysis."""
import json, time, os, re
from playwright.sync_api import sync_playwright

FARM_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(FARM_DIR, "data", "genspark")
os.makedirs(DATA_DIR, exist_ok=True)

with open(os.path.join(DATA_DIR, "genspark_results.json"), "r", encoding="utf-8") as f:
    data = json.load(f)
r = data[-1]

cookies_list = [
    {"name": k, "value": v, "domain": ".genspark.ai", "path": "/"}
    for k, v in r.get("genspark_cookies", {}).items()
]

with sync_playwright() as pw:
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    )
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    # Attach response handler BEFORE navigation
    api_calls = []
    def capture_response(response):
        url = response.url
        if "genspark.ai/api/" in url:
            try:
                body = response.text()
                api_calls.append({"url": url, "status": response.status, "body": body[:5000]})
                print(f"  [API] {response.status} {url[:100]}")
            except Exception:
                pass
    page.on("response", capture_response)

    print("Loading https://www.genspark.ai/ ...")
    page.goto("https://www.genspark.ai/", wait_until="domcontentloaded", timeout=60000)
    print("Waiting 15s for SPA hydration...")
    time.sleep(15)
    print(f"Title: {page.title()}")
    print(f"URL: {page.url}")
    print(f"API calls captured: {len(api_calls)}")

    # Print all captured API calls
    for ac in api_calls:
        print(f"  {ac['status']} {ac['url'][:120]}")

    # Now fetch models_config in-browser (we know this works)
    print("\nFetching /api/models_config ...")
    mc = page.evaluate("""async () => {
        const r = await fetch('/api/models_config', {credentials: 'include'});
        return await r.json();
    }""")
    print(f"  Keys: {list(mc.get('data', {}).keys())}")

    # Try to find chat/search model config
    print("\nProbing additional endpoints...")
    endpoints_to_try = [
        "/api/search/config",
        "/api/chat/config",
        "/api/agent/config",
        "/api/search/model_options",
        "/api/search/v2/config",
    ]
    for ep in endpoints_to_try:
        result = page.evaluate(f"""async () => {{
            try {{
                const r = await fetch('{ep}', {{credentials: 'include'}});
                if (r.ok) return {{status: r.status, body: await r.json()}};
                return {{status: r.status}};
            }} catch(e) {{ return {{error: e.message}}; }}
        }}""")
        if result.get("status") == 200:
            print(f"\n  [200] {ep}")
            compact = json.dumps(result["body"], ensure_ascii=False)
            if len(compact) > 1000:
                compact = compact[:1000] + "..."
            print(f"  {compact}")

    # Extract model IDs from page HTML/scripts
    print("\nScanning page source for model IDs...")
    html = page.content()
    # Search for model patterns in inline scripts
    model_pattern = re.compile(r'["\']((?:claude|gpt|gemini|llama|deepseek|qwen|mistral|kimi|o[134]|grok|phi|command-r| GLM|flux|sora)[a-zA-Z0-9._\-]+)["\']', re.IGNORECASE)
    matches = model_pattern.findall(html)
    unique_models = sorted(set(matches))
    print(f"  Found {len(unique_models)} unique model references:")
    for m in unique_models:
        print(f"    {m}")

    # Save everything
    out = os.path.join(DATA_DIR, "genspark_models_discovery.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({
            "api_calls": [{"url": a["url"], "status": a["status"]} for a in api_calls],
            "models_config": mc,
            "model_ids_found": unique_models,
        }, f, indent=2, ensure_ascii=False)
    print(f"\nSaved discovery to {out}")

    browser.close()
