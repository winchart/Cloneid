import time
import re
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import datetime
from dotenv import load_dotenv
import os
import hashlib
from selenium.common.exceptions import TimeoutException

# Load .env credentials
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
EMAIL = os.getenv("IVASMS_USERNAME")
PASSWORD = os.getenv("IVASMS_PASSWORD")

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": GROUP_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    # Retry logic to handle "Too Many Requests" error
    for _ in range(5): # 5 attempts
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            print("✅ Message successfully sent to Telegram.")
            time.sleep(1) # Add a small delay to respect Telegram's rate limits
            return
        except requests.exceptions.RequestException as e:
            if response.status_code == 429:
                print(f"❌ Failed to send message to Telegram: {e}. Retrying after a delay...")
                time.sleep(15)  # Wait for a longer period before retrying
            else:
                print(f"❌ Failed to send message to Telegram: {e}")
                return


options = Options()
options.add_argument('--headless')
options.add_argument("--disable-gpu")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
driver = webdriver.Chrome(options=options)

LOGIN_URL = "https://www.ivasms.com/login"
SMS_PAGE_URL = "https://www.ivasms.com/portal/sms/received"

last_seen_counts = {}
processed_messages = set()  # Track processed messages to avoid duplicates

def get_message_hash(msg_content):
    return hashlib.md5(msg_content.encode()).hexdigest()

def handle_popup():
    try:
        wait = WebDriverWait(driver, 5)
        next_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".driver-popover-next-btn")))
        next_btn.click()
        time.sleep(1)
        done_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".driver-popover-next-btn")))
        done_btn.click()
        print("✅ Closed tutorial popup.")
    except:
        print("ℹ️ No popup or already closed.")

def login():
    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 20)
    
    # Wait for the login form to be visible
    wait.until(EC.presence_of_element_located((By.NAME, "email"))).send_keys(EMAIL)
    wait.until(EC.presence_of_element_located((By.NAME, "password"))).send_keys(PASSWORD)
    
    # Use a more specific XPath to find the login button by its 'name' attribute
    login_button = wait.until(EC.element_to_be_clickable(
        (By.XPATH, '//button[@name="submit"]')))
    
    # Use JavaScript to click the button to avoid interception issues
    driver.execute_script("arguments[0].click();", login_button)
    
    print("✅ Logged in.")
    
    # Add a small delay to ensure navigation is complete
    time.sleep(2)
    
    # Navigate to SMS page and handle the popup
    driver.get(SMS_PAGE_URL)
    
    # Wait for any potential loading spinner to disappear before proceeding
    try:
        WebDriverWait(driver, 10).until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.waitMe_container')))
    except TimeoutException:
        print("ℹ️ Loading spinner did not disappear within the time limit, but continuing...")

    wait.until(EC.presence_of_element_located((By.ID, "ResultCDR")))
    print("🌐 Navigated to SMS page.")
    handle_popup()

def parse_message(country, number, msg, cli):
    time_now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    otp_match = re.search(r'\b(\d{5,8})\b', msg)
    otp_code = otp_match.group(1) if otp_match else "No OTP found"
    
    telegram_message = (
        f"🔥 *{country} {cli} OTP RECEIVED!* ✨\n\n"
        f"⏰ Time: {time_now}\n"
        f"🌍 Country: {country}\n"
        f"⚙️ Service: {cli}\n"
        f"☎️ Number: `{number}`\n"
        f"🔑 OTP: `{otp_code}`\n\n"
        f"📩 Full Message: \n{msg}"
    )
    return telegram_message

def click_get_sms():
    try:
        wait = WebDriverWait(driver, 20)
        get_sms_button = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[contains(text(), "Get SMS")]')))
        driver.execute_script("arguments[0].click();", get_sms_button)
        print("📅 Clicked 'Get SMS'")
        
        wait.until(EC.invisibility_of_element_located((By.CSS_SELECTOR, '.waitMe_container')))
        print("✅ Loading spinner disappeared.")
    except Exception as e:
        print(f"⚠️ 'Get SMS' button not found or not clickable: {e}")

def scrape_messages_loop():
    global last_seen_counts, processed_messages
    wait = WebDriverWait(driver, 15)

    while True:
        try:
            click_get_sms()
            new_messages_found_in_session = False
            
            # Get current page source
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            items_soup = soup.select('.item')
            current_counts = {}

            # Step 1: Process all service cards
            for item in items_soup:
                try:
                    item_card = item.select_one('.card.card-body.mb-1.pointer')
                    if not item_card:
                        continue
                    
                    onclick_attr = item_card.get('onclick', '')
                    item_id_match = re.search(r"getDetials\('([^']*)'\)", onclick_attr)
                    item_id = item_id_match.group(1).strip() if item_id_match else None

                    if not item_id:
                        continue

                    item_total_count_p = item.select_one('.card.card-body.mb-1.pointer p.mb-0.pb-0')
                    item_total_count = int(item_total_count_p.text) if item_total_count_p and item_total_count_p.text.strip().isdigit() else 0
                    
                    current_counts[item_id] = {'total_count': item_total_count, 'numbers': {}}
                    last_total_count = last_seen_counts.get(item_id, {}).get('total_count', 0)
                    
                    if item_total_count > last_total_count:
                        new_messages_found_in_session = True
                        print(f"🟢 New messages detected for service: {item_id}. Old count: {last_total_count}, New count: {item_total_count}")
                        
                        # Click to open service details
                        item_element = wait.until(EC.presence_of_element_located(
                            (By.XPATH, f"//div[contains(@onclick, \"getDetials('{item_id}')\")]")))
                        driver.execute_script("arguments[0].click();", item_element)
                        print(f"🖱️ Clicked to open details for: {item_id}")
                        
                        # Wait for numbers to load completely
                        try:
                            WebDriverWait(driver, 10).until(
                                EC.presence_of_element_located(
                                    (By.XPATH, f'//div[contains(@class, "open_{item_id.replace(" ", "_")}")]//div[contains(@onclick, "getDetialsNumber")]')
                                )
                            )
                        except TimeoutException:
                            print(f"⚠️ Numbers didn't load for {item_id}")
                            continue

                        # Find ALL number cards using a more robust XPath
                        number_cards = driver.find_elements(
                            By.XPATH,
                            f'//div[contains(@class, "open_{item_id.replace(" ", "_")}")]//div[contains(@onclick, "getDetialsNumber")]'
                        )
                        print(f"🔍 Found {len(number_cards)} number cards inside {item_id}")

                        for number_card in number_cards:
                            try:
                                number_element = number_card
                                number = number_element.text.strip()
                                
                                count_element = number_element.find_element(By.XPATH, './following-sibling::div[1]/p')
                                number_msg_count = int(count_element.text) if count_element.text.strip().isdigit() else 0
                                
                                current_counts[item_id]['numbers'][number] = number_msg_count
                                last_number_count = last_seen_counts.get(item_id, {}).get('numbers', {}).get(number, 0)
                                
                                if number_msg_count > last_number_count:
                                    print(f"🟢 New message found for number: {number} (Count: {number_msg_count})")
                                    
                                    # Click number to load messages
                                    driver.execute_script("arguments[0].click();", number_element)
                                    print(f"🖱️ Clicked to open SMS details for number: {number}")
                                    
                                    # Wait for messages to load completely
                                    try:
                                        WebDriverWait(driver, 10).until(
                                            lambda d: len(d.find_elements(
                                                By.CSS_SELECTOR, '.ContentSMS.open .card.bg-soft-dark')) >= number_msg_count
                                        )
                                    except TimeoutException:
                                        print(f"⚠️ Only loaded {len(driver.find_elements(By.CSS_SELECTOR, '.ContentSMS.open .card.bg-soft-dark'))} messages out of {number_msg_count}")

                                    # Process all messages
                                    sms_cards = driver.find_elements(By.CSS_SELECTOR, '.ContentSMS.open .card.bg-soft-dark')
                                    print(f"🔎 Found {len(sms_cards)} total messages for {number}")
                                    
                                    # Process only new messages
                                    for i in range(last_number_count, len(sms_cards)):
                                        try:
                                            msg_card = sms_cards[i]
                                            cli_element = msg_card.find_element(By.CSS_SELECTOR, 'div.col-sm-4')
                                            message_element = msg_card.find_element(By.CSS_SELECTOR, 'div.col-9.col-sm-6 p.mb-0.pb-0')
                                            
                                            cli = cli_element.text.replace('CLI', '').strip()
                                            full_message = message_element.text
                                            msg_hash = get_message_hash(full_message)
                                            
                                            if msg_hash not in processed_messages:
                                                processed_messages.add(msg_hash)
                                                country_name = ' '.join(item_id.split(' ')[:-1]).strip() if len(item_id.split(' ')) > 1 else item_id
                                                telegram_message = parse_message(country_name, number, full_message, cli)
                                                send_to_telegram(telegram_message)
                                            else:
                                                print(f"ℹ️ Message already processed for {number}")
                                                
                                        except Exception as msg_error:
                                            print(f"❌ Error processing message {i+1} for {number}: {msg_error}")
                                    
                                    # Collapse number view
                                    driver.execute_script("arguments[0].click();", number_element)
                                    print(f"🖱️ Collapsed number view for: {number}")
                                    time.sleep(0.5)
                                    
                            except Exception as number_error:
                                print(f"❌ Error processing number card: {number_error}")
                        
                        # Collapse service view
                        driver.execute_script("arguments[0].click();", item_element)
                        print(f"🖱️ Collapsed item view for: {item_id}")
                        time.sleep(0.5)
                        
                except Exception as item_error:
                    print(f"❌ Error processing item {item_id if 'item_id' in locals() else 'unknown'}: {item_error}")
            
            # Update last seen counts
            if new_messages_found_in_session:
                last_seen_counts = current_counts
                print("🔄 Caching current counts for the next check.")
            else:
                print("ℹ️ No new messages found. Waiting for next check.")
                
        except Exception as e:
            print(f"❌ An error occurred during the main scraping loop: {e}")
            
        time.sleep(10)


if __name__ == "__main__":
    try:
        login()
        scrape_messages_loop()
    except KeyboardInterrupt:
        print("\nScript stopped by user")
    finally:
        driver.quit()
        print("Browser closed.")