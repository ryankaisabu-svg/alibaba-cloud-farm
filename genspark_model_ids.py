#!/usr/bin/env python3
"""Extract internal model IDs from genspark model selector DOM."""
import json, time, os, sys
sys.path.insert(0, ".")
from genspark_farm import run_account
from playwright.sync_api import sync_playwright

FARM_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(FARM_DIR, "data", "genspark")

with open(os.path.join(DATA_DIR, "genspark_accounts.txt"), "r") as f:
    acc = f.readline().strip().split("|")

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled", "--no-sandbox"])
    ctx = browser.new_context(
        viewport={"width": 1366, "height": 900},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    )

    print("=== LOGIN ===")
    result = run_account(browser, ctx, acc[0], acc[1], show_browser=False, idx=0, total=1)
    page = ctx.pages[-1]

    print("\n=== EXTRACT MODEL IDS ===")
    page.goto("https://www.genspark.ai/agents?type=ai_chat", wait_until="networkidle", timeout=90000)
    time.sleep(8)

    # Click model selector
    model_btn = page.wait_for_selector("span:has-text('Claude Haiku')", timeout=10000)
    if model_btn:
        model_btn.click()
        time.sleep(2)

    # Extract ALL model items with their internal IDs
    models = page.evaluate("""() => {
        const items = [];
        // Try multiple selectors for model options
        const allEls = document.querySelectorAll('*');
        for (const el of allEls) {
            const text = (el.innerText || '').trim();
            // Match model display names we know
            const modelPatterns = [
                /Claude\\s+(Haiku|Sonnet|Opus)\\s+[\\d.]+/,
                /GPT-[\\d.]+(?:\\s+(Mini|Nano|Pro))?/,
                /o[34]-pro/,
                /Gemini\\s+[\d.]+(?:\\s+\\w+(?:\\s+\\w+)?)?/,
                /DeepSeek\\s+V[\\d.]+(?:\\s+\\w+)?/,
                /Minimax\\s+M[\\d.]+/,
                /Kimi\\s+K[\\d.]+/,
                /GLM-[\\d.]+/,
                /Grok\\s+[\d.]+(?:\\s+\\w+)?/,
                /Search\\s+Web/,
            ];
            for (const pat of modelPatterns) {
                if (pat.test(text) && text.length < 60) {
                    // Found a model element — extract all attributes
                    const attrs = {};
                    for (const attr of el.attributes) {
                        attrs[attr.name] = attr.value;
                    }
                    // Check parent and children for data attributes
                    let parent = el.parentElement;
                    for (let i = 0; i < 3 && parent; i++) {
                        for (const attr of parent.attributes) {
                            if (attr.name.startsWith('data-') || attr.name === 'value') {
                                attrs['parent_' + attr.name] = attr.value;
                            }
                        }
                        parent = parent.parentElement;
                    }
                    items.push({
                        text: text,
                        tag: el.tagName,
                        id: el.id,
                        cls: (el.className || '').toString().substring(0, 80),
                        attrs: attrs,
                    });
                    break;
                }
            }
        }
        return items;
    }""")

    print(f"Found {len(models)} model elements:")
    for m in models:
        print(f"  {m['text']}")
        # Print any data-* or value attributes that might be the internal ID
        for k, v in m.get("attrs", {}).items():
            if any(x in k.lower() for x in ["value", "model", "id", "key", "slug"]):
                print(f"    {k}={v}")
        if m.get("id"):
            print(f"    element.id={m['id']}")

    # Also try: get model config from JS state
    print("\n=== JS STATE PROBE ===")
    js_models = page.evaluate("""() => {
        // Check __NUXT__ or other state
        const results = {};
        
        // Try __pinia__
        if (window.__pinia__) {
            results.pinia_keys = Object.keys(window.__pinia__);
        }
        
        // Try useNuxtApp
        if (window.useNuxtApp) {
            try {
                const app = window.useNuxtApp();
                if (app) results.nuxtApp = Object.keys(app).slice(0, 20);
            } catch(e) {}
        }
        
        // Try __NUXT__
        if (window.__NUXT__) {
            results.nuxt_keys = Object.keys(window.__NUXT__);
        }

        // Try to find model config in Vue app instance
        const appEl = document.querySelector('#__nuxt') || document.querySelector('[data-v-app]');
        if (appEl && appEl.__vue_app__) {
            results.vue_app = 'found';
            try {
                const config = appEl.__vue_app__.config;
                results.global_props = Object.keys(config.globalProperties || {}).slice(0, 20);
            } catch(e) {}
        }
        
        // Check Vue component instances for model data
        const allVueEls = document.querySelectorAll('[data-v-]');
        results.vue_components = allVueEls.length;
        
        // Get first 5 vue component instance data
        for (const el of allVueEls) {
            const inst = el.__vue__;
            if (inst && inst.$data) {
                const dataKeys = Object.keys(inst.$data);
                if (dataKeys.some(k => k.toLowerCase().includes('model'))) {
                    results.vue_data_with_model = dataKeys;
                    break;
                }
            }
        }
        
        return results;
    }""")
    
    print(f"  JS state: {json.dumps(js_models, indent=2)}")

    # Save
    out = os.path.join(DATA_DIR, "model_ids_extract.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(models, f, indent=2, ensure_ascii=False)
    print(f"\nSaved to {out}")

    browser.close()
