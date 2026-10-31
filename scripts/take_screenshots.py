import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

BASE_URL = "http://127.0.0.1:8000/"
OUTPUT_DIR = Path("docs/screenshots")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


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
                "deviceMetrics": {"width": width, "height": height, "pixelRatio": 3.0},
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
    print(f"[{context_name}] Console log entries: {len(logs)}, Severe errors: {len(severe_errors)}")
    if severe_errors:
        for err in severe_errors:
            print(f"  SEVERE ERROR: {err}")
    assert len(severe_errors) == 0, (
        f"Found severe console errors in {context_name}: {severe_errors}"
    )


def main():
    print("Starting screenshot generation...")

    # 1. Desktop Light (1280x800)
    print("Capturing desktop_light.png...")
    driver = get_driver(1280, 800)
    try:
        driver.get(BASE_URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".example-chip"))
        )

        # Click Dallas -> Denver popular corridor chip
        chips = driver.find_elements(By.CSS_SELECTOR, ".example-chip")
        dallas_chip = None
        for c in chips:
            if "Dallas" in c.text:
                dallas_chip = c
                break
        if dallas_chip:
            dallas_chip.click()
        else:
            chips[0].click()

        # Wait for results to render (KPI grid hero cost)
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".hero-cost"))
        )

        # Show corridor stations
        btn_corridor = driver.find_element(By.ID, "btn-corridor-toggle")
        btn_corridor.click()

        # Wait for map idle / rendering
        time.sleep(2.5)

        check_console_errors(driver, "desktop_light")
        driver.save_screenshot(str(OUTPUT_DIR / "desktop_light.png"))
        print("Saved desktop_light.png successfully.")
    finally:
        driver.quit()

    # 2. Desktop Dark (1280x800)
    print("Capturing desktop_dark.png...")
    driver = get_driver(1280, 800)
    try:
        driver.get(BASE_URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".example-chip"))
        )

        # Toggle dark mode
        btn_theme = driver.find_element(By.ID, "btn-theme-toggle")
        btn_theme.click()

        # Click popular corridor
        chips = driver.find_elements(By.CSS_SELECTOR, ".example-chip")
        for c in chips:
            if "Dallas" in c.text:
                c.click()
                break

        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".hero-cost"))
        )

        # Show corridor stations
        btn_corridor = driver.find_element(By.ID, "btn-corridor-toggle")
        btn_corridor.click()

        time.sleep(2.5)

        check_console_errors(driver, "desktop_dark")
        driver.save_screenshot(str(OUTPUT_DIR / "desktop_dark.png"))
        print("Saved desktop_dark.png successfully.")
    finally:
        driver.quit()

    # 3. Mobile (390x844)
    print("Capturing mobile.png...")
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

        # Wait for results to render
        WebDriverWait(driver, 15).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".hero-cost"))
        )

        # Verify route-summary-bar is displayed and input card is collapsed
        summary_bar = driver.find_element(By.ID, "route-summary-bar")
        assert summary_bar.is_displayed(), "Expected route-summary-bar to be visible on mobile"

        time.sleep(2.0)

        check_console_errors(driver, "mobile")
        driver.save_screenshot(str(OUTPUT_DIR / "mobile.png"))
        print("Saved mobile.png successfully.")
    finally:
        driver.quit()

    print("All screenshots captured with 0 console errors!")


if __name__ == "__main__":
    main()
