"""
reCAPTCHA auto-solver using audio challenge method.
Adapted from sarperavci/GoogleRecaptchaBypass for Playwright.

Usage:
    from recaptcha_solver import solve_recaptcha_playwright
    solved = solve_recaptcha_playwright(page, timeout=60)
"""
import os
import time
import random
import urllib.request
import logging

logger = logging.getLogger("captcha_solver")

# Optional deps — graceful if missing
try:
    import pydub
    HAS_PYDUB = True
except ImportError:
    HAS_PYDUB = False

try:
    import speech_recognition
    HAS_SR = True
except ImportError:
    HAS_SR = False

try:
    from playwright.sync_api import Page, Frame
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

TEMP_DIR = os.getenv("TEMP") if os.name == "nt" else "/tmp"


def solve_recaptcha_playwright(page, timeout=60):
    """
    Attempt to solve reCAPTCHA via audio challenge using Playwright page.

    Args:
        page: Playwright Page instance
        timeout: max seconds to wait

    Returns:
        True if solved, False if failed
    """
    if not HAS_PYDUB or not HAS_SR:
        logger.error("Missing pydub or speech_recognition. Install: pip install pydub SpeechRecognition")
        return False

    logger.info("Starting reCAPTCHA audio solver...")

    # Step 1: Wait for reCAPTCHA iframe to appear and stabilize
    # Xiaomi wraps reCAPTCHA in miverify_wind — iframe may take time to load
    recaptcha_frame = None
    for attempt in range(15):  # 15 seconds
        for frame in page.frames:
            url = frame.url or ""
            if "recaptcha" in url.lower() or "google.com/recaptcha" in url:
                recaptcha_frame = frame
                break
        if recaptcha_frame:
            break
        time.sleep(1)

    if not recaptcha_frame:
        # Try finding via selector
        try:
            iframe_el = page.query_selector('iframe[title*="reCAPTCHA"], iframe[title*="recaptcha"], iframe[src*="recaptcha"]')
            if iframe_el:
                recaptcha_frame = iframe_el.content_frame()
        except:
            pass

    if not recaptcha_frame:
        logger.error("reCAPTCHA iframe not found")
        return False

    logger.info(f"Found reCAPTCHA iframe: {(recaptcha_frame.url or '')[:60]}...")

    # Wait for iframe content to load (not "Checking for security issues...")
    for _ in range(10):
        try:
            content = recaptcha_frame.content()
            if "rc-anchor" in content or "recaptcha-checkbox" in content:
                break
        except:
            pass
        time.sleep(1)

    # Step 2: Click the checkbox "I'm not a robot"
    try:
        checkbox = recaptcha_frame.query_selector('.rc-anchor-content')
        if checkbox:
            checkbox.click()
            logger.info("Clicked reCAPTCHA checkbox")
            time.sleep(2)
    except Exception as e:
        logger.error(f"Failed to click checkbox: {e}")
        return False

    # Step 3: Check if solved by just clicking
    if _is_solved_playwright(recaptcha_frame):
        logger.info("Solved by just clicking checkbox!")
        return True

    # Step 4: Try audio challenge
    logger.info("Checkbox not enough — trying audio challenge...")

    # Look for challenge iframe (appears after checkbox if challenge required)
    challenge_frame = None
    for frame in page.frames:
        url = frame.url or ""
        if "recaptcha/api2/bframe" in url or "recaptcha/api2" in url:
            challenge_frame = frame
            break

    if not challenge_frame:
        logger.error("Challenge iframe not found — may be Enterprise (no audio)")
        return False

    # Step 5: Click audio button
    try:
        audio_btn = challenge_frame.query_selector('#recaptcha-audio-button')
        if audio_btn:
            audio_btn.click()
            logger.info("Clicked audio challenge button")
            time.sleep(1.5)
        else:
            logger.error("Audio button not found — Enterprise may not offer audio")
            return False
    except Exception as e:
        logger.error(f"Failed to click audio button: {e}")
        return False

    # Step 6: Check for "detected as bot" message
    try:
        body_text = challenge_frame.inner_text('body')
        if "Try again later" in body_text or "detected" in body_text.lower():
            logger.error("Bot detected by reCAPTCHA")
            return False
    except:
        pass

    # Step 7: Download and process audio
    try:
        audio_source = challenge_frame.query_selector('#audio-source')
        if not audio_source:
            logger.error("Audio source element not found")
            return False

        audio_url = audio_source.get_attribute('src')
        if not audio_url:
            logger.error("Audio URL not found")
            return False

        logger.info(f"Downloading audio from: {audio_url[:60]}...")

        # Download + convert + recognize
        text = _process_audio(audio_url)
        if not text:
            logger.error("Speech recognition failed")
            return False

        logger.info(f"Recognized text: '{text}'")

        # Step 8: Input response and verify
        response_input = challenge_frame.query_selector('#audio-response')
        if response_input:
            response_input.fill(text.lower())
            time.sleep(0.3)

        verify_btn = challenge_frame.query_selector('#recaptcha-verify-button')
        if verify_btn:
            verify_btn.click()

        time.sleep(1)

        # Step 9: Check if solved
        if _is_solved_playwright(recaptcha_frame):
            logger.info("reCAPTCHA SOLVED via audio challenge!")
            return True
        else:
            logger.error("Audio answer was wrong")
            return False

    except Exception as e:
        logger.error(f"Audio challenge failed: {e}")
        return False


def _is_solved_playwright(recaptcha_frame):
    """Check if reCAPTCHA is solved by looking at checkbox state."""
    try:
        # Look for checked state
        checkmark = recaptcha_frame.query_selector('.recaptcha-checkbox-checkmark')
        if checkmark:
            style = checkmark.get_attribute('style') or ''
            if 'opacity' in style or 'block' in style:
                return True

        # Also check aria-checked
        checkbox = recaptcha_frame.query_selector('.recaptcha-checkbox')
        if checkbox:
            checked = checkbox.get_attribute('aria-checked')
            if checked == 'true':
                return True

        return False
    except:
        return False


def _process_audio(audio_url):
    """Download audio, convert to WAV, recognize speech."""
    mp3_path = os.path.join(TEMP_DIR, f"recaptcha_{random.randrange(1,10000)}.mp3")
    wav_path = os.path.join(TEMP_DIR, f"recaptcha_{random.randrange(1,10000)}.wav")

    try:
        # Download
        urllib.request.urlretrieve(audio_url, mp3_path)

        # Convert MP3 → WAV
        sound = pydub.AudioSegment.from_mp3(mp3_path)
        sound.export(wav_path, format="wav")

        # Recognize
        recognizer = speech_recognition.Recognizer()
        with speech_recognition.AudioFile(wav_path) as source:
            audio = recognizer.record(source)

        return recognizer.recognize_google(audio)

    except Exception as e:
        logger.error(f"Audio processing error: {e}")
        return None
    finally:
        for path in (mp3_path, wav_path):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except:
                    pass


if __name__ == "__main__":
    # Quick test
    print("Dependencies:")
    print(f"  pydub: {'OK' if HAS_PYDUB else 'MISSING'}")
    print(f"  speech_recognition: {'OK' if HAS_SR else 'MISSING'}")
    print(f"  playwright: {'OK' if HAS_PLAYWRIGHT else 'MISSING'}")
