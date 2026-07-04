# core package — modular extraction from farm_headless.py
#
# Submodules:
#   config.py          — paths, constants, color scheme
#   helpers.py         — shared utility functions
#   browser_engine.py  — Playwright browser launch + anti-detect
#   email_providers.py — email provider backends (tempmail, gmail, outlook, etc.)
#   captcha_solver.py  — CAPTCHA detection and solving (Playwright, PyAutoGUI, 2Captcha)
#   registry.py        — farm tab registry and configuration system
