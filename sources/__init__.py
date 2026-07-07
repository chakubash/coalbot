from .mysteel_fast import collect_links as collect_mysteel_fast_links
from .mysteel_jiaotan import collect_links as collect_mysteel_jiaotan_links
from .mysteel_coal_portal import collect_links as collect_mysteel_coal_portal_links
from .mysteel_list_fallback import collect_links as collect_mysteel_list_fallback_links
from .sxcoal import collect_links as collect_sxcoal_links
from .cls import collect_links as collect_cls_links


def collect_all_candidates():
    rows = []

    for name, fn in [
        ("mysteel_fast", lambda: collect_mysteel_fast_links(max_items=120)),
        ("mysteel_jiaotan", lambda: collect_mysteel_jiaotan_links(max_pages=10)),
        ("mysteel_coal_portal", lambda: collect_mysteel_coal_portal_links(max_pages=10)),
        ("mysteel_list_fallback", lambda: collect_mysteel_list_fallback_links(max_pages=3)),
        ("sxcoal", lambda: collect_sxcoal_links(max_pages=5)),
        ("cls", lambda: collect_cls_links(max_pages=4)),
    ]:
        try:
            part = fn() or []
            print(f"DEBUG_SOURCE {name}: {len(part)}")
            rows.extend(part)
        except Exception as e:
            print(f"DEBUG_SOURCE_ERROR {name}: {e}")

    print(f"DEBUG_SOURCE TOTAL: {len(rows)}")
    return rows
