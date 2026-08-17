import datetime
import os
import re
import time
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests


# ============================================================
# CONFIG
# ============================================================

MIN_LOT_COST = 15000.0
MAX_LOT_COST = 20000.0
MIN_QIB_SUBSCRIPTION = 10.0

INDIA_TIMEZONE = ZoneInfo("Asia/Kolkata")

BASE_URL = "https://www.nseindia.com"
IPO_LIST_URL = "https://www.nseindia.com/api/ipo-current-issue"
IPO_DETAIL_URL = "https://www.nseindia.com/api/ipo-detail"


# ============================================================
# REGEX
# ============================================================

LOT_SIZE_PATTERN = re.compile(
    r"([\d,]+)\s+Equity Shares"
)

PRICE_RANGE_PATTERN = re.compile(
    r"Rs\.?\s*([\d,]+(?:\.\d+)?)"
    r"\s+to\s+"
    r"Rs\.?\s*([\d,]+(?:\.\d+)?)"
)


# ============================================================
# NSE SCRAPER
# ============================================================

class NSEIPOScraper:

    def __init__(self):
        self.session = requests.Session()

        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": (
                    "application/json, text/plain, */*"
                ),
                "Accept-Language": (
                    "en-US,en;q=0.9"
                ),
                "Referer": (
                    "https://www.nseindia.com/"
                ),
                "Connection": "keep-alive",
            }
        )

        self._refresh_cookies()

    def _refresh_cookies(self):

        print("Initializing NSE session...")

        try:
            response = self.session.get(
                BASE_URL,
                timeout=15,
            )

            print(
                f"NSE homepage response: "
                f"{response.status_code}"
            )

        except requests.RequestException as e:

            print(
                f"NSE homepage request failed: {e}"
            )

    def _get(
        self,
        url: str,
        params: Optional[Dict] = None,
        retries: int = 3,
    ):

        for attempt in range(1, retries + 1):

            try:

                response = self.session.get(
                    url,
                    params=params,
                    timeout=20,
                )

                print(
                    f"GET {url} "
                    f"-> {response.status_code} "
                    f"(attempt {attempt}/{retries})"
                )

                if response.status_code == 200:
                    return response

                if response.status_code == 403:

                    print(
                        "NSE returned 403. "
                        "Refreshing cookies..."
                    )

                    self._refresh_cookies()

                if response.status_code == 429:

                    print(
                        "NSE rate limit detected."
                    )

                if attempt < retries:

                    sleep_time = attempt * 2

                    print(
                        f"Retrying in "
                        f"{sleep_time} seconds..."
                    )

                    time.sleep(sleep_time)

            except requests.RequestException as e:

                print(
                    f"Request error: {e} "
                    f"(attempt {attempt}/{retries})"
                )

                if attempt < retries:
                    time.sleep(attempt * 2)

        print(
            f"Request failed after "
            f"{retries} attempts: {url}"
        )

        return None

    def fetch_active_ipos(self) -> List[Dict]:

        print("\nFetching active IPOs...")

        response = self._get(
            IPO_LIST_URL
        )

        if not response:
            return []

        try:

            data = response.json()

            if isinstance(data, list):

                print(
                    f"Active IPOs found: "
                    f"{len(data)}"
                )

                return data

            print(
                "Unexpected IPO list response."
            )

            return []

        except Exception as e:

            print(
                f"Failed to parse IPO list: {e}"
            )

            return []

    def fetch_bid_details(
        self,
        symbol: str,
    ) -> List[Dict]:

        response = self._get(
            IPO_DETAIL_URL,
            params={
                "symbol": symbol
            },
        )

        if not response:
            return []

        try:

            return response.json().get(
                "bidDetails",
                [],
            )

        except Exception as e:

            print(
                f"Failed to parse bid details "
                f"for {symbol}: {e}"
            )

            return []

    def fetch_issue_info(
        self,
        symbol: str,
        series: str,
    ) -> List[Dict]:

        params = {
            "symbol": symbol
        }

        if series.upper() == "SME":
            params["series"] = "SME"

        response = self._get(
            IPO_DETAIL_URL,
            params=params,
        )

        if not response:
            return []

        try:

            return (
                response.json()
                .get("issueInfo", {})
                .get("dataList", [])
            )

        except Exception as e:

            print(
                f"Failed to parse issue info "
                f"for {symbol}: {e}"
            )

            return []


# ============================================================
# PARSING
# ============================================================

def parse_lot_size(
    issue_info_fields: List[Dict],
) -> Optional[int]:

    for field in issue_info_fields:

        if field.get("title") in (
            "Bid Lot",
            "Lot Size",
        ):

            value = field.get(
                "value"
            ) or ""

            match = LOT_SIZE_PATTERN.search(
                value
            )

            if match:

                return int(
                    match.group(1)
                    .replace(",", "")
                )

    return None


def parse_cut_off_price(
    issue_info_fields: List[Dict],
) -> Optional[float]:

    for field in issue_info_fields:

        if field.get("title") == "Price Range":

            value = field.get(
                "value"
            ) or ""

            match = PRICE_RANGE_PATTERN.search(
                value
            )

            if match:

                return float(
                    match.group(2)
                    .replace(",", "")
                )

    return None


def parse_subscription_times(
    bid_details: List[Dict],
) -> Tuple[
    Optional[float],
    Optional[float],
]:

    qib_multiple = None
    total_multiple = None

    for row in bid_details:

        category = row.get(
            "category",
            "",
        )

        times_str = row.get(
            "noOfTime"
        )

        try:

            times = (
                float(times_str)
                if times_str
                else None
            )

        except (
            ValueError,
            TypeError,
        ):

            times = None

        if "QIB" in category.upper():

            qib_multiple = times

        elif category == "Total":

            total_multiple = times

    return (
        qib_multiple,
        total_multiple,
    )


def parse_nse_date(
    date_str: str,
) -> datetime.date:

    return datetime.datetime.strptime(
        date_str,
        "%d-%b-%Y",
    ).date()


# ============================================================
# IPO PROCESSING
# ============================================================

def get_qib_ipos() -> Tuple[List[str], List[Dict]]:

    scraper = NSEIPOScraper()

    active_issues = (
        scraper.fetch_active_ipos()
    )

    today = datetime.datetime.now(
        INDIA_TIMEZONE
    ).date()

    print(
        f"\nIndia date: {today}"
    )

    print(
        f"Filters:"
        f" Lot ₹{MIN_LOT_COST:,.0f}"
        f" - ₹{MAX_LOT_COST:,.0f}"
        f" | QIB >= {MIN_QIB_SUBSCRIPTION}x"
    )

    # --------------------------------------------------------
    # Active IPO names
    # --------------------------------------------------------

    active_ipo_names = []

    for issue in active_issues:

        company_name = issue.get(
            "companyName"
        )

        symbol = issue.get(
            "symbol"
        )

        name = company_name or symbol

        if name:
            active_ipo_names.append(name)

    # --------------------------------------------------------
    # Qualified IPOs
    # --------------------------------------------------------

    qualifying_ipos = []

    for issue in active_issues:

        symbol = issue.get(
            "symbol"
        )

        company_name = issue.get(
            "companyName",
            symbol,
        )

        series = issue.get(
            "series",
            "",
        )

        start_date_str = issue.get(
            "issueStartDate"
        )

        end_date_str = issue.get(
            "issueEndDate"
        )

        if not symbol:
            continue

        if not start_date_str:
            continue

        if not end_date_str:
            continue

        try:

            end_date = parse_nse_date(
                end_date_str
            )

        except ValueError:

            print(
                f"Invalid end date for "
                f"{symbol}: {end_date_str}"
            )

            continue

        # ----------------------------------------------------
        # Last day
        # ----------------------------------------------------

        if today != end_date:

            print(
                f"Skipping {symbol}: "
                f"ends on {end_date}"
            )

            continue

        print(
            "\n"
            + "=" * 50
        )

        print(
            f"Checking final-day IPO:"
            f" {company_name}"
        )

        print(
            f"Symbol: {symbol}"
        )

        # ----------------------------------------------------
        # Issue information
        # ----------------------------------------------------

        time.sleep(0.5)

        issue_info_fields = (
            scraper.fetch_issue_info(
                symbol,
                series,
            )
        )

        lot_size = parse_lot_size(
            issue_info_fields
        )

        cut_off_price = (
            parse_cut_off_price(
                issue_info_fields
            )
        )

        if not lot_size:

            print(
                f"❌ {symbol}: "
                "Lot size unavailable."
            )

            continue

        if not cut_off_price:

            print(
                f"❌ {symbol}: "
                "Cut-off price unavailable."
            )

            continue

        # ----------------------------------------------------
        # Lot investment
        # ----------------------------------------------------

        lot_investment = round(
            lot_size * cut_off_price,
            2,
        )

        print(
            f"Lot size: {lot_size}"
        )

        print(
            f"Cut-off price:"
            f" ₹{cut_off_price:,.2f}"
        )

        print(
            f"Lot investment:"
            f" ₹{lot_investment:,.2f}"
        )

        if not (
            MIN_LOT_COST
            <= lot_investment
            <= MAX_LOT_COST
        ):

            print(
                f"❌ {symbol}: "
                "Lot investment outside range."
            )

            continue

        print(
            "✅ Lot investment passed."
        )

        # ----------------------------------------------------
        # Subscription
        # ----------------------------------------------------

        time.sleep(0.5)

        bid_details = (
            scraper.fetch_bid_details(
                symbol
            )
        )

        qib_multiple, total_multiple = (
            parse_subscription_times(
                bid_details
            )
        )

        print(
            f"QIB: {qib_multiple}x"
            if qib_multiple is not None
            else "QIB: N/A"
        )

        print(
            f"Total: {total_multiple}x"
            if total_multiple is not None
            else "Total: N/A"
        )

        if qib_multiple is None:

            print(
                f"❌ {symbol}: "
                "QIB subscription unavailable."
            )

            continue

        if qib_multiple < MIN_QIB_SUBSCRIPTION:

            print(
                f"❌ {symbol}: "
                f"QIB {qib_multiple}x "
                f"is below "
                f"{MIN_QIB_SUBSCRIPTION}x."
            )

            continue

        # ----------------------------------------------------
        # QUALIFIED
        # ----------------------------------------------------

        print(
            f"🎯 {symbol} QUALIFIED!"
        )

        qualifying_ipos.append(
            {
                "symbol": symbol,
                "company_name": company_name,
                "series": series,
                "issue_start_date": start_date_str,
                "issue_end_date": end_date_str,
                "lot_size": lot_size,
                "cut_off_price": cut_off_price,
                "lot_investment_amount": lot_investment,
                "qib_subscription_times": qib_multiple,
                "total_subscription_times": total_multiple,
            }
        )

    return (
        active_ipo_names,
        qualifying_ipos,
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram_message(
    message: str,
):

    bot_token = os.environ.get(
        "TELEGRAM_BOT_TOKEN"
    )

    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID"
    )

    if not bot_token:

        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing."
        )

    if not chat_id:

        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{bot_token}/sendMessage"
    )

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
        },
        timeout=20,
    )

    print(
        f"Telegram API response:"
        f" {response.status_code}"
    )

    if response.status_code != 200:

        print(
            response.text
        )

        response.raise_for_status()

    data = response.json()

    if not data.get("ok"):

        raise RuntimeError(
            f"Telegram error: {data}"
        )

    print(
        "✅ Telegram message sent."
    )


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_telegram_message(
    active_ipo_names: List[str],
    qualifying_ipos: List[Dict],
) -> str:

    today = datetime.datetime.now(
        INDIA_TIMEZONE
    ).strftime(
        "%d %b %Y"
    )

    lines = [
        "📊 IPO QIB TRACKER",
        f"📅 {today}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "📋 ACTIVE IPOs",
        "━━━━━━━━━━━━━━━━━━",
        "",
    ]

    # --------------------------------------------------------
    # Active IPO names only
    # --------------------------------------------------------

    if active_ipo_names:

        for name in active_ipo_names:

            lines.append(
                f"• {name}"
            )

    else:

        lines.append(
            "No active IPOs found."
        )

    # --------------------------------------------------------
    # Qualified IPOs
    # --------------------------------------------------------

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "🎯 QUALIFIED IPOs",
            "━━━━━━━━━━━━━━━━━━",
            "",
        ]
    )

    if not qualifying_ipos:

        lines.append(
            "No IPOs currently meet "
            "the qualification criteria."
        )

    else:

        for index, ipo in enumerate(
            qualifying_ipos,
            start=1,
        ):

            qib = ipo[
                "qib_subscription_times"
            ]

            total = ipo[
                "total_subscription_times"
            ]

            qib_text = (
                f"{qib}x"
                if qib is not None
                else "N/A"
            )

            total_text = (
                f"{total}x"
                if total is not None
                else "N/A"
            )

            lines.extend(
                [
                    f"🏢 {ipo['company_name']}",
                    f"📈 Symbol: {ipo['symbol']}",
                    f"📊 Series: {ipo['series']}",
                    "",
                    f"📅 Issue:"
                    f" {ipo['issue_start_date']}"
                    f" → "
                    f"{ipo['issue_end_date']}",
                    "",
                    f"📦 Lot Size:"
                    f" {ipo['lot_size']}",
                    f"💰 Cut-off:"
                    f" ₹{ipo['cut_off_price']:,.2f}",
                    f"💵 Lot Investment:"
                    f" ₹{ipo['lot_investment_amount']:,.2f}",
                    "",
                    f"🏦 QIB:"
                    f" {qib_text}",
                    f"📊 Total:"
                    f" {total_text}",
                    "",
                ]
            )

            if index < len(
                qualifying_ipos
            ):

                lines.extend(
                    [
                        "──────────────────",
                        "",
                    ]
                )

    # --------------------------------------------------------
    # Footer
    # --------------------------------------------------------

    lines.extend(
        [
            "",
            "⚠️ Automated NSE tracker.",
            "Verify subscription data before "
            "making investment decisions.",
        ]
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "🚀 Starting IPO QIB Tracker..."
    )

    print(
        "India time:",
        datetime.datetime.now(
            INDIA_TIMEZONE
        ),
    )

    # --------------------------------------------------------
    # Fetch IPO data
    # --------------------------------------------------------

    (
        active_ipo_names,
        qualifying_ipos,
    ) = get_qib_ipos()

    print(
        f"\nActive IPOs:"
        f" {len(active_ipo_names)}"
    )

    print(
        f"Qualified IPOs:"
        f" {len(qualifying_ipos)}"
    )

    # --------------------------------------------------------
    # Build Telegram message
    # --------------------------------------------------------

    message = build_telegram_message(
        active_ipo_names,
        qualifying_ipos,
    )

    print(
        "\n"
        + message
    )

    # --------------------------------------------------------
    # Always send Telegram
    # --------------------------------------------------------

    send_telegram_message(
        message
    )


if __name__ == "__main__":
    main()