import csv
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.common.exceptions import WebDriverException
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service as ChromeService
from selenium.webdriver.edge.service import Service as EdgeService
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


BROWSER = "edge"
BASE_URL = os.environ.get("ONLINE_BOUTIQUE_URL", "http://localhost:8080")
TIMEOUT = 20
RUN_COUNT = 5
DEFAULT_CHROMEDRIVER_PATH = r"D:\chromedriver-win64\chromedriver.exe"
DEFAULT_EDGEDRIVER_PATH = r"D:\edgedriver_win64\msedgedriver.exe"

ROOT_DIR = Path(__file__).resolve().parent
RESULT_FILE = ROOT_DIR / "online_boutique_metrics.csv"
CSV_FIELDS = [
    "system",
    "browser",
    "test_step",
    "status",
    "duration_seconds",
    "remark",
    "timestamp",
]


def ensure_csv_header():
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not RESULT_FILE.exists() or RESULT_FILE.stat().st_size == 0:
        with RESULT_FILE.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()


def write_metric(step, status, duration, remark=""):
    ensure_csv_header()
    with RESULT_FILE.open("a", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writerow(
            {
                "system": "Online Boutique",
                "browser": BROWSER,
                "test_step": step,
                "status": status,
                "duration_seconds": f"{duration:.3f}",
                "remark": remark,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
        )


def create_driver():
    browser = BROWSER.strip().lower()
    profile_dir = tempfile.mkdtemp(prefix=f"selenium-{browser}-")
    prefs = {
        "autofill.profile_enabled": False,
        "autofill.credit_card_enabled": False,
        "autofill.credit_card_upload_enabled": False,
        "autofill.credit_card_fido_auth_enabled": False,
        "credentials_enable_service": False,
        "payments.can_make_payment_enabled": False,
        "profile.password_manager_enabled": False,
        "profile.password_manager_leak_detection": False,
    }
    common_args = [
        "--start-maximized",
        f"--user-data-dir={profile_dir}",
        "--disable-save-password-bubble",
        "--disable-popup-blocking",
        "--disable-sync",
        "--disable-extensions",
        "--disable-component-update",
        "--disable-features=AutofillServerCommunication,PasswordManagerOnboarding,PaymentRequest,SecurePaymentConfirmation",
    ]
    if browser == "chrome":
        options = webdriver.ChromeOptions()
        for argument in common_args:
            options.add_argument(argument)
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        driver_path = (
            os.environ.get("CHROMEDRIVER_PATH")
            or DEFAULT_CHROMEDRIVER_PATH
            or shutil.which("chromedriver")
        )
        try:
            if driver_path:
                return webdriver.Chrome(service=ChromeService(driver_path), options=options)
            return webdriver.Chrome(options=options)
        except WebDriverException as error:
            raise RuntimeError(
                "Unable to start Chrome WebDriver. Selenium Manager may be unable to "
                "download drivers in the current network environment. Install ChromeDriver "
                "matching your Chrome version, add it to PATH, or set CHROMEDRIVER_PATH "
                "to the full chromedriver.exe path."
            ) from error
    if browser == "edge":
        options = webdriver.EdgeOptions()
        for argument in common_args:
            options.add_argument(argument)
        options.add_experimental_option("prefs", prefs)
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        driver_path = (
            os.environ.get("EDGEDRIVER_PATH")
            or DEFAULT_EDGEDRIVER_PATH
            or shutil.which("msedgedriver")
        )
        try:
            if driver_path:
                return webdriver.Edge(service=EdgeService(driver_path), options=options)
            return webdriver.Edge(options=options)
        except WebDriverException as error:
            raise RuntimeError(
                "Unable to start Edge WebDriver. Install Microsoft Edge WebDriver matching "
                "your Edge version, add it to PATH, or set EDGEDRIVER_PATH to the full "
                "msedgedriver.exe path."
            ) from error
    raise ValueError(f"Unsupported browser: {BROWSER}. Use 'chrome' or 'edge'.")


def wait_for_any(driver, wait, candidates, condition="presence"):
    last_error = None
    for by, value in candidates:
        try:
            if condition == "clickable":
                return wait.until(EC.element_to_be_clickable((by, value)))
            if condition == "visible":
                return wait.until(EC.visibility_of_element_located((by, value)))
            return wait.until(EC.presence_of_element_located((by, value)))
        except TimeoutException as error:
            last_error = error
    locators = "; ".join(f"{by}={value}" for by, value in candidates)
    raise TimeoutException(f"No matching element found. Tried: {locators}") from last_error


def click_element(driver, element):
    driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
    element.click()


def fill_first(driver, wait, candidates, value):
    element = wait_for_any(driver, wait, candidates, "visible")
    element.clear()
    element.send_keys(value)
    return element


def select_or_fill(driver, wait, candidates, visible_text):
    element = wait_for_any(driver, wait, candidates, "visible")
    tag_name = element.tag_name.lower()
    if tag_name == "select":
        select = Select(element)
        try:
            select.select_by_visible_text(visible_text)
            return element
        except NoSuchElementException:
            pass
        try:
            select.select_by_value(visible_text)
            return element
        except NoSuchElementException:
            pass
        normalized_target = visible_text.strip().lower().lstrip("0")
        month_aliases = {
            "1": {"1", "01", "jan", "january"},
            "2": {"2", "02", "feb", "february"},
            "3": {"3", "03", "mar", "march"},
            "4": {"4", "04", "apr", "april"},
            "5": {"5", "05", "may"},
            "6": {"6", "06", "jun", "june"},
            "7": {"7", "07", "jul", "july"},
            "8": {"8", "08", "aug", "august"},
            "9": {"9", "09", "sep", "september"},
            "10": {"10", "oct", "october"},
            "11": {"11", "nov", "november"},
            "12": {"12", "dec", "december"},
        }
        accepted = month_aliases.get(normalized_target, {normalized_target})
        for index, option in enumerate(select.options):
            text = option.text.strip().lower()
            value = (option.get_attribute("value") or "").strip().lower()
            if text.lstrip("0") in accepted or value.lstrip("0") in accepted:
                select.select_by_index(index)
                return element
        options = [option.text.strip() for option in select.options]
        raise NoSuchElementException(
            f"Could not select {visible_text!r}; available options: {options}"
        )
    else:
        element.clear()
        element.send_keys(visible_text)
    return element


def run_step(step_name, action, metrics, run_number):
    start = time.perf_counter()
    last_stale_error = None
    final_error = None
    for attempt in range(1, 4):
        try:
            remark = action() or ""
            duration = time.perf_counter() - start
            if attempt > 1:
                remark = f"{remark}; retried stale element {attempt - 1} time(s)"
            metrics.append(
                {
                    "run": run_number,
                    "step": step_name,
                    "status": "pass",
                    "duration": duration,
                    "remark": remark,
                }
            )
            print(f"[RUN {run_number}/{RUN_COUNT}] [PASS] {step_name}: {duration:.3f}s {remark}")
            return remark
        except StaleElementReferenceException as error:
            last_stale_error = error
            if attempt < 3:
                print(f"[RUN {run_number}/{RUN_COUNT}] [RETRY] {step_name}: stale element, retry {attempt}/2")
                continue
            final_error = last_stale_error
        except Exception as error:
            final_error = error

        duration = time.perf_counter() - start
        remark = f"{type(final_error).__name__}: {final_error}"
        metrics.append(
            {
                "run": run_number,
                "step": step_name,
                "status": "fail",
                "duration": duration,
                "remark": remark,
            }
        )
        print(f"[RUN {run_number}/{RUN_COUNT}] [FAIL] {step_name}: {duration:.3f}s {remark}")
        raise final_error


def write_average_metrics(metrics):
    if not metrics:
        return
    ordered_steps = []
    for item in metrics:
        if item["step"] not in ordered_steps:
            ordered_steps.append(item["step"])

    for step in ordered_steps:
        step_items = [item for item in metrics if item["step"] == step]
        average_duration = sum(item["duration"] for item in step_items) / len(step_items)
        pass_count = sum(1 for item in step_items if item["status"] == "pass")
        fail_items = [item for item in step_items if item["status"] == "fail"]
        status = "pass" if pass_count == RUN_COUNT and not fail_items else "fail"
        remark = f"average of {len(step_items)}/{RUN_COUNT} runs; pass={pass_count}; fail={len(fail_items)}"
        if fail_items:
            first_failure = fail_items[0]
            remark += f"; first failure run={first_failure['run']}: {first_failure['remark']}"
        write_metric(step, status, average_duration, remark)


def run_flow_once(run_number, metrics):
    driver = create_driver()
    wait = WebDriverWait(driver, TIMEOUT)
    product_name = {"value": ""}

    try:
        def homepage_load():
            driver.get(BASE_URL)
            wait_for_any(
                driver,
                wait,
                [
                    (By.CSS_SELECTOR, "a[href*='/product/']"),
                    (By.CSS_SELECTOR, ".hot-product-card a"),
                    (By.CSS_SELECTOR, ".product-card a"),
                    (By.XPATH, "//main//*[self::a or self::h2 or self::h3]"),
                ],
                "presence",
            )
            return f"opened {BASE_URL}"

        run_step("homepage_load", homepage_load, metrics, run_number)

        def product_detail():
            product_link = wait_for_any(
                driver,
                wait,
                [
                    (By.CSS_SELECTOR, "a[href*='/product/']"),
                    (By.CSS_SELECTOR, ".hot-product-card a"),
                    (By.CSS_SELECTOR, ".product-card a"),
                    (By.XPATH, "//a[contains(@href, 'product')]"),
                ],
                "clickable",
            )
            click_element(driver, product_link)
            wait_for_any(
                driver,
                wait,
                [
                    (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add to cart')]"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                    (By.CSS_SELECTOR, "form[action*='cart'] button"),
                ],
                "clickable",
            )
            title_candidates = driver.find_elements(By.CSS_SELECTOR, "h1, h2, .product-title")
            if title_candidates:
                product_name["value"] = title_candidates[0].text.strip()
            return product_name["value"] or "product detail opened"

        run_step("product_detail", product_detail, metrics, run_number)

        def add_to_cart():
            add_button = wait_for_any(
                driver,
                wait,
                [
                    (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'add to cart')]"),
                    (By.CSS_SELECTOR, "form[action*='cart'] button[type='submit']"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                ],
                "clickable",
            )
            click_element(driver, add_button)
            wait_for_any(
                driver,
                wait,
                [
                    (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'cart')]"),
                    (By.CSS_SELECTOR, "a[href*='/cart']"),
                    (By.CSS_SELECTOR, "main"),
                ],
                "presence",
            )
            return "clicked Add to Cart"

        run_step("add_to_cart", add_to_cart, metrics, run_number)

        def cart_check():
            if "/cart" not in driver.current_url:
                cart_link = wait_for_any(
                    driver,
                    wait,
                    [
                        (By.CSS_SELECTOR, "a[href*='/cart']"),
                        (By.LINK_TEXT, "Cart"),
                        (By.PARTIAL_LINK_TEXT, "Cart"),
                    ],
                    "clickable",
                )
                click_element(driver, cart_link)
            wait_for_any(
                driver,
                wait,
                [
                    (By.CSS_SELECTOR, "main"),
                    (By.CSS_SELECTOR, "table"),
                    (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'shopping cart')]"),
                ],
                "presence",
            )
            page_text = driver.find_element(By.TAG_NAME, "body").text
            if product_name["value"] and product_name["value"] not in page_text:
                raise AssertionError(f"cart does not contain product: {product_name['value']}")
            if "empty" in page_text.lower() and not product_name["value"]:
                raise AssertionError("cart appears to be empty")
            return "cart contains selected product"

        run_step("cart_check", cart_check, metrics, run_number)

        def checkout_form_fill():
            fill_first(driver, wait, [(By.NAME, "email"), (By.ID, "email")], "tester@example.com")
            fill_first(
                driver,
                wait,
                [(By.NAME, "street_address"), (By.ID, "street_address"), (By.CSS_SELECTOR, "input[autocomplete='street-address']")],
                "1600 Amphitheatre Parkway",
            )
            fill_first(driver, wait, [(By.NAME, "zip_code"), (By.ID, "zip_code"), (By.NAME, "zip")], "94043")
            fill_first(driver, wait, [(By.NAME, "city"), (By.ID, "city")], "Mountain View")
            fill_first(driver, wait, [(By.NAME, "state"), (By.ID, "state")], "CA")
            select_or_fill(driver, wait, [(By.NAME, "country"), (By.ID, "country")], "United States")
            fill_first(
                driver,
                wait,
                [(By.NAME, "credit_card_number"), (By.ID, "credit_card_number"), (By.NAME, "cc_number")],
                "4111111111111111",
            )
            select_or_fill(
                driver,
                wait,
                [(By.NAME, "credit_card_expiration_month"), (By.ID, "credit_card_expiration_month"), (By.NAME, "cc_month")],
                "12",
            )
            select_or_fill(
                driver,
                wait,
                [(By.NAME, "credit_card_expiration_year"), (By.ID, "credit_card_expiration_year"), (By.NAME, "cc_year")],
                "2030",
            )
            fill_first(
                driver,
                wait,
                [(By.NAME, "credit_card_cvv"), (By.ID, "credit_card_cvv"), (By.NAME, "cc_cvv"), (By.NAME, "cvv")],
                "123",
            )
            return "checkout form filled"

        run_step("checkout_form_fill", checkout_form_fill, metrics, run_number)

        def checkout_submit():
            place_order_button = wait_for_any(
                driver,
                wait,
                [
                    (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'place order')]"),
                    (By.XPATH, "//input[contains(translate(@value, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'place order')]"),
                    (By.CSS_SELECTOR, "button[type='submit']"),
                ],
                "clickable",
            )
            click_element(driver, place_order_button)
            wait_for_any(
                driver,
                wait,
                [
                    (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'your order is complete')]"),
                    (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'order complete')]"),
                    (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'confirmation #')]"),
                    (By.XPATH, "//*[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'tracking #')]"),
                ],
                "presence",
            )
            page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
            success_words = ["your order is complete", "order complete", "confirmation #", "tracking #"]
            if not any(word in page_text for word in success_words):
                raise AssertionError("order confirmation message was not found")
            return "order confirmation displayed"

        run_step("checkout_submit", checkout_submit, metrics, run_number)

        def continue_shopping():
            continue_button = wait_for_any(
                driver,
                wait,
                [
                    (By.XPATH, "//a[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue shopping')]"),
                    (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continue shopping')]"),
                    (By.LINK_TEXT, "Continue Shopping"),
                    (By.PARTIAL_LINK_TEXT, "Continue"),
                ],
                "clickable",
            )
            click_element(driver, continue_button)
            wait_for_any(
                driver,
                wait,
                [
                    (By.CSS_SELECTOR, "a[href*='/product/']"),
                    (By.CSS_SELECTOR, ".hot-product-card a"),
                    (By.CSS_SELECTOR, ".product-card a"),
                    (By.XPATH, "//main//*[self::a or self::h2 or self::h3]"),
                ],
                "presence",
            )
            return "returned to shopping page"

        run_step("continue_shopping", continue_shopping, metrics, run_number)
        print(f"Online Boutique run {run_number}/{RUN_COUNT} completed.")
    finally:
        driver.quit()


def main():
    ensure_csv_header()
    metrics = []
    try:
        for run_number in range(1, RUN_COUNT + 1):
            print(f"Starting Online Boutique run {run_number}/{RUN_COUNT}...")
            run_flow_once(run_number, metrics)
        write_average_metrics(metrics)
        print(f"Online Boutique Selenium test completed. Average metrics for {RUN_COUNT} runs were written to CSV.")
    except Exception as error:
        write_average_metrics(metrics)
        print(f"Online Boutique Selenium test failed: {type(error).__name__}: {error}")
        print("Average metrics for completed steps were written to CSV.")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
