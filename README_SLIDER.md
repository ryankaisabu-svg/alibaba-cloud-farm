# Dynamic Slider CAPTCHA Solver - AlibabaCloud Farm

## Overview

This implementation adds **dynamic slider CAPTCHA solving** to your AlibabaCloud farm project. The system automatically detects your OS and available libraries, then tries all available solving methods in order until the slider is solved.

## Features

- **Automatic OS Detection**: Works on both Windows and Linux
- **Multiple Solving Methods**: Tries all available methods in priority order
- **No Manual Configuration**: Automatically detects installed libraries
- **Fallback System**: If one method fails, tries the next available method
- **Comprehensive Logging**: Detailed logs for debugging

## Available Solving Methods

### 1. Playwright Mouse Actions (Built-in)
- **Platform**: All (Windows, Linux, macOS)
- **Dependencies**: None (built into Playwright)
- **Priority**: First (always tried first)
- **Works in headless**: Yes

### 2. PyAutoGUI
- **Platform**: Windows, Linux, macOS
- **Install**: `pip install pyautogui`
- **Priority**: Second (Windows), Third (Linux)
- **Works in headless**: No (requires visible desktop)
- **Recommended for Windows**: ✅ YES

### 3. pynput
- **Platform**: Windows, Linux, macOS
- **Install**: `pip install pynput`
- **Priority**: Third (Windows), Fourth (Linux)
- **Works in headless**: No (requires visible desktop)

### 4. uinput (Linux Only)
- **Platform**: Linux only
- **Install**: `pip install python-uinput`
- **Requires**: uinput kernel module (usually loaded by default)
- **Priority**: Second (Linux only)
- **Works in headless**: Yes

## Installation

### For Windows Users (RECOMMENDED)

```bash
cd E:\WEB\alibaba-cloud-farm
pip install pyautogui
```

This gives you the best results on Windows since PyAutoGUI works well with the Windows GUI system.

### For Linux Users

```bash
cd /path/to/alibaba-cloud-farm

# Option 1: Install all methods
pip install pyautogui pynput python-uinput

# Option 2: Install only uinput (most reliable for Linux)
pip install python-uinput

# Note: uinput requires the kernel module to be loaded
# Check if loaded: lsmod | grep uinput
# If not loaded: sudo modprobe uinput
```

### Quick Install (All Methods)

```bash
pip install -r requirements_slider.txt
```

## Usage

The dynamic solver is **automatically integrated** into both files:

### farm_headless.py
- Automatically used when slider is detected
- Tries all methods in order
- Falls back to manual if all automatic methods fail

### farm.py
- Same dynamic solver integration
- Replaces the old uinput-only approach

### How It Works

1. **Detection**: When a slider CAPTCHA is detected, the system logs:
   ```
   [SLIDER] ==================================================
   [SLIDER] DYNAMIC SLIDER SOLVER - AlibabaCloud
   [SLIDER] ==================================================
   [SLIDER] OS: Windows
   [SLIDER] Available methods: ['Playwright Mouse', 'PyAutoGUI', 'pynput']
   ```

2. **Attempt Sequence**: Tries each method in order:
   ```
   [SLIDER] Trying Playwright Mouse...
   [SLIDER] Playwright: Handle at (500,300), drag 300px
   [SLIDER] Playwright: ❌ Still visible
   [SLIDER] Trying PyAutoGUI...
   [SLIDER] PyAutoGUI: Dragging from (500,300) to (800,300)
   [SLIDER] PyAutoGUI: ✅ SOLVED!
   ```

3. **Result**: If any method succeeds, the script continues automatically.

## Method Priority Order

### On Windows:
1. Playwright Mouse (built-in)
2. PyAutoGUI (if installed)
3. pynput (if installed)

### On Linux:
1. Playwright Mouse (built-in)
2. uinput (if installed and available)
3. PyAutoGUI (if installed)
4. pynput (if installed)

## Troubleshooting

### "No slider handle found"
- The slider element selectors might have changed
- Check the HTML structure of the CAPTCHA
- Add new selectors to `find_slider_handle()` function

### "PyAutoGUI not available"
- Install PyAutoGUI: `pip install pyautogui`
- Make sure it's installed in the same Python environment

### "uinput not available or not on Linux"
- This is expected on Windows
- On Linux: `pip install python-uinput`
- Check kernel module: `lsmod | grep uinput`

### "All automatic methods failed"
- Try running with `--show` flag for visible browser
- Some CAPTCHAs require human interaction
- Check if the slider is a different type (not Baxia/NC)

### Playwright mouse not working in headless
- Playwright mouse actions work in headless mode
- If it's not working, try with `--show` flag
- Some systems may need additional configuration

## Customization

### Adding New Methods

To add a new solving method:

1. Create a new function:
```python
def solve_slider_my_method(page):
    """My custom slider solver."""
    # Your implementation here
    return True  # or False
```

2. Add it to the methods list in `solve_baxia_slider_dynamic()`:
```python
methods.append(("My Method", solve_slider_my_method))
```

### Changing Priority Order

Modify the order in the `methods` list in `solve_baxia_slider_dynamic()` function.
Methods are tried in the order they appear in the list.

### Adding New Selectors

If the slider HTML structure changes, add new selectors to `find_slider_handle()`:
```python
for sel in ['#nc_1_n1z', '.nc_iconfont.btn_slide', '.btn_slide',
             '#new_selector_1', '#new_selector_2']:
```

## Files Modified

1. **farm_headless.py**
   - Added dynamic solver functions
   - Modified `handle_captcha()` to use dynamic solver
   - Added OS and library detection

2. **farm.py**
   - Added dynamic solver functions
   - Modified `solve_slider()` to use dynamic solver
   - Added OS and library detection

3. **requirements_slider.txt** (NEW)
   - Lists all optional dependencies

4. **README_SLIDER.md** (NEW)
   - This documentation file

## Compatibility

- **Python**: 3.7+
- **Playwright**: 1.40.0+
- **OS**: Windows 10/11, Linux (most distributions)
- **Browser**: Chromium, Firefox, WebKit (via Playwright)

## Performance Notes

- **Fastest**: Playwright Mouse (built-in, no external dependencies)
- **Most Reliable (Windows)**: PyAutoGUI
- **Most Reliable (Linux)**: uinput
- **Fallback**: pynput (works but may be slower)

## Testing

To test the slider solver:

```bash
# Run with visible browser
python farm_headless.py --show

# Or run farm.py
python farm.py
```

When a slider appears, the system will automatically try all methods and log the results.

## Contributing

If you find a new CAPTCHA type or have improvements:

1. Add the new solving method
2. Update the selectors in `find_slider_handle()`
3. Test on your system
4. Submit a pull request

## License

This code is part of the AlibabaCloud Farm project and follows the same license.

---

**Note**: CAPTCHA solving may violate some websites' terms of service. Use responsibly and only for legitimate purposes.