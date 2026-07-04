"""
core/captcha_solver.py — CAPTCHA detection and solver for Alibaba Cloud Farm.

Extracted from farm_headless.py L848-1523.
Provides: find_slider_handle, solve_slider_playwright, solve_slider_pyautogui,
          solve_slider_pynput, solve_slider_uinput, solve_baxia_slider_dynamic,
          handle_captcha, _captcha_solved.

CAPTCHA auto-solve is DISABLED — all paths use manual solve (120s timeout).
"""

import time
import platform

# ─ Optional dependencies (same pattern as farm_headless.py) ──
try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False

try:
    from pynput.mouse import Button, Controller
    PYNPUT_AVAILABLE = True
except ImportError:
    PYNPUT_AVAILABLE = False

try:
    import uinput
    UINPUT_AVAILABLE = True
except ImportError:
    UINPUT_AVAILABLE = False

# ─ Config (will be set externally or use defaults) ──
AUTO_CAPTCHA = False  # Auto-solve DISABLED


def log(step, msg):
    """Minimal log — avoids circular import with core/helpers.py."""
    ts = time.strftime("%H:%M:%S")
    try:
        print(f"  [{ts}] [{step}] {msg}", flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("ascii", "replace").decode("ascii")
        print(f"  [{ts}] [{step}] {safe}", flush=True)


def screenshot(page, filename):
    """Take screenshot — tries page.screenshot(), falls back gracefully."""
    try:
        page.screenshot(path=filename)
        log("SHOT", f"Saved {filename}")
    except:
        pass


def human_pause_short():
    """Short human-like pause (0.3-0.8s)."""
    import random as _r
    time.sleep(_r.uniform(0.3, 0.8))


# ════════════════════════════════════════════════════
# ─ Slider handle finder ────────────────────────────
# ════════════════════════════════════════════════════

def find_slider_handle(page, frame=None):
    """Search all frames for slider handle (Baxia/NC/risk_slider).
    Returns: (element, frame, selector) or (None, None, None)
    """
    # Selectors for AlibabaCloud risk_slider (newer Baxia)
    risk_selectors = [
        '#nc_1_n1z', '.nc_iconfont.btn_slide', '.btn_slide',
        'span.nc_iconfont', '#nc_1_n1z_em', '.nc-iconfont',
        '#nc_1__scale_text', '#risk_slider_container .nc_iconfont',
        '#risk_slider_container .btn_slide',
        '#risk_slider_container [role="slider"]',
        '#risk_slider_container .slider-btn',
        '#risk_slider_container .sliderBtn',
        '#baxia-dialog .nc_iconfont',
        '#baxia-dialog .btn_slide',
        '.baxia-captcha .nc_iconfont',
        '.baxia-captcha .btn_slide',
        # Generic slider selectors
        '[data-role="sliderHandle"]',
        '.slider-handle',
        '.slide-verify-slider',
        '#aliyunCaptcha-btn',
        '.nc-container .nc_iconfont',
    ]

    # Search in the provided frame first
    frames_to_search = []
    if frame:
        frames_to_search.append(frame)
    frames_to_search.extend(page.frames)

    for f in frames_to_search:
        for sel in risk_selectors:
            try:
                el = f.query_selector(sel)
                if el:
                    box = el.bounding_box()
                    if box and box['width'] > 0 and box['height'] > 0:
                        return el, f, sel
            except:
                pass
    return None, None, None


# ════════════════════════════════════════════════════
# ─ Solver 1: Playwright Mouse ──────────────────────
# ════════════════════════════════════════════════════

def solve_slider_playwright(page, frame=None):
    """Solve slider using Playwright's built-in mouse actions."""
    log("SLIDER", "Attempting Playwright mouse solver...")

    # Wait for slider widget to finish loading (up to 10s)
    log("SLIDER", "Waiting for slider widget to render...")
    for wait_i in range(10):
        el, target_frame, sel = find_slider_handle(page, frame)
        if el:
            break
        time.sleep(1)
        if wait_i == 4:
            log("SLIDER", "Still waiting for slider handle...")

    if not el:
        # Log all visible elements in #risk_slider_container for debugging
        if frame:
            try:
                container = frame.query_selector("#risk_slider_container")
                if container:
                    inner = container.inner_html()
                    log("SLIDER", f"risk_slider_container innerHTML (first 500 chars): {inner[:500]}")
            except:
                pass
        log("SLIDER", "Playwright: No slider handle found after 10s wait")
        return False

    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "Playwright: No bounding box")
            return False

        # Calculate drag distance - try to find track
        track = None
        if target_frame:
            for track_sel in ['#nc_1__scale_text', '.nc_scale', '#nc_1_n1t', '.nc-track']:
                try:
                    track = target_frame.query_selector(track_sel)
                    if track:
                        track_box = track.bounding_box()
                        if track_box:
                            drag_dist = track_box['width'] - box['width']
                            break
                except:
                    pass

        if track is None:
            drag_dist = 300  # Default drag distance

        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        end_x = start_x + drag_dist

        log("SLIDER", f"Playwright: Handle at ({start_x:.0f},{start_y:.0f}), drag {drag_dist:.0f}px")

        # Move to slider handle
        page.mouse.move(start_x, start_y)
        page.mouse.down()

        # Drag with steps for human-like movement
        steps = 20
        for i in range(1, steps + 1):
            current_x = start_x + (drag_dist * i / steps)
            page.mouse.move(current_x, start_y)
            time.sleep(0.05)

        page.mouse.up()
        time.sleep(2)

        # Check if solved
        el2, _, _ = find_slider_handle(page, target_frame)
        if not el2:
            log("SLIDER", "Playwright: Slider solved!")
            return True
        else:
            log("SLIDER", "Playwright: Slider still visible")
            return False

    except Exception as e:
        log("SLIDER", f"Playwright: Error - {e}")
        return False


# ════════════════════════════════════════════════════
# ─ Solver 2: PyAutoGUI ─────────────────────────────
# ════════════════════════════════════════════════════

def solve_slider_pyautogui(page, frame=None):
    """Solve slider using PyAutoGUI."""
    if not PYAUTOGUI_AVAILABLE:
        log("SLIDER", "PyAutoGUI not available")
        return False

    log("SLIDER", "Attempting PyAutoGUI solver...")

    import pyautogui

    el, found_frame, sel = find_slider_handle(page, frame)
    if not el:
        log("SLIDER", "PyAutoGUI: No slider handle found")
        return False

    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "PyAutoGUI: No bounding box")
            return False

        # Calculate drag distance
        track = None
        if found_frame:
            for track_sel in ['#nc_1__scale_text', '.nc_scale', '#nc_1_n1t',
                              '#risk_slider_container .nc_scale',
                              '#risk_slider_container .scale_text',
                              '.nc_scale', '.scale_text']:
                try:
                    track = found_frame.query_selector(track_sel)
                    if track:
                        track_box = track.bounding_box()
                        if track_box:
                            drag_dist = track_box['width'] - box['width']
                            break
                except:
                    pass

        if track is None:
            drag_dist = 300

        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2
        end_x = start_x + drag_dist

        log("SLIDER", f"PyAutoGUI: Dragging from ({start_x:.0f},{start_y:.0f}) to ({end_x:.0f},{start_y:.0f})")

        # Move and drag
        pyautogui.moveTo(start_x, start_y, duration=0.5)
        pyautogui.mouseDown()
        pyautogui.moveTo(end_x, start_y, duration=1.0)
        pyautogui.mouseUp()
        time.sleep(2)

        # Check if solved
        el2, _, _ = find_slider_handle(page, found_frame)
        if not el2:
            log("SLIDER", "PyAutoGUI: Slider solved!")
            return True
        else:
            log("SLIDER", "PyAutoGUI: Slider still visible")
            return False

    except Exception as e:
        log("SLIDER", f"PyAutoGUI: Error - {e}")
        return False


# ════════════════════════════════════════════════════
# ─ Solver 3: pynput ────────────────────────────────
# ════════════════════════════════════════════════════

def solve_slider_pynput(page, frame=None):
    """Solve slider using pynput."""
    if not PYNPUT_AVAILABLE:
        log("SLIDER", "pynput not available")
        return False

    log("SLIDER", "Attempting pynput solver...")

    from pynput.mouse import Controller, Button

    mouse = Controller()

    el, found_frame, sel = find_slider_handle(page, frame)
    if not el:
        log("SLIDER", "pynput: No slider handle found")
        return False

    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "pynput: No bounding box")
            return False

        # Calculate drag distance
        drag_dist = 300  # Default
        if found_frame:
            for track_sel in ['#nc_1__scale_text', '.nc_scale',
                              '#risk_slider_container .nc_scale',
                              '#risk_slider_container .scale_text']:
                try:
                    track = found_frame.query_selector(track_sel)
                    if track:
                        track_box = track.bounding_box()
                        if track_box:
                            drag_dist = track_box['width'] - box['width']
                            break
                except:
                    pass

        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2

        log("SLIDER", f"pynput: Dragging from ({start_x:.0f},{start_y:.0f}) for {drag_dist:.0f}px")

        # Move and drag
        mouse.position = (start_x, start_y)
        mouse.press(Button.left)
        mouse.move(drag_dist, 0)  # Move right
        mouse.release(Button.left)
        time.sleep(2)

        # Check if solved
        el2, _, _ = find_slider_handle(page, found_frame)
        if not el2:
            log("SLIDER", "pynput: Slider solved!")
            return True
        else:
            log("SLIDER", "pynput: Slider still visible")
            return False

    except Exception as e:
        log("SLIDER", f"pynput: Error - {e}")
        return False


# ════════════════════════════════════════════════════
# ─ Solver 4: uinput (Linux only) ───────────────────
# ════════════════════════════════════════════════════

def solve_slider_uinput(page, frame=None):
    """Solve slider using uinput (Linux only)."""
    if not UINPUT_AVAILABLE or platform.system() != 'Linux':
        log("SLIDER", "uinput not available or not on Linux")
        return False

    log("SLIDER", "Attempting uinput solver...")

    import uinput

    el, found_frame, sel = find_slider_handle(page, frame)
    if not el:
        log("SLIDER", "uinput: No slider handle found")
        return False

    try:
        box = el.bounding_box()
        if not box:
            log("SLIDER", "uinput: No bounding box")
            return False

        # Create virtual mouse
        with uinput.Device([
            uinput.ABS_X + (0, 65535),
            uinput.ABS_Y + (0, 65535),
            uinput.BTN_LEFT,
            uinput.REL_X,
            uinput.REL_Y
        ]) as device:
            start_x = int(box['x'] + box['width'] / 2)
            start_y = int(box['y'] + box['height'] / 2)
            drag_dist = 300

            # Move to position (absolute)
            device.emit_click(uinput.ABS_X, start_x)
            device.emit_click(uinput.ABS_Y, start_y)

            # Press mouse button
            device.emit_click(uinput.BTN_LEFT)
            time.sleep(0.1)

            # Drag
            steps = 20
            for i in range(1, steps + 1):
                move_dist = int(drag_dist * i / steps)
                device.emit(uinput.REL_X, move_dist)
                time.sleep(0.05)

            # Release
            device.emit_click(uinput.BTN_LEFT)
            time.sleep(2)

        # Check if solved
        el2, _, _ = find_slider_handle(page, found_frame)
        if not el2:
            log("SLIDER", "uinput: Slider solved!")
            return True
        else:
            log("SLIDER", "uinput: Slider still visible")
            return False

    except Exception as e:
        log("SLIDER", f"uinput: Error - {e}")
        return False


# ════════════════════════════════════════════════════
# ─ Dynamic solver (tries all methods) ───────────────
# ════════════════════════════════════════════════════

def solve_baxia_slider_dynamic(page, frame=None, headless=False):
    """
    Dynamic slider solver - tries all available methods in order.
    Returns: True if solved, False if failed, "SLIDER" if needs manual
    """
    log("SLIDER", "=" * 50)
    log("SLIDER", "DYNAMIC SLIDER SOLVER - AlibabaCloud")
    log("SLIDER", "=" * 50)

    # Define solving methods in priority order
    methods = []

    # Always try Playwright first (built-in, no dependencies)
    methods.append(("Playwright Mouse", solve_slider_playwright))

    # Add OS-specific methods
    if platform.system() == 'Windows':
        if PYAUTOGUI_AVAILABLE:
            methods.append(("PyAutoGUI", solve_slider_pyautogui))
        if PYNPUT_AVAILABLE:
            methods.append(("pynput", solve_slider_pynput))
    elif platform.system() == 'Linux':
        if UINPUT_AVAILABLE:
            methods.append(("uinput", solve_slider_uinput))
        if PYAUTOGUI_AVAILABLE:
            methods.append(("PyAutoGUI", solve_slider_pyautogui))
        if PYNPUT_AVAILABLE:
            methods.append(("pynput", solve_slider_pynput))

    log("SLIDER", f"OS: {platform.system()}")
    log("SLIDER", f"Available methods: {[name for name, _ in methods]}")

    # Try each method
    for method_name, solver_func in methods:
        log("SLIDER", f"Trying {method_name}...")
        try:
            if solver_func(page, frame):
                log("SLIDER", f"SUCCESS with {method_name}!")
                return True
        except Exception as e:
            log("SLIDER", f"{method_name} failed: {e}")

        time.sleep(1)  # Brief pause between attempts

    # If headless and no methods worked
    if headless:
        log("SLIDER", "No automatic solver available in headless mode")
        return "SLIDER"

    # Manual fallback
    log("SLIDER", "All automatic methods failed - manual solve required")
    return False


# ════════════════════════════════════════════════════
# ─ Main CAPTCHA handler ────────────────────────────
# ════════════════════════════════════════════════════

def handle_captcha(page, frame, headless=True, timeout=120):
    """Handle various CAPTCHA types: slider, press-and-hold, nested iframe.
    Returns: True if solved/passed, False if blocked, "SLIDER" if can't solve."""
    start = time.time()
    while time.time() - start < timeout:
        # Check 1: Slider CAPTCHA (#risk_slider_container)
        if frame:
            slider = frame.query_selector("#risk_slider_container")
            if slider:
                try:
                    if slider.is_visible():
                        box = slider.bounding_box()
                        if box and box['width'] > 50 and box['height'] > 20:
                            log("CAPTCHA", f"Slider detected ({box['width']:.0f}x{box['height']:.0f})")
                            screenshot(page, "captcha_slider.png")

                            # Auto-slider DISABLED — always go to manual path for bug testing
                            # if AUTO_CAPTCHA and solve_baxia_slider_dynamic(page, frame, headless):
                            #     log("CAPTCHA", "Slider solved automatically!")
                            #     return True

                            if headless:
                                return "SLIDER"
                            else:
                                log("CAPTCHA", ">>> SLIDER CAPTCHA DETECTED! <<<")
                                log("CAPTCHA", "Auto-slider DISABLED — manual solve only")

                                # CRITICAL: Release any mouse locks from all input methods
                                # Playwright virtual mouse
                                try:
                                    page.mouse.up()
                                except:
                                    pass
                                # PyAutoGUI physical mouse
                                try:
                                    import pyautogui
                                    pyautogui.mouseUp()
                                    pyautogui.FAILSAFE = False
                                except:
                                    pass
                                # pynput physical mouse
                                try:
                                    from pynput.mouse import Button, Controller
                                    Controller().release(Button.left)
                                except:
                                    pass

                                # Bring browser window to front so user can interact
                                try:
                                    page.bring_to_front()
                                except:
                                    pass
                                human_pause_short()  # Give browser time to gain focus

                                # Wait for manual solve (up to 120s, ignoring outer timeout)
                                log("CAPTCHA", "Waiting up to 120s for manual solve...")
                                log("CAPTCHA", ">>> YOU CAN NOW DRAG THE SLIDER MANUALLY <<<")
                                for w in range(60):
                                    time.sleep(2)
                                    if _captcha_solved(page, frame):
                                        log("CAPTCHA", "Slider solved!")
                                        return True
                                    if w % 5 == 0 and w > 0:
                                        log("CAPTCHA", f"Waiting... ({w*2}s)")
                                log("CAPTCHA", "Manual solve timed out (120s)")
                                return "SLIDER"
                except:
                    pass

        # Check 2: Press-and-Hold CAPTCHA (hsprotect iframe)
        for f in page.frames:
            furl = (f.url or "").lower()
            if "hsprotect" in furl or "fpt.live" in furl:
                try:
                    hold_btn = f.query_selector(
                        "button:has-text('Press'), [role='button']:has-text('Press'), "
                        "button:has-text('hold'), [role='button']:has-text('hold')"
                    )
                    if hold_btn:
                        box = hold_btn.bounding_box()
                        if box and box['width'] > 0:
                            log("CAPTCHA", f"Press-and-Hold button found ({box['width']:.0f}x{box['height']:.0f})")
                            screenshot(page, "captcha_hold.png")
                            if headless:
                                return "HOLD"
                            else:
                                log("CAPTCHA", ">>> PRESS AND HOLD BUTTON IN BROWSER! <<<")
                                # Auto-solve is DISABLED
                                log("CAPTCHA", "Press-and-hold auto-solve is DISABLED — manual solve required")
                except:
                    pass

        # Check 3: Main page press-and-hold (not in iframe)
        try:
            hold_btn = page.query_selector(
                "button:has-text('Press'), [role='button']:has-text('Press'), "
                "button:has-text('hold'), [role='button']:has-text('hold')"
            )
            if hold_btn:
                box = hold_btn.bounding_box()
                if box and box['width'] > 0:
                    log("CAPTCHA", "Press-and-Hold on main page")
                    if headless:
                        return "HOLD"
                    # Auto-solve DISABLED — manual only
                    # elif AUTO_CAPTCHA:
                    #     page.mouse.move(box["x"] + box["width"]/2, box["y"] + box["height"]/2)
                    #     page.mouse.down()
                    #     time.sleep(5)
                    #     page.mouse.up()
                    #     time.sleep(3)
                    #     if _captcha_solved(page, frame):
                    #         return True

                    # Manual solve path for Press-and-Hold
                    log("CAPTCHA", ">>> PRESS-AND-HOLD CAPTCHA DETECTED! <<<")
                    log("CAPTCHA", "Auto-solve DISABLED — manual solve only")

                    # Release any mouse locks
                    try:
                        page.mouse.up()
                    except:
                        pass
                    try:
                        import pyautogui
                        pyautogui.mouseUp()
                        pyautogui.FAILSAFE = False
                    except:
                        pass

                    try:
                        page.bring_to_front()
                    except:
                        pass
                    human_pause_short()

                    log("CAPTCHA", ">>> HOLD THE BUTTON MANUALLY FOR 5 SECONDS <<<")
                    log("CAPTCHA", "Waiting up to 120s for manual solve...")
                    for w in range(60):
                        time.sleep(2)
                        if _captcha_solved(page, frame):
                            log("CAPTCHA", "Hold CAPTCHA solved!")
                            return True
                        if w % 5 == 0 and w > 0:
                            log("CAPTCHA", f"Waiting... ({w*2}s)")
                    log("CAPTCHA", "Manual solve timed out (120s)")
                    return "HOLD"
        except:
            pass

        # Check 4: Nested iframe baxia-dialog (login/OTP CAPTCHA — slider puzzle)
        # Baxia can appear in the passport iframe OR in a nested iframe inside it
        baxia_frames = []
        if frame:
            baxia_frames.append(frame)
        # Also check nested iframes inside passport frame
        if frame:
            try:
                nested_iframes = frame.query_selector_all("iframe")
                for ni in nested_iframes:
                    try:
                        ni_frame = ni.content_frame()
                        if ni_frame:
                            baxia_frames.append(ni_frame)
                    except:
                        pass
            except:
                pass

        for bf in baxia_frames:
            try:
                baxia = bf.query_selector("#baxia-dialog-content, .baxia-dialog, .nc_iconfont, #nc_1_wrapper, .nc_wrapper")
                if baxia:
                    try:
                        is_vis = baxia.is_visible()
                    except:
                        is_vis = True
                    if is_vis:
                        log("CAPTCHA", "Baxia dialog detected")
                        screenshot(page, "captcha_baxia.png")

                        # Auto-slider DISABLED — always go to manual path for bug testing
                        # if AUTO_CAPTCHA and solve_baxia_slider_dynamic(page, bf, headless):
                        #     log("CAPTCHA", "Baxia slider solved automatically!")
                        #     return True

                        if headless:
                            return "BAXIA"
                        else:
                            log("CAPTCHA", ">>> SOLVE BAXIA SLIDER IN BROWSER! <<<")
                            log("CAPTCHA", "Auto-slider DISABLED — manual solve only")

                            # Release any mouse locks from all input methods
                            try:
                                page.mouse.up()
                            except:
                                pass
                            try:
                                import pyautogui
                                pyautogui.mouseUp()
                                pyautogui.FAILSAFE = False
                            except:
                                pass
                            try:
                                from pynput.mouse import Button, Controller
                                Controller().release(Button.left)
                            except:
                                pass

                            # Bring browser to front for manual interaction
                            try:
                                page.bring_to_front()
                            except:
                                pass
                            human_pause_short()

                            log("CAPTCHA", "Waiting up to 120s for manual solve...")
                            log("CAPTCHA", ">>> YOU CAN NOW DRAG THE SLIDER MANUALLY <<<")
                            for w in range(60):
                                time.sleep(2)
                                # Check if page advanced (tabs disappeared, URL changed)
                                try:
                                    tabs = bf.query_selector_all("li[role='tab']")
                                    if len(tabs) == 0:
                                        # Tabs gone — might have advanced
                                        url = page.url.lower()
                                        if "register" not in url or "login" in url or "success" in url:
                                            log("CAPTCHA", "Page advanced after Baxia solve!")
                                            return True
                                except:
                                    pass
                                # Check if baxia disappeared
                                try:
                                    still = bf.query_selector("#baxia-dialog-content, .baxia-dialog")
                                    if not still or not still.is_visible():
                                        time.sleep(2)
                                        url = page.url.lower()
                                        if "login" in url or "success" in url or "console" in url:
                                            log("CAPTCHA", "Baxia solved — redirected!")
                                            return True
                                except:
                                    pass
                                if w % 5 == 0 and w > 0:
                                    log("CAPTCHA", f"Waiting for Baxia solve... ({w*2}s)")
                            log("CAPTCHA", "Baxia solve timeout")
                            return "BAXIA"
            except:
                pass

        time.sleep(2)

    return True  # No CAPTCHA found — proceed


# ════════════════════════════════════════════════════
# ─ CAPTCHA solved checker ──────────────────────────
# ════════════════════════════════════════════════════

def _captcha_solved(page, frame):
    """Check if CAPTCHA was solved (page advanced or CAPTCHA disappeared)."""
    # Collect all frames to check: main page + passport frame + nested iframes
    frames_to_check = [page]
    if frame:
        frames_to_check.append(frame)
        # Check nested iframes inside passport frame
        try:
            for ni in frame.query_selector_all("iframe"):
                try:
                    child = ni.content_frame()
                    if child:
                        frames_to_check.append(child)
                except:
                    pass
        except:
            pass
    # Also check all page frames (covers baxia-dialog iframe)
    frames_to_check.extend(page.frames)

    for f in frames_to_check:
        try:
            # Check if tabs appeared (page advanced)
            tabs = f.query_selector_all("li[role='tab']")
            if len(tabs) > 0:
                return True
            # Check if slider disappeared
            slider = f.query_selector("#risk_slider_container")
            if slider:
                try:
                    if not slider.is_visible():
                        time.sleep(1)
                        tabs = f.query_selector_all("li[role='tab']")
                        if len(tabs) > 0:
                            return True
                        # Slider hidden = likely solved
                        return True
                except:
                    pass
        except:
            pass
    # Check URL change
    url = page.url.lower()
    if "login" in url or "console" in url or "dashboard" in url:
        return True
    return False
