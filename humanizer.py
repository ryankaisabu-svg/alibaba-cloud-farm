"""
Humanizer Module for Browser Automation
Makes nodriver/Playwright look like a real human user.

Usage:
    from humanizer import Humanizer
    
    h = Humanizer(tab)
    await h.move_to(500, 300)           # Natural mouse movement
    await h.click(500, 300)             # Click with human delay
    await h.type_text("hello@ex.com")   # Type like a real person
    await h.scroll_down()               # Natural scroll
    await h.random_delay()              # Random wait
"""

import asyncio
import random
import math
import json


class Humanizer:
    """Makes browser automation behave like a real human user."""
    
    def __init__(self, tab):
        self.tab = tab
        # Track current mouse position (default center of screen)
        self._mouse_x = 960
        self._mouse_y = 540
        
        # Typing speed config (ms per character)
        self.TYPING_SPEED_MIN = 50      # Fast typist
        self.TYPING_SPEED_MAX = 180     # Slower, thoughtful typing
        self.TYPING_ERROR_CHANCE = 0.02  # 2% chance of typo (will be corrected)
        
        # Mouse speed config
        self.MOUSE_MIN_DURATION = 150   # ms for short distance
        self.MOUSE_MAX_DURATION = 800   # ms for long cross-screen moves
        
        # Action delays
        self.DELAY_AFTER_CLICK = (200, 600)
        self.DELAY_AFTER_TYPE = (300, 800)
        self.DELAY_BETWEEN_ACTIONS = (400, 1200)
    
    async def setup_anti_detection(self):
        """Remove common automation fingerprints from the page."""
        scripts = [
            # Remove webdriver flag
            """Object.defineProperty(navigator, 'webdriver', {get: () => false})""",
            
            # Fix plugins (real browsers have some plugins)
            """Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5].map(() => ({
                    name: 'Chrome PDF Plugin',
                    filename: 'internal-pdf-viewer',
                    description: 'Portable Document Format',
                    length: 1
                }))
            })""",
            
            # Fix languages
            """Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en', 'id']
            })""",
            
            # Fix chrome runtime
            """window.chrome = { runtime: {}, loadTimes: function(){}, csi: function(){} }""",
            
            # Fix permissions
            """const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
            )""",
        ]
        
        for script in scripts:
            try:
                await self.tab.evaluate(script)
            except Exception:
                pass
        
        return True
    
    async def accept_cookies(self):
        """Auto-accept cookie banners if present."""
        result = await self.tab.evaluate("""(() => {
            var buttons = document.querySelectorAll('button, [role=button], a');
            var clicked = null;
            buttons.forEach(function(b) {
                var t = (b.innerText || '').trim().toLowerCase();
                if ((t === 'accept' || t === 'agree' || t === 'ok' || t === 'i agree') &&
                    b.getBoundingClientRect().width > 10 && b.getBoundingClientRect().height > 10) {
                    if (!clicked) {
                        b.click();
                        clicked = t;
                    }
                }
            });
            return clicked || 'NONE';
        })()""")
        
        if result and result != 'NONE':
            print(f"  🍪 Cookie accepted ({result})")
            await asyncio.sleep(random.uniform(0.3, 0.8))
            return True
        return False
    
    async def move_to(self, target_x, target_y):
        """
        Move mouse naturally to target position using bezier curve.
        Simulates human hand tremor and acceleration/deceleration.
        """
        start_x, start_y = self._mouse_x, self._mouse_y
        dx = target_x - start_x
        dy = target_y - start_y
        distance = math.sqrt(dx * dx + dy * dy)
        
        # Calculate duration based on distance (longer distance = longer time)
        duration = min(self.MOUSE_MAX_DURATION,
                       max(self.MOUSE_MIN_DURATION, int(distance / 2)))
        
        # Add randomness (+/- 20%)
        duration = int(duration * random.uniform(0.8, 1.2))
        
        steps = max(10, int(distance / 15))  # More steps for smoother curve
        
        # Bezier control points (slight curve to simulate natural movement)
        cp_offset_x = random.uniform(-30, 30)
        cp_offset_y = random.uniform(-30, 30)
        
        # Control point for quadratic bezier (perpendicular offset from midpoint)
        mid_x = (start_x + target_x) / 2 + cp_offset_x
        mid_y = (start_y + target_y) / 2 + cp_offset_y
        
        step_delay = duration / 1000.0 / steps  # Convert to seconds
        
        for i in range(steps + 1):
            t = i / steps
            
            # Quadratic bezier formula
            cur_x = (1-t)**2 * start_x + 2*(1-t)*t * mid_x + t**2 * target_x
            cur_y = (1-t)**2 * start_y + 2*(1-t)*t * mid_y + t**2 * target_y
            
            # Add micro-jitter (simulates hand tremor, ~2 pixels)
            jitter_x = random.gauss(0, 1.5)
            jitter_y = random.gauss(0, 1.5)
            
            actual_x = round(cur_x + jitter_x)
            actual_y = round(cur_y + jitter_y)
            
            await self.tab.mouse_move(actual_x, actual_y)
            await asyncio.sleep(step_delay)
        
        # Update tracked position
        self._mouse_x, self._mouse_y = target_x, target_y
    
    async def click(self, x, y, button='left'):
        """
        Click at position with natural timing.
        Includes pre-click pause and post-click delay.
        """
        # Move there first (if not already close)
        dist = math.sqrt((x - self._mouse_x)**2 + (y - self._mouse_y)**2)
        if dist > 20:
            await self.move_to(x, y)
        
        # Small pause before click (human thinking time)
        await asyncio.sleep(random.uniform(0.05, 0.2))
        
        # Click with slight random delay between down and up
        await self.tab.mouse_click(x, y)
        
        # Post-action pause
        await asyncio.sleep(random.uniform(*self.DELAY_AFTER_CLICK))
    
    async def type_text(self, text, selector=None, clear_first=True):
        """
        Type text like a real human:
        - Variable speed per character
        - Occasional pauses (thinking)
        - Rare typo simulation (with correction)
        """
        if selector:
            # Focus element first via JS
            focus_result = await self.tab.evaluate(f"""(() => {{
                var el = document.querySelector('{selector}');
                if (!el) return 'NOT_FOUND';
                
                // Scroll into view
                el.scrollIntoView({{behavior:'smooth', block:'center'}});
                el.focus();
                
                if ({clear_first}) {{
                    // Clear existing value
                    var nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(el, '');
                }}
                
                return 'FOCUSED';
            }})()""")
            
            if focus_result != 'FOCUSED':
                print(f"  ⚠️ Could not find element '{selector}'")
                return False
            
            # Click the element first to ensure focus
            pos = await self.tab.evaluate(f"""(() => {{
                var el = document.querySelector('{selector}');
                if(!el) return null;
                var r = el.getBoundingClientRect();
                return JSON.stringify({{x: Math.round(r.x+r.width/2), y: Math.round(r.y+r.height/2)}});
            }})()""")
            
            if pos and pos != 'null':
                p = json.loads(pos)
                await self.click(p['x'], p['y'])
        
        await asyncio.sleep(random.uniform(0.1, 0.3))
        
        # Now type character by character with variable speed
        i = 0
        while i < len(text):
            char = text[i]
            
            # Random "thinking pause" (happens every 5-12 characters)
            should_pause = random.random() < 0.08  # 8% chance per char
            chars_typed = len(text[:i+1])
            if should_pause and chars_typed > 3 and chars_typed % random.randint(5, 12) == 0:
                pause_time = random.uniform(0.2, 0.6)
                await asyncio.sleep(pause_time)
            
            # Rare typo simulation (type wrong char then delete it)
            if (random.random() < self.TYPING_ERROR_CHANCE 
                and i > 0 
                and char.isalpha()
                and not char.isspace()):
                
                # Type wrong character (adjacent key)
                wrong_char = chr(ord(char) + random.choice([-1, 1]))
                try:
                    await self.tab.evaluate(f"document.activeElement.value += '{wrong_char}'")
                    await self.tab.evaluate("document.activeElement.dispatchEvent(new Event('input', {bubbles:true}))")
                    
                    # Short pause (notice mistake)
                    await asyncio.sleep(random.uniform(0.15, 0.35))
                    
                    # Delete it (backspace)
                    await self.tab.evaluate("""
                        var el = document.activeElement;
                        if(el.value.length>0){
                            el.value = el.value.slice(0,-1);
                            el.dispatchEvent(new Event('input',{bubbles:true}));
                            el.dispatchEvent(new Event('change',{bubbles:true}));
                        }
                    """)
                    
                    # Pause after correction
                    await asyncio.sleep(random.uniform(0.1, 0.25))
                except Exception:
                    pass
            
            # Type correct character via native setter (triggers React/Angular)
            type_js = f"""(() => {{
                var el = document.activeElement;
                if(!el) return;
                var s=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
                s.call(el, (el.value||'') + '{char}');
                el.dispatchEvent(new Event('input',{{bubbles:true}}));
                el.dispatchEvent(new Event('change',{{bubbles:true}}));
            }})()"""
            
            try:
                await self.tab.evaluate(type_js)
            except Exception:
                pass
            
            # Variable delay per character
            char_delay = random.uniform(self.TYPING_SPEED_MIN, self.TYPING_SPEED_MAX) / 1000.0
            await asyncio.sleep(char_delay)
            
            i += 1
        
        # Post-typing pause
        await asyncio.sleep(random.uniform(*self.DELAY_AFTER_TYPE))
        return True
    
    async def scroll_down(self, amount=300, smooth=True):
        """Scroll down naturally."""
        scroll_js = f"""(() => {{
            var amt = {amount};
            if ({smooth}) {{
                window.scrollBy({{top:amt, behavior:'smooth'}});
            }} else {{
                window.scrollBy(0, amt);
            }}
            return window.scrollY;
        }})()"""
        
        result = await self.tab.evaluate(scroll_js)
        await asyncio.sleep(random.uniform(0.3, 0.7))
        return result
    
    async def random_delay(self, min_ms=400, max_ms=1200):
        """Wait a random amount of time (simulates human thinking)."""
        delay = random.uniform(min_ms, max_ms) / 1000.0
        await asyncio.sleep(delay)
    
    async def wait_for_element(self, selector, timeout=30):
        """Wait for an element to appear in the DOM (polling-based)."""
        start = asyncio.get_event_loop().time()
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start
            if elapsed > timeout:
                return None
            
            result = await self.tab.evaluate(f"((document.querySelector('{selector}')||{{}}).tagName)||''")
            
            if result == str(result):  # valid string returned
                return result
            
            await asyncio.sleep(0.5)


# Convenience function for quick usage
async def create_humanized_tab(browser, url=None):
    """
    Create a new tab with full anti-detection + humanization.
    
    Usage:
        tab, h = await create_humanized_tab(browser, "https://example.com")
        await h.move_to(500, 300)
        await h.click(500, 300)
    """
    tab = await browser.get(url or "about:blank")
    
    if url:
        # Wait for page to load
        await asyncio.sleep(3)
    
    h = Humanizer(tab)
    
    # Setup anti-detection
    await h.setup_anti_detection()
    
    # Accept cookies if present
    await h.accept_cookies()
    
    return tab, h


if __name__ == "__main__":
    # Quick test
    import sys
    print("Humanizer module loaded OK")
    print(f"Classes: Humanizer")
