#!/usr/bin/env python3
"""Click genspark model selector on agents page and extract all model names."""
import json, time, os
from playwright.sync_api import sync_playwright

FARM_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(FARM_DIR, "data", "genspark")

with open(os.path.join(DATA_DIR, "genspark_results.json"), "r", encoding="utf-8") as f:
    data = json.load(f)
r = data[-1]

cookies_list = [
    {"name": k, "value": v, "domain": ".genspark.ai", "path": "/"}
    for k, v in r.get("genspark_cookies", {}).items()
]

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    )
    ctx.add_cookies(cookies_list)
    page = ctx.new_page()

    api_calls = []
    def on_resp(resp):
        url = resp.url
        if "genspark.ai/api/" in url:
            try:
                body = resp.text()
                api_calls.append({"url": url, "status": resp.status, "body": body[:10000]})
            except:
                pass
    page.on("response", on_resp)

    print("Loading agents page...")
    try:
        page.goto("https://www.genspark.ai/agents?type=ai_chat", wait_until="networkidle", timeout=90000)
    except:
        pass
    time.sleep(5)
    print(f"Title: {page.title()}")

    # Screenshot 1: initial state
    page.screenshot(path=os.path.join(DATA_DIR, "agents_01_initial.png"))
    print("Screenshot: initial state")

    # Find and click any element that contains "Claude Haiku 4.5" or model-related text
    print("\nLooking for model selector elements...")
    
    # Try multiple selectors
    selectors_to_try = [
        # Model selector buttons/labels
        'span:has-text("Claude")',
        'div:has-text("Claude Haiku")',
        'button:has-text("Claude")',
        '[class*="model"]',
        '[class*="selector"]',
        '[class*="dropdown"]',
        # Generic clickable elements with model text
        '*:has-text("Claude Haiku 4.5")',
    ]
    
    clicked = False
    for sel in selectors_to_try:
        try:
            els = page.query_selector_all(sel)
            for el in els:
                try:
                    txt = el.inner_text().strip()
                    if txt and "Claude" in txt:
                        print(f"  Found element: [{sel}] text='{txt[:60]}'")
                        el.click()
                        time.sleep(2)
                        clicked = True
                        break
                except:
                    continue
            if clicked:
                break
        except:
            continue

    if clicked:
        page.screenshot(path=os.path.join(DATA_DIR, "agents_02_model_open.png"))
        print("Screenshot: after clicking model selector")

        # Collect all visible model names after clicking
        time.sleep(2)
        body_text = page.inner_text("body")
        print("\n=== All model names visible after click ===")
        model_keywords = ["Claude", "GPT", "Gemini", "GLM", "Llama", "DeepSeek", "Qwen", "Mistral", "Kimi", "Grok", "o1", "o3", "o4", "Flash", "Sonnet", "Opus", "Haiku", "Pro", "Search", "Nano", "Hermes", "Command", "Phi", "Yi"]
        for line in body_text.split("\n"):
            line = line.strip()
            if line and any(kw in line for kw in model_keywords):
                print(f"  {line[:120]}")

        # Also dump all visible text
        print("\n=== Full visible text after model click (filtered) ===")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        for line in lines[:80]:
            print(f"  {line[:150]}")
    else:
        print("  Could not find model selector to click")
        
        # Dump all buttons/interactive elements
        print("\n=== All clickable elements on page ===")
        all_els = page.query_selector_all("button, [role='button'], [role='option'], [role='listbox'], select, .dropdown, [class*='select']")
        for el in all_els[:30]:
            try:
                txt = el.inner_text().strip()
                tag = el.evaluate("e => e.tagName")
                cls = el.evaluate("e => e.className").strip()[:60]
                if txt:
                    print(f"  <{tag} class='{cls}'> {txt[:80]}")
            except:
                pass

    # Save API calls
    out = os.path.join(DATA_DIR, "agents_model_click.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(api_calls, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(api_calls)} API calls")

    browser.close()
