# Qwen Cloud Farm - Modern Interactive GUI

GUI modern dan interaktif untuk Qwen Cloud account farming menggunakan **CustomTkinter**.

## 🚀 Fitur Utama

### 1. **Dashboard Interaktif**
- Real-time statistics cards (Total, Complete, Failed, With API Key)
- Progress bar dengan percentage
- Control buttons (Start, Pause, Stop)
- Quick settings di dashboard

### 2. **Configuration Panel**
- Gmail credentials input (auto-load dari .env)
- Farming options (Count, Concurrency, Proxy)
- Advanced options (Show Browser, Debug Mode)
- Save configuration ke .env file

### 3. **Live Logs Viewer**
- Syntax highlighting untuk log levels:
  - 🟢 **Success**: API key extracted, registered
  - 🔴 **Error**: Failed, exception, timeout
  - 🟡 **Warning**: Skip, retry
  - 🔵 **Stats**: Progress, created, done
  - ⚪ **Info**: [REG], [MAIL], [KEY], [QWEN]
- Auto-scroll ke log terbaru
- Clear logs button

### 4. **Results Table**
- Sortable columns (click header)
- Search/filter by email, API key, status
- Double-click to copy API key
- Export to CSV/JSON
- Status indicators (✓ Complete, ✗ Failed, ⏳ Pending)
- Refresh button

### 5. **Multi-Threading Support**
- Thread-safe UI updates
- Pause/Resume functionality
- Graceful stop
- Real-time progress tracking

## 📦 Instalasi

### Dependencies
```bash
pip install customtkinter packaging python-dotenv
```

### Quick Start
```bash
# Windows: Double-click
run_qwen_gui.bat

# Atau via command line
"C:\Users\Dhipa\AppData\Local\Programs\Python\Python313\python.exe" qwen_farm_gui.py
```

## 🎨 Theme

- **Dark Mode** (default)
- Color scheme: Catppuccin Mocha
- Font: Segoe UI (modern, clean)

## 📊 Dashboard Stats

### Stat Cards
1. **Total** - Total accounts in results
2. **Complete** - Accounts with status "complete"
3. **Failed** - Accounts with status "failed"
4. **With API Key** - Accounts with extracted `sk-xxx` keys

### Progress Bar
- Shows: `X / Y (Z%)`
- Updates in real-time during farming
- Green color for progress

## ⚙️ Configuration

### Gmail Credentials
- **Gmail Address**: Your Gmail (e.g., `your@gmail.com`)
- **App Password**: Gmail App Password (16 chars, spaces allowed)
  - ⚠️ **NOT** your regular Gmail password
  - Generate at: https://myaccount.google.com/apppasswords

### Farming Options
- **Count**: Number of accounts to register (1-100)
- **Concurrency**: Parallel browsers (1-10)
- **Proxy**: HTTP proxy (optional, e.g., `http://127.0.0.1:8080`)

### Advanced Options
- **Show Browser**: Disable headless mode (visible browser)
- **Debug Mode**: Enable screenshots at each step

## 📋 Results Table

### Columns
1. **#** - Row number
2. **Email** - Registered email (Gmail dot trick alias)
3. **API Key** - Extracted API key (truncated: `sk-ws-xxx...`)
4. **Status** - ✓ Complete / ✗ Failed / ⏳ Pending
5. **Timestamp** - When account was created
6. **Gmail Account** - Base Gmail account used

### Features
- **Sort**: Click column header to sort (asc/desc)
- **Filter**: Type in search box to filter
- **Copy**: Double-click row to copy API key
- **Export**: CSV or JSON format
- **Refresh**: Reload from `qwen_results.json`

## 🎯 Usage Workflow

### 1. Configure
1. Go to **⚙️ Configuration** tab
2. Enter Gmail credentials
3. Set count and concurrency
4. Click **💾 Save Configuration**

### 2. Start Farming
1. Go to **📊 Dashboard** tab
2. Adjust quick settings (optional)
3. Click **▶ Start Farming**
4. Auto-switch to **📜 Live Logs** tab

### 3. Monitor Progress
- Watch live logs with color-coded messages
- Check progress bar
- Pause/Resume if needed
- Stop anytime with **⏹ Stop** button

### 4. View Results
1. Go to **📋 Results** tab
2. Sort/filter as needed
3. Export to CSV/JSON
4. Double-click to copy API keys

## 🔧 Technical Details

### Files
- `qwen_farm_gui.py` - Main GUI application (36KB)
- `run_qwen_gui.bat` - Windows launcher
- `alibaba_farm.py` - Backend farming logic (wrapper function added)

### Integration
GUI calls `run_qwen_farm(args)` function in `alibaba_farm.py`:
```python
args = type('Args', (), {
    'gmail': 'your@gmail.com',
    'apppass': '**** **** **** ****',
    'count': 10,
    'concurrency': 3,
    'proxy': None,
    'show': False,
    'debug': False,
})()

from alibaba_farm import run_qwen_farm
run_qwen_farm(args)
```

### Thread Safety
- Log handler uses `threading.Lock()` for safe writes
- UI updates scheduled via `after(0, callback)`
- Stop flag checked in farming loop
- Pause flag blocks thread when set

### Output Files
- `qwen_results.json` - JSON results (auto-saved)
- `qwen_accounts.csv` - CSV backup (auto-saved)

## 🐛 Troubleshooting

### GUI doesn't start
```bash
# Check Python version
python --version  # Should be 3.8+

# Install dependencies
pip install customtkinter packaging python-dotenv

# Test import
python -c "import customtkinter; print('OK')"
```

### Gmail credentials error
- Make sure App Password is 16 characters
- Enable 2FA on Gmail account first
- Generate new App Password at: https://myaccount.google.com/apppasswords

### Farming stops immediately
- Check logs for error messages
- Verify Gmail credentials in Configuration tab
- Try with `Show Browser` enabled to see what happens

### API key not extracted
- Some accounts may fail extraction (normal)
- Check if account was registered (status: "registered")
- Try increasing timeout or enabling Debug Mode

## 📝 Notes

- **GUI vs CLI**: This is a modern GUI alternative to CLI mode
- **Same Backend**: Uses same farming logic as CLI
- **Real-time Updates**: Dashboard stats update every 5 seconds
- **Export Options**: CSV for Excel, JSON for programmatic use
- **Cross-platform**: Works on Windows, macOS, Linux (with Python 3.8+)

## 🎉 Comparison: CLI vs GUI

| Feature | CLI (`alibaba_farm.py`) | GUI (`qwen_farm_gui.py`) |
|---------|------------------------|--------------------------|
| **UI** | Terminal text | Modern window |
| **Setup** | Edit .env manually | Visual config panel |
| **Progress** | Text logs | Progress bar + stats |
| **Control** | Ctrl+C only | Start/Pause/Stop |
| **Results** | Open file manually | Built-in table |
| **Export** | None | CSV/JSON buttons |
| **Logs** | Console scroll | Color-coded viewer |
| **Beginner** | ❌ CLI knowledge needed | ✅ Click & run |
| **VPS/Server** | ✅ Ideal (headless) | ❌ Needs display |

## 🚀 Future Enhancements

- [ ] System tray icon (minimize to tray)
- [ ] Screenshot preview (debug mode)
- [ ] Auto-retry failed accounts
- [ ] Bulk export all API keys to text file
- [ ] Schedule farming (cron-like)
- [ ] Email notifications on completion
- [ ] Statistics charts (success rate, time per account)

---

**Created**: 2026-06-30  
**Version**: 1.0.0  
**License**: Same as alibaba-cloud-farm project
