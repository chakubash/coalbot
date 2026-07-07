from playwright.sync_api import sync_playwright

MYSTEEL_PROFILE = "/root/coalbot/browser_profiles/mysteel_live"
SXCOAL_PROFILE = "/root/coalbot/browser_profiles/sxcoal_live"


def login_mysteel_once():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=MYSTEEL_PROFILE,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.new_page()
        page.goto("https://news.mysteel.com/", wait_until="load", timeout=120000)
        print("Войди в Mysteel вручную в открывшемся окне.")
        input("После логина и проверки доступа нажми Enter здесь...")
        context.close()


def login_sxcoal_once():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=SXCOAL_PROFILE,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = context.new_page()
        page.goto("https://www.sxcoal.com/en", wait_until="load", timeout=120000)
        print("Войди в SXCoal вручную в открывшемся окне.")
        input("После логина и проверки доступа нажми Enter здесь...")
        context.close()


if __name__ == "__main__":
    print("1 = Mysteel")
    print("2 = SXCoal")
    choice = input("Что логиним? ")

    if choice == "1":
        login_mysteel_once()
    elif choice == "2":
        login_sxcoal_once()
    else:
        print("Неизвестный выбор")
