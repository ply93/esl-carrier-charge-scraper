#!/usr/bin/env python3
"""
Emirates Shipping Line - Carrier Charge Finder Scraper (GitHub Actions 優化版)
"""

import time
import json
import argparse
from pathlib import Path
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager


def create_driver(headless: bool = True) -> webdriver.Chrome:
    options = Options()
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--lang=en-US")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if headless:
        options.add_argument("--headless=new")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)

    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"}
    )
    return driver


def select_port(driver, input_id: str, hidden_id: str, port_text: str, timeout: int = 20):
    wait = WebDriverWait(driver, timeout)

    # 先確保 form 容器已經出現
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".carrier-charge-finder_container, #carrierChargeFinderForm")))

    input_el = wait.until(EC.element_to_be_clickable((By.ID, input_id)))
    input_el.clear()
    time.sleep(0.5)
    input_el.send_keys(port_text)
    time.sleep(1.2)

    try:
        # 等 autocomplete 出現
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "ul.ui-autocomplete")))
        items = driver.find_elements(By.CSS_SELECTOR, "ul.ui-autocomplete li.ui-menu-item")
        
        clicked = False
        for item in items:
            txt = item.text.strip().upper()
            if port_text.upper() in txt or any(part in txt for part in port_text.upper().split()):
                item.click()
                clicked = True
                break
        if not clicked and items:
            items[0].click()
    except TimeoutException:
        input_el.send_keys(Keys.ENTER)

    time.sleep(1)

    hidden = driver.find_element(By.ID, hidden_id)
    code = hidden.get_attribute("value")
    if not code:
        # 再試一次
        input_el.send_keys(Keys.ENTER)
        time.sleep(1)
        code = hidden.get_attribute("value")

    if not code:
        raise ValueError(f"無法正確選擇港口：{port_text}（hidden code 仍然係空）")
    
    print(f"  ✓ 已選 {port_text} → code = {code}")
    return code


def scrape_charges(origin: str, destination: str, cargo_type: str = "dry", headless: bool = True):
    url = "https://www.emiratesline.com/services-and-information/carrier-charge-finder/"
    driver = create_driver(headless=headless)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        print(f"打開頁面：{url}")
        driver.get(url)
        
        # 等頁面基本載入
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3)

        # 儲存初始頁面（方便 debug）
        Path(f"debug_page_{timestamp}.html").write_text(driver.page_source, encoding="utf-8")
        driver.save_screenshot(f"debug_screenshot_{timestamp}.png")
        print("已儲存 debug 頁面同截圖")

        print(f"選擇 Origin: {origin}")
        select_port(driver, "originPort", "originPortCode", origin)

        print(f"選擇 Destination: {destination}")
        select_port(driver, "destinationPort", "destinationPortCode", destination)

        # Cargo Type
        cargo_type = cargo_type.lower()
        radio = driver.find_element(By.ID, cargo_type)
        driver.execute_script("arguments[0].click();", radio)
        print(f"  ✓ Cargo Type = {cargo_type}")

        # 提交
        search_btn = driver.find_element(By.CSS_SELECTOR, "button.primary-btn[type='submit']")
        search_btn.click()
        print("已提交，等待結果...")
        time.sleep(6)

        # 儲存結果
        html_path = Path(f"result_{timestamp}.html")
        html_path.write_text(driver.page_source, encoding="utf-8")
        driver.save_screenshot(f"result_{timestamp}.png")
        print(f"已儲存結果 → {html_path}")

        # 簡單提取
        page_text = driver.find_element(By.TAG_NAME, "body").text
        charge_lines = [
            line.strip() for line in page_text.splitlines()
            if any(kw in line.lower() for kw in ["fee", "charge", "thc", "b/l", "documentation", "amount", "usd", "aed", "cny", "hkd"])
            and len(line.strip()) > 4
        ]

        output = {
            "origin": origin,
            "destination": destination,
            "cargo_type": cargo_type,
            "scraped_at": timestamp,
            "charge_related_lines": charge_lines[:40],
        }

        json_path = Path(f"charges_{timestamp}.json")
        json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已輸出 JSON → {json_path}")

        if charge_lines:
            print("\n=== 找到嘅收費相關文字 ===")
            for line in charge_lines[:15]:
                print(" •", line)
        else:
            print("⚠ 未明顯搵到收費文字，請下載 result_*.html 同 screenshot 檢查")

        return output

    except Exception as e:
        print(f"\n❌ 發生錯誤：{e}")
        # 失敗都儲存截圖同 HTML
        try:
            driver.save_screenshot(f"error_{timestamp}.png")
            Path(f"error_{timestamp}.html").write_text(driver.page_source, encoding="utf-8")
            print("已儲存 error 截圖同 HTML")
        except:
            pass
        raise

    finally:
        driver.quit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--origin", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--cargo", default="dry", choices=["dry", "reefer"])
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()

    scrape_charges(
        origin=args.origin,
        destination=args.destination,
        cargo_type=args.cargo,
        headless=args.headless,
    )
