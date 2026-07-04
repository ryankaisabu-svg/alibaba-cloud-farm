#!/usr/bin/env python3
"""
WaveSpeed Farm v31 — Bulk API Key Extraction via Google OAuth + Cloudflare Bypass
================================================================================

Engine: NODRIVER (real Chrome CDP — only engine that bypasses WaveSpeed's CF Turnstile)

Flow per akun:
  1. Open wavespeed.ai/sign-in + accept cookie
  2. Wait for CF Turnstile invisible verification (token > 50 chars, ~110-130s)
  3. Click "Sign in with Google"
  4. OAuth redirect → fill email → Next
  5. Fill password → Sign In
  6. Handle post-login screens (password challenge / speedbump / consent)
  7. Dashboard reached → navigate to /accesskey
  8. Enter key name → click Generate → extract wsk_live_... key from <code> element
  9. Save result to JSON

Input:
  --email user@domain.com --pass password    Single account
  --accounts-file accounts.txt               Multiple accounts (email|password per line)
  --count N                                   Max accounts to process
  --show                                      Show browser (headless=False)

Usage:
  python wavespeed_farm.py --email user@domain.com --pass xxx --show
  python wavespeed_farm.py --accounts-file gsuite_accounts.txt --count 10 --show
"""
import asyncio
import json
import os
import sys

# ── Path setup ──────────────────────────────────────
FARM_DIR = os.path.dirname(os.path.abspath(__file__))
if FARM_DIR not in sys.path:
    sys.path.insert(0, FARM_DIR)
_DATA_DIR = os.path.join(FARM_DIR, "data", "wavespeed")
os.makedirs(_DATA_DIR, exist_ok=True)
RESULTS_FILE = os.path.join(_DATA_DIR, "wavespeed_results.json")
SCREENSHOT_DIR = os.path.join(FARM_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)


# ════════════════════════════════════════════════════
# JS SNIPPETS (pre-built, avoid quote escaping hell)
# ════════════════════════════════════════════════════

JS_CF_POLL = """(() => {
  var ti=document.querySelector('input[name="cf-turnstile-response"]');
  var btn=document.querySelector('[aria-label="Sign in with Google"]');
  if(!ti || !btn) return JSON.stringify({vl:0,bd:null});
  return JSON.stringify({vl:(ti.value||'').length,bd:btn.disabled});
})()"""

JS_GOOGLE_BTN = """(() => {
  var el=document.querySelector('[aria-label="Sign in with Google"]');
  if(!el||el.getBoundingClientRect().width===0)return null;
  var r=el.getBoundingClientRect();
  return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
})()"""

JS_GOOGLE_BTN_FALLBACK = """(() => {
  for(var e of document.querySelectorAll('button')){
    var t=(e.innerText||'');
    if(t.includes('Google')&&!t.includes('GitHub')&&e.getBoundingClientRect().width>0){
      var r=e.getBoundingClientRect();
      return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
    }
  }return null;
})()"""

JS_FILL_EMAIL = None   # built dynamically with email addr
JS_FILL_PASSWORD = None # built dynamically with password

JS_FIND_BTN = None       # built dynamically with text_matches + id_matches
JS_FIND_TEXT_BTN = None  # built dynamically with text list
JS_FIND_ANY_BTN = """(() => {
  for(var e of document.querySelectorAll('button,[role=button],a')){
    var r=e.getBoundingClientRect();
    if(r.width>50&&r.height>20&&r.width<500&&r.height<100){
      return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
        text:(e.innerText||e.value||'').trim().substring(0,50)});
    }
  }return null;
})()"""

JS_CONTINUE_BTN = """(() => {
  for(var e of document.querySelectorAll('*')){
    var t=(e.innerText||'').trim();
    if((t==='Continue'||t==='continue')&&e.getBoundingClientRect().width>10){
      var r=e.getBoundingClientRect();
      return JSON.stringify({tag:e.tagName,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
    }
  }return null;
})()"""

JS_EXTRACT_KEY = """(() => {
  var codes=document.querySelectorAll('code');
  for(var c=0;c<codes.length;c++){
    var txt=(codes[c].innerText||'').trim();
    if(txt.startsWith('wsk_live_')||txt.startsWith('wsk_test_'))return txt;
  }
  var m=(document.body||{}).innerText?.match(/wsk_live_[a-zA-Z0-9_-]{20,}/);
  if(m)return m[0];
  var m2=(document.body||{}).innerText?.match(/sk-[a-zA-Z0-9]{15,}/);
  if(m2)return m2[0];
  return '';
})()"""


# ════════════════════════════════════════════════════
# CLI ARGS
# ════════════════════════════════════════════════════

def parse_args():
    args = {'email': None, 'password': None, 'accounts_file': None,
            'count': 1, 'show': False}
    i = 0
    while i < len(sys.argv):
        a = sys.argv[i]
        if a == '--email' and i+1 < len(sys.argv):
            args['email'] = sys.argv[i+1]; i += 2
        elif a == '--pass' and i+1 < len(sys.argv):
            args['password'] = sys.argv[i+1]; i += 2
        elif a == '--accounts-file' and i+1 < len(sys.argv):
            args['accounts_file'] = sys.argv[i+1]; i += 2
        elif a == '--count' and i+1 < len(sys.argv):
            try: args['count'] = int(sys.argv[i+1])
            except: pass
            i += 2
        elif a == '--show':
            args['show'] = True; i += 1
        else:
            i += 1
    return args


def load_accounts(filepath):
    """Load accounts from file. Format: email|password per line."""
    accounts = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('|')
            if len(parts) >= 2:
                accounts.append({'email': parts[0].strip(), 'password': parts[1].strip()})
    return accounts


# ════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════

async def js(tab, expression, default=""):
    """Safe JS evaluate — returns string or default on error."""
    try:
        result = await tab.evaluate(expression)
        if result is None:
            return default
        return str(result)
    except Exception:
        return default


async def body_text(tab, length=300):
    """Get visible page body text."""
    return await js(tab, "(document.body||{}).innerText?.substring(0,{})||''".format(length), "")


def is_dashboard(url):
    """Check if URL looks like WaveSpeed dashboard (not sign-in, not Google)."""
    if not url:
        return False
    url = str(url).lower()
    return ('wavespeed.ai' in url and '/sign-in' not in url
            and 'google.com' not in url and url.strip()
            and 'error=' not in url)


async def fill_email(tab, email_addr):
    """Fill Google identifier field using nativeInputValueSetter."""
    script = """(() => {
      var el=document.querySelector('input[name="identifier"]');
      if(!el) return 'NOT_FOUND';
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
        .set.call(el,'""" + email_addr + """');
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      return 'OK:'+el.value;
    })()"""
    await tab.evaluate(script)


async def fill_password(tab, password):
    """Fill Google password field using nativeInputValueSetter."""
    script = """(() => {
      var el=document.querySelector('input[type="password"],input[name="Passwd"]');
      if(!el) return 'NOT_FOUND';
      Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
        .set.call(el,'""" + password + """');
      el.dispatchEvent(new Event('input',{bubbles:true}));
      el.dispatchEvent(new Event('change',{bubbles:true}));
      el.dispatchEvent(new Event('keyup',{bubbles:true}));
      return 'OK:'+el.value.length;
    })()"""
    await tab.evaluate(script)


async def find_btn(tab, text_matches, id_matches=None):
    """Find button by text content or ID → return {x,y} JSON string."""
    texts = json.dumps(text_matches)
    ids = json.dumps(id_matches or [])
    script = """(() => {
      var texts=""" + texts + """;
      var ids=""" + ids + """;
      for(var e of document.querySelectorAll('#passwordNext,#identifierNext,[role=button],button')){
        var t=(e.innerText||'').trim().toLowerCase();
        var idMatch=ids.length>0 && ids.includes(e.id);
        var txtMatch=texts.some(function(x){return t.includes(x)||t===x});
        if((txtMatch||idMatch)&&e.getBoundingClientRect().width>0){
          var r=e.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
        }
      }return null;
    })()"""
    return await tab.evaluate(script)


async def find_text_btn(tab, text_list):
    """Find any element by its text content (case-insensitive)."""
    targets = json.dumps(text_list)
    script = """(() => {
      var targets=""" + targets + """;
      for(var e of document.querySelectorAll('[role=button],button,a,div[role=button],span')){
        var t=(e.innerText||'').trim().toLowerCase();
        if(targets.some(function(x){return t===x||t.includes(x)}) && e.getBoundingClientRect().width>0){
          var r=e.getBoundingClientRect();
          return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),
            tag:e.tagName,text:t});
        }
      }return null;
    })()"""
    return await tab.evaluate(script)


async def click_coords(tab, x, y, label=""):
    """Click at coordinates with tiny delay."""
    await tab.mouse_click(int(x), int(y))


async def screenshot(tab, name):
    """Save screenshot, suppress errors."""
    try:
        path = os.path.join(SCREENSHOT_DIR, name)
        await tab.save_screenshot(path)
    except Exception:
        pass


def save_result(email, api_key):
    """Append {email, api_key} to results JSON file."""
    results = []
    if os.path.exists(RESULTS_FILE):
        try:
            with open(RESULTS_FILE, 'r') as f:
                results = json.load(f)
        except (json.JSONDecodeError, IOError):
            results = []

    results.append({"email": email, "api_key": api_key})

    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    return len(results)


# ════════════════════════════════════════════════════
# CORE FLOW: single account
# ════════════════════════════════════════════════════

async def run_account(browser, email, password, log_fn, idx=0):
    """
    Full flow for ONE account.
    Returns: dict with keys: success, api_key, error (optional)
    """
    tag = "A{}".format(idx)
    KEY_NAME = "key-{}".format(idx)
    tab = None

    try:
        tab = await browser.get("https://wavespeed.ai/sign-in")

        # ── Cookie ──
        await asyncio.sleep(5)
        ac = await js(tab, """(() => {
          for(var e of document.querySelectorAll('button,a,[role=button]')){
            if(['accept','ok','agree'].includes((e.innerText||'').trim().toLowerCase())){
              e.click();return 'ok';
            }
          }return null;
        })()""")
        log_fn("[{}] Cookie: {}".format(tag, ac or 'none'))
        await asyncio.sleep(2)

        # ── STEP 1: CF Turnstile (poll until token > 50, max 200s) ──
        log_fn("[{}] CF Turnstile polling...".format(tag))
        cf_ok = False
        for tick in range(1000):
            await asyncio.sleep(0.2)
            r = await js(tab, JS_CF_POLL)
            try:
                info = json.loads(r) if isinstance(r, str) else {}
                vl = info.get('vl', 0); bd = info.get('bd')
                if isinstance(vl, int) and vl > 50:
                    cf_ok = True; log_fn("[{}] TOKEN={}ch @{:.0f}s".format(tag, vl, tick*0.2)); break
                if bd is False:
                    cf_ok = True; log_fn("[{}] Button enabled @{:.0f}s".format(tag, tick*0.2)); break
                if tick % 125 == 0 and tick > 0:
                    log_fn("[{}] [{:.0f}s] tok={} disabled={}".format(tag, tick*0.2, vl, bd))
                if tick >= 999:
                    log_fn("[{}] CF TIMEOUT".format(tag)); return {"success": False, "error": "cf_timeout"}
            except Exception:
                pass

        await asyncio.sleep(0.5)

        # ── STEP 2: Click "Sign in with Google" ──
        gb = await js(tab, JS_GOOGLE_BTN)
        if not gb or gb == 'null':
            gb = await js(tab, JS_GOOGLE_BTN_FALLBACK)
        if not gb or gb == 'null':
            log_fn("[{}] No Google button found".format(tag)); return {"success": False, "error": "no_google_btn"}

        g = json.loads(gb); await click_coords(tab, g['x'], g['y'], "google-btn")
        log_fn("[{}] Google clicked!".format(tag))

        # ── STEP 3: Wait for OAuth redirect ──
        on_google = False
        for wi in range(30):
            await asyncio.sleep(1)
            gu = await js(tab, "window.location.href")
            if 'accounts.google.com' in str(gu):
                on_google = True; break
        if not on_google:
            log_fn("[{}] No OAuth redirect".format(tag)); return {"success": False, "error": "no_redirect"}
        log_fn("[{}] On Google page".format(tag))

        await asyncio.sleep(3)

        # ── STEP 4: Fill Email ──
        log_fn("[{}] Email: {}".format(tag, email))
        er = await fill_email(tab, email)
        actual_er = await js(tab, "(document.querySelector('input[name=\"identifier\"]')||{}).value", "")
        log_fn("[{}] Result: {}".format(tag, actual_er))
        if 'NOT_FOUND' in str(er):
            log_fn("[{}] Email input NOT FOUND".format(tag)); return {"success": False, "error": "email_not_found"}

        nj = await find_btn(tab, ['next'], ['#identifierNext'])
        if nj and nj != 'null':
            n = json.loads(nj); await click_coords(tab, n['x'], n['y'], "next-email")

        # ── Wait for password field ──
        pw_found = False
        for pi in range(20):
            await asyncio.sleep(0.5)
            if await js(tab, "(document.querySelector('input[type=\"password\"]')||{}).tagName", "") == 'INPUT':
                pw_found = True; break
        if not pw_found:
            log_fn("[{}] Password field NOT FOUND".format(tag)); return {"success": False, "error": "no_pwd_field"}

        # ── STEP 5: Fill Password ──
        log_fn("[{}] Password...".format(tag))
        pr = await fill_password(tab, password)
        pr_actual = await js(tab, "(document.querySelector('input[type=\"password\"]')||{}).value.length", "0")
        log_fn("[{}] Pwd chars: {}".format(tag, pr_actual))

        sj = await find_btn(tab, ['sign in', 'next'], ['#passwordNext'])
        if sj and sj != 'null':
            s = json.loads(sj); await click_coords(tab, s['x'], s['y'], "signin-btn")
            log_fn("[{}] Sign In clicked!".format(tag))
        else:
            log_fn("[{}] Sign In button NOT FOUND".format(tag)); return {"success": False, "error": "no_signin_btn"}

        # ── STEP 6: Post-Sign-In Monitoring ──
        # Handles: back-to-email, password-challenge, speedbump/TOS, consent, dashboard
        log_fn("[{}] Post-sign-in monitoring...".format(tag))
        email_retry = 0; pwd_retry = 0

        for ci in range(100):
            await asyncio.sleep(2)

            cur_url = await js(tab, "window.location.href")
            btxt = await body_text(tab, 300)
            elapsed = (ci + 1) * 2
            url_l = str(cur_url).lower()

            # Page type detection by URL
            is_email = '/identifier' in url_l
            is_pwd = '/password' in url_l or ('challenge' in url_l and 'pwd' in url_l)
            is_speedbump = 'speedbump' in url_l or 'termsofservice' in url_l
            is_consent = '/signin/oauth' in url_l
            is_error = 'error=' in url_l or 'domain_restricted' in url_l

            # ✅ SUCCESS: Dashboard
            if is_dashboard(url_l) and not is_error:
                log_fn("[{}] *** DASHBOARD REACHED! ***".format(tag))
                api_key = await do_generate_api_key(tab, email, KEY_NAME, log_fn, tag)
                if api_key:
                    total = save_result(email, api_key)
                    log_fn("[{}] DONE! Key saved ({}/total)".format(tag, total))
                    return {"success": True, "api_key": api_key}
                else:
                    return {"success": False, "error": "key_gen_failed"}

            # ❌ Domain / error page
            if is_error and elapsed > 10:
                log_fn("[{}] ERROR page: {} ... stopping".format(tag, cur_url[:100]))
                await screenshot(tab, "ws_err_{}.png".format(idx))
                return {"success": False, "error": "domain_restricted", "url": cur_url}

            # 🔁 Back to email page → click Next again
            if is_email and ci > 2:
                email_retry += 1
                if email_retry > 5:
                    log_fn("[{}] Too many email retries".format(tag)); return {"success": False, "error": "email_loop"}
                log_fn("[{}] [{}] Back to email (#{}) - clicking Next".format(tag, elapsed, email_retry))
                nj2 = await find_btn(tab, ['next'], ['#identifierNext'])
                if nj2 and nj2 != 'null':
                    n2 = json.loads(nj2); await click_coords(tab, n2['x'], n2['y'], "next-retry")
                await asyncio.sleep(3); continue

            # 🔁 Password challenge → re-enter password
            if is_pwd and ci > 2:
                pwd_retry += 1
                if pwd_retry > 3:
                    log_fn("[{}] Too many password retries".format(tag)); return {"success": False, "error": "pwd_loop"}
                log_fn("[{}] [{}] Password challenge (#{})".format(tag, elapsed, pwd_retry))
                await fill_password(tab, password)
                await asyncio.sleep(0.5)
                sj2 = await find_btn(tab, ['sign in', 'next'], ['#passwordNext'])
                if sj2 and sj2 != 'null':
                    s2 = json.loads(sj2); await click_coords(tab, s2['x'], s2['y'], "signin-retry")
                continue

            # 📋 Speedbump / TOS → "I Understand" button
            if is_speedbump:
                log_fn("[{}] [{}] Speedbump/TOS".format(tag, elapsed))
                sb = await find_text_btn(tab, ['i understand', 'i agree', 'accept', 'agree to terms'])
                if sb and sb != 'null':
                    btn = json.loads(sb)
                    log_fn("[{}] '{}' @ ({},{})".format(tag, btn.get('text','?'), btn['x'], btn['y']))
                    await click_coords(tab, btn['x'], btn['y'], "speedbump")
                else:
                    abtn = await js(tab, JS_FIND_ANY_BTN)
                    if abtn and abtn != 'null':
                        a = json.loads(abtn); await click_coords(tab, a['x'], a['y'], "speedbump-any")
                continue

            # 📋 Consent → "Continue" button
            if is_consent:
                log_fn("[{}] [{}] Consent page".format(tag, elapsed))
                cp = await js(tab, JS_CONTINUE_BTN)
                if cp and cp != 'null':
                    cb = json.loads(cp); await click_coords(tab, cb['x'], cb['y'], "consent-continue")
                else:
                    for coord in [(715, 497), (750, 520), (807, 580)]:
                        await click_coords(tab, coord[0], coord[1], "consent-fallback"); await asyncio.sleep(1)
                continue

            # Debug: unknown pages
            if ci < 4:
                log_fn("[{}] [{}]s | {} | {}".format(tag, elapsed,
                    cur_url[:60] if cur_url else '?',
                    btxt[:80] if btxt else ''))

        log_fn("[{}] TIMEOUT after monitoring".format(tag))
        await screenshot(tab, "ws_timeout_{}.png".format(idx))
        return {"success": False, "error": "timeout"}

    except Exception as ex:
        log_fn("[{}] FATAL: {}: {}".format(tag, type(ex).__name__, ex))
        return {"success": False, "error": str(ex)[:200]}


# ════════════════════════════════════════════════════
# STEP 8: Generate API Key on /accesskey
# ════════════════════════════════════════════════════

async def do_generate_api_key(tab, email, key_name, log_fn, tag=""):
    """
    Navigate to /accesskey, enter key name, generate, extract wsk_live_... key.
    Returns: api_key string or None
    """
    log_fn("[{}] /accesskey -> generating key...".format(tag))
    await asyncio.sleep(2)

    try:
        await tab.get("https://wavespeed.ai/accesskey")
        await asyncio.sleep(6)
        await screenshot(tab, "ws_accesskey.png")

        # Check if there's already a key visible
        existing = await js(tab, JS_EXTRACT_KEY)
        if existing and len(existing) > 10:
            log_fn("[{}] Key already exists: {}...".format(tag, existing[:20]))
            return existing

        # Find the "Enter key name" input
        inp_info = await js(tab, """(() => {
          var inputs=document.querySelectorAll('input');
          for(var i=0;i<inputs.length;i++){
            var inp=inputs[i], ph=(inp.placeholder||'').toLowerCase();
            if(ph.includes('key name')||(inp.value===''&&inp.offsetWidth>100)){
              var r=inp.getBoundingClientRect();
              return JSON.stringify({
                ph:inp.placeholder,id:inp.id,name:inp.name,
                x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2),vis:r.width>0
              });
            }
          }return 'NOT_FOUND';
        })()""")

        if not inp_info or inp_info in ('NOT_FOUND', 'None', 'null'):
            log_fn("[{}] Key name input not found".format(tag))
            # Dump all inputs for debugging
            all_in = await js(tab, """(() => {
            return Array.from(document.querySelectorAll('input')).map(function(e){
              return {t:e.type,n:e.name,id:e.id,p:(e.placeholder||'').substring(0,30),v:e.offsetWidth>0};
            }); })()""")
            log_fn("[{}] All inputs: {}".format(tag, all_in))
            return None

        info = json.loads(inp_info)
        log_fn("[{}] Input found: ph={}".format(tag, info.get('ph', '?')))

        # Fill key name
        await js(tab, """(() => {
          var inputs=document.querySelectorAll('input');
          for(var i=0;i<inputs.length;i++){
            var inp=inputs[i],ph=(inp.placeholder||'').toLowerCase();
            if(ph.includes('key name')){
              Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')
                .set.call(inp,'""" + key_name + """');
              inp.dispatchEvent(new Event('input',{bubbles:true}));
              inp.dispatchEvent(new Event('change',{bubbles:true}));
              return 'OK:'+inp.value;
            }
          }return 'NO_MATCH';
        })()""")

        await asyncio.sleep(0.3)

        # Click Generate / Create button
        gen_btn = await js(tab, """(() => {
          var tgt=['generate','create','add key','new key'];
          for(var e of document.querySelectorAll('button,[role=button],a,input[type=submit]')){
            var t=(e.innerText||e.value||'').trim().toLowerCase();
            if(tgt.some(function(x){return t===x||t.includes(x)})&&e.getBoundingClientRect().width>0){
              var r=e.getBoundingClientRect();
              return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),t:t});
            }
          }
          // fallback: first prominent button
          for(var b of document.querySelectorAll('button,[role=button]')){
            var rb=b.getBoundingClientRect();
            if(rb.width>60&&rb.height>25&&rb.width<250)
              return JSON.stringify({x:Math.round(rb.x+rb.width/2),y:Math.round(rb.y+rb.height/2),t:'fallback'});
          }return null;
        })()""")

        if gen_btn and gen_btn != 'null':
            gb = json.loads(gen_btn)
            log_fn("[{}] Gen btn '{}' @ ({},{})".format(tag, gb.get('t', '?'), gb['x'], gb['y']))
            await click_coords(tab, gb['x'], gb['y'], "generate")
        else:
            log_fn("[{}] No gen btn, trying Enter".format(tag))
            await tab.press_key('Enter')

        # Poll for API key appearance
        log_fn("[{}] Waiting for key...".format(tag))
        api_key = None
        for wt in range(18):
            await asyncio.sleep(1)
            key_val = await js(tab, JS_EXTRACT_KEY)
            if key_val and len(key_val) > 10:
                api_key = key_val
                log_fn("[{}] KEY FOUND after {}s: {}...".format(tag, wt+1, api_key[:25]))
                break

        if api_key:
            await screenshot(tab, "ws_success.png")
            return api_key
        else:
            bcontent = await body_text(tab, 800)
            log_fn("[{}] NO KEY after 18s. Page: {}...".format(tag, bcontent[:250]))
            await screenshot(tab, "ws_nokey.png")
            return None

    except Exception as ex:
        log_fn("[{}] Keygen error: {}".format(tag, ex))
        await screenshot(tab, "ws_generr.png")
        return None


# ════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════

async def main():
    args = parse_args()

    show_browser = args['show']
    max_count = args.get('count', 1)

    # Collect accounts
    accounts = []
    if args['email'] and args['password']:
        accounts.append({'email': args['email'], 'password': args['password']})
    elif args['accounts_file']:
        accounts = load_accounts(args['accounts_file'])

    if not accounts:
        print("No accounts specified.")
        print("Usage:")
        print("  python wavespeed_farm.py --email user@domain.com --pass PASSWORD --show")
        print("  python wavespeed_farm.py --accounts-file accounts.txt --count 10 --show")
        sys.exit(1)

    accounts = accounts[:max_count]
    total = len(accounts)

    print("=" * 55)
    print("WAVE SPEED FARM v31 (Nodriver)")
    print("Accounts: {} | Show browser: {}".format(total, show_browser))
    print("=" * 55)

    import nodriver as uc

    browser = await uc.start(headless=(not show_browser))

    results = {"ok": 0, "fail": 0, "errors": []}

    for idx, acct in enumerate(accounts):
        email = acct['email']
        password = acct['password']

        print("\n--- Account {}/{}: {} ---".format(idx + 1, total, email))

        result = await run_account(browser, email, password, print, idx + 1)

        if result.get('success'):
            results['ok'] += 1
        else:
            results['fail'] += 1
            err = result.get('error', 'unknown')
            results['errors'].append("{}: {}".format(email, err))
            print("  FAILED: {}".format(err))

    # Summary
    print("\n" + "=" * 55)
    print("SUMMARY: {} OK / {} FAIL".format(results['ok'], results['fail']))
    if results['errors']:
        print("Failures:")
        for err in results['errors']:
            print("  - {}".format(err))
    print("=" * 55)

    # Keep browser open briefly so user can see final state
    if show_browser:
        await asyncio.sleep(3)

    browser.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    except Exception as e:
        print("FATAL: {}: {}".format(type(e).__name__, e))
