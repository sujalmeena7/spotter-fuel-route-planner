"""Screenshot automation using headless Chrome and Selenium."""

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

PORT = 8000
BASE_URL = f"http://127.0.0.1:{PORT}/"
OUTPUT_DIR = Path("docs/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def ensure_server_running():
    try:
        resp = urllib.request.urlopen(f"{BASE_URL}healthz", timeout=1)
        if resp.status == 200:
            print(f"Server is already running on port {PORT}.")
            return None
    except Exception:
        pass

    print(f"Starting server on port {PORT}...")
    server = subprocess.Popen(
        [sys.executable, "manage.py", "runserver", f"127.0.0.1:{PORT}", "--noreload"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(40):
        try:
            resp = urllib.request.urlopen(f"{BASE_URL}healthz", timeout=1)
            if resp.status == 200:
                print("Server warmed and ready.")
                break
        except Exception:
            time.sleep(0.5)
    return server


def get_driver(width, height, is_mobile=False):
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument(f"--window-size={width},{height}")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    if is_mobile:
        opts.add_experimental_option(
            "mobileEmulation",
            {
                "deviceMetrics": {"width": width, "height": height, "pixelRatio": 2.0},
                "userAgent": (
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
                ),
            },
        )
    return webdriver.Chrome(options=opts)


def check_console_errors(driver, context_name):
    logs = driver.get_log("browser")
    severe_errors = [
        entry
        for entry in logs
        if entry["level"] == "SEVERE"
        and "favicon.ico" not in entry["message"]
        and "404" not in entry["message"]
    ]
    print(f"[{context_name}] Console entries: {len(logs)}, Severe errors: {len(severe_errors)}")
    if severe_errors:
        for err in severe_errors:
            print(f"  SEVERE ERROR: {err}")
    assert len(severe_errors) == 0, (
        f"Found severe console errors in {context_name}: {severe_errors}"
    )


def main():
    server = ensure_server_running()
    try:
        # 1. Desktop Light (1440x900): New York -> Los Angeles, practical mode
        print("\n--- Capturing desktop_light.png (1440x900) ---")
        driver = get_driver(1440, 900)
        try:
            driver.get(f"{BASE_URL}?theme=light")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".example-chip"))
            )

            # Click New York -> LA chip
            chips = driver.find_elements(By.CSS_SELECTOR, ".example-chip")
            ny_chip = None
            for c in chips:
                if "New York" in c.text or "LA" in c.text:
                    ny_chip = c
                    break
            if ny_chip:
                ny_chip.click()
            else:
                chips[0].click()

            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".hero-cost"))
            )

            # Settle rendering
            time.sleep(4.0)

            # Assert route-summary-bar is displayed and input card is collapsed
            summary_bar = driver.find_element(By.ID, "route-summary-bar")
            assert summary_bar.is_displayed(), "Expected route-summary-bar to be visible"
            input_card = driver.find_element(By.CSS_SELECTOR, ".route-input-card")
            assert not input_card.is_displayed(), "Expected route-input-card to be collapsed/hidden"

            # Assert route-line layer is rendered on map
            has_line = driver.execute_script("return !!window.mapInstance.getLayer('route-line');")
            assert has_line, "Expected route-line layer to be present on map"

            # Assert KPI cards and fuel chart are visible
            hero_cost = driver.find_element(By.CSS_SELECTOR, ".hero-cost")
            assert hero_cost.is_displayed(), "Expected hero-cost KPI to be visible"

            check_console_errors(driver, "desktop_light")
            driver.save_screenshot(str(OUTPUT_DIR / "desktop_light.png"))
            print("Successfully saved desktop_light.png (1440x900)")
        finally:
            driver.quit()

        # 2. Desktop Dark (1440x900): Dallas -> Denver, candidates toggled ON
        print("\n--- Capturing desktop_dark.png (1440x900) ---")
        driver = get_driver(1440, 900)
        try:
            driver.get(f"{BASE_URL}?theme=dark")
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".example-chip"))
            )

            # Click Dallas -> Denver chip
            chips = driver.find_elements(By.CSS_SELECTOR, ".example-chip")
            dallas_chip = None
            for c in chips:
                if "Dallas" in c.text:
                    dallas_chip = c
                    break
            if dallas_chip:
                dallas_chip.click()
            else:
                chips[1].click()

            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".hero-cost"))
            )

            # Toggle corridor stations ON
            btn_corridor = driver.find_element(By.ID, "btn-corridor-toggle")
            btn_corridor.click()

            time.sleep(4.0)

            # Verify corridor candidate layer is visible
            cand_visibility = driver.execute_script(
                "return window.mapInstance.getLayoutProperty('corridor-candidates-layer', 'visibility');"
            )
            print("Corridor candidate visibility:", cand_visibility)
            assert cand_visibility == "visible", "Expected corridor-candidates-layer to be visible"

            check_console_errors(driver, "desktop_dark")
            driver.save_screenshot(str(OUTPUT_DIR / "desktop_dark.png"))
            print("Successfully saved desktop_dark.png (1440x900)")
        finally:
            driver.quit()

        # 3. Mobile Half Snap (390x844 @2x): Dallas -> Denver, half snap, legend hidden
        print("\n--- Capturing mobile_half_snap.png (390x844 @2x) ---")
        driver = get_driver(390, 844, is_mobile=True)
        try:
            driver.get(BASE_URL)
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".example-chip"))
            )

            chips = driver.find_elements(By.CSS_SELECTOR, ".example-chip")
            for c in chips:
                if "Dallas" in c.text:
                    c.click()
                    break

            WebDriverWait(driver, 20).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, ".hero-cost"))
            )

            time.sleep(3.0)

            # Verify price legend is cleanly hidden at half snap on mobile
            legend_display = driver.execute_script(
                "return window.getComputedStyle(document.querySelector('.price-legend-box')).display;"
            )
            print("Mobile half-snap price legend display:", legend_display)
            assert legend_display == "none", (
                f"Expected price-legend-box to be hidden, got {legend_display}"
            )

            check_console_errors(driver, "mobile_half_snap")
            driver.save_screenshot(str(OUTPUT_DIR / "mobile_half_snap.png"))
            driver.save_screenshot(str(OUTPUT_DIR / "mobile.png"))
            print("Successfully saved mobile_half_snap.png (390x844 @2x)")
        finally:
            driver.quit()

        print("\nAll 3 screenshots captured and validated with 0 severe console errors!")
    finally:
        if server:
            server.terminate()
            server.wait()


if __name__ == "__main__":
    main()
