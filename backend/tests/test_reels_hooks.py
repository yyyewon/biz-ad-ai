from app.utils.reels_hooks import resolve_reels_hook_lines


def test_open_announcement_hook_uses_store_name_and_location():
    copy = resolve_reels_hook_lines(
        "오픈 소식 알림",
        store_name="온기식당",
        menu_name="고추장 찌개",
        store_location="성수동",
        price_text="9,000원",
    )

    assert copy.lead_line == "성수동에 새로 오픈한"
    assert copy.emphasis_line == "줄 서먹는 온기식당?"


def test_event_promotion_hook_uses_price():
    copy = resolve_reels_hook_lines(
        "이벤트/프로모션",
        store_name="온기식당",
        menu_name="고추장 찌개",
        store_location="성수동",
        price_text="9,000원",
    )

    assert copy.lead_line == "인당 9,000원"
    assert copy.emphasis_line == "온기식당 고추장 찌개?"
