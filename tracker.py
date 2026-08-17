import datetime
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import requests


BASE_URL = "https://www.nseindia.com"
IPO_LIST_URL = "https://www.nseindia.com/api/ipo-current-issue"
IPO_DETAIL_URL = "https://www.nseindia.com/api/ipo-detail"

LOT_SIZE_PATTERN = re.compile(r"([\d,]+)\s+Equity Shares")
PRICE_RANGE_PATTERN = re.compile(
    r"Rs\.?\s*([\d,]+(?:\.\d+)?)\s+to\s+Rs\.?\s*([\d,]+(?:\.\d+)?)"
)


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
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.nseindia.com/",
            }
        )

        self._refresh_cookies()

    def _refresh_cookies(self):
        """Initialize NSE session cookies."""
        try:
            response = self.session.get(BASE_URL, timeout=15)
            print(f"NSE homepage: {response.status_code}")
        except Exception as e:
            print(f"Cookie refresh warning: {e}")

    def _get(self, url: str, params=None, retries: int = 3):
        """GET request with retry handling."""
        for attempt in range(retries):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=15,
                )

                if response.status_code == 200:
                    return response

                print(
                    f"Request failed: {response.status_code} "
                    f"(attempt {attempt + 1}/{retries})"
                )

                if response.status_code in (403, 429):
                    self._refresh_cookies()

            except requests.RequestException as e:
                print(
                    f"Request error: {e} "
                    f"(attempt {attempt + 1}/{retries})"
                )

            time.sleep(2 * (attempt + 1))

        return None

    def fetch_active_ipos(self) -> List[Dict]:
        """Fetch all current IPO issues."""
        response = self._get(IPO_LIST_URL)

        if not response:
            return []

        try:
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            print(f"Failed to parse IPO list: {e}")
            return []

    def fetch_bid_details(self, symbol: str) -> List[Dict]:
        """Fetch category-wise subscription details."""
        response = self._get(
            IPO_DETAIL_URL,
            params={"symbol": symbol},
        )

        if not response:
            return []

        try:
            return response.json().get("bidDetails", [])
        except Exception as e:
            print(f"Failed to parse bid details for {symbol}: {e}")
            return []

    def fetch_issue_info(
        self,
        symbol: str,
        series: str,
    ) -> List[Dict]:
        """Fetch lot size and price information."""
        params = {"symbol": symbol}

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
            print(f"Failed to parse issue info for {symbol}: {e}")
            return []


def parse_lot_size(
    issue_info_fields: List[Dict],
) -> Optional[int]:
    for field in issue_info_fields:
        if field.get("title") in ("Bid Lot", "Lot Size"):
            match = LOT_SIZE_PATTERN.search(
                field.get("value") or ""
            )

            if match:
                return int(
                    match.group(1).replace(",", "")
                )

    return None


def parse_cut_off_price(
    issue_info_fields: List[Dict],
) -> Optional[float]:
    for field in issue_info_fields:
        if field.get("title") == "Price Range":
            match = PRICE_RANGE_PATTERN.search(
                field.get("value") or ""
            )

            if match:
                return float(
                    match.group(2).replace(",", "")
                )

    return None


def parse_subscription_times(
    bid_details: List[Dict],
) -> Tuple[Optional[float], Optional[float]]:
    qib_multiple = None
    total_multiple = None

    for row in bid_details:
        category = row.get("category", "")
        times_str = row.get("noOfTime")

        try:
            times = float(times_str) if times_str else None
        except (ValueError, TypeError):
            times = None

        if "QIB" in category.upper():
            qib_multiple = times

        elif category == "Total":
            total_multiple = times

    return qib_multiple, total_multiple


def parse_nse_date(date_str: str) -> datetime.date:
    return datetime.datetime.strptime(
        date_str,
        "%d-%b-%Y",
    ).date()


def get_qib_ipos(
    min_lot_cost: float = 15000.0,
    max_lot_cost: float = 20000.0,
    min_qib_subscription: float = 10.0,
) -> List[Dict]:

    scraper = NSEIPOScraper()

    active_issues = scraper.fetch_active_ipos()

    today = datetime.date.today()

    qualifying_ipos = []

    print(f"Today: {today}")
    print(f"Active IPOs found: {len(active_issues)}")

    for issue in active_issues:
        symbol = issue.get("symbol")
        series = issue.get("series", "")
        start_date_str = issue.get("issueStartDate")
        end_date_str = issue.get("issueEndDate")

        if not symbol or not start_date_str or not end_date_str:
            continue

        try:
            end_date = parse_nse_date(end_date_str)
        except ValueError:
            print(
                f"Invalid end date for {symbol}: "
                f"{end_date_str}"
            )
            continue

        # Only process IPOs whose actual final day is today.
        if today != end_date:
            continue

        print(f"\nChecking final-day IPO: {symbol}")

        # Give NSE a small break between requests.
        time.sleep(0.5)

        issue_info_fields = scraper.fetch_issue_info(
            symbol,
            series,
        )

        lot_size = parse_lot_size(issue_info_fields)
        cut_off_price = parse_cut_off_price(
            issue_info_fields
        )

        if not lot_size or not cut_off_price:
            print("  Missing lot size or price.")
            continue

        lot_investment = round(
            lot_size * cut_off_price,
            2,
        )

        print(
            f"  Lot: {lot_size} | "
            f"Cut-off: ₹{cut_off_price} | "
            f"Investment: ₹{lot_investment}"
        )

        if not (
            min_lot_cost
            <= lot_investment
            <= max_lot_cost
        ):
            print("  ❌ Lot investment outside range.")
            continue

        time.sleep(0.5)

        bid_details = scraper.fetch_bid_details(
            symbol
        )

        qib_multiple, total_multiple = (
            parse_subscription_times(bid_details)
        )

        print(
            f"  QIB: {qib_multiple}x | "
            f"Total: {total_multiple}x"
        )

        if (
            qib_multiple is None
            or qib_multiple < min_qib_subscription
        ):
            print("  ❌ QIB subscription below threshold.")
            continue

        print("  ✅ QUALIFIED")

        qualifying_ipos.append(
            {
                "symbol": symbol,
                "company_name": issue.get(
                    "companyName",
                    symbol,
                ),
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

    return qualifying_ipos


def send_telegram_message(message: str):
    bot_token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]

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
        timeout=15,
    )

    response.raise_for_status()

    print("Telegram message sent successfully.")


def build_telegram_message(
    ipos: List[Dict],
) -> str:

    lines = [
        "🚨 IPO QIB ALERT",
        "",
        "Qualifying final-day IPOs:",
        "",
    ]

    for ipo in ipos:
        total = ipo["total_subscription_times"]

        total_text = (
            f"{total}x"
            if total is not None
            else "N/A"
        )

        lines.extend(
            [
                f"🏢 {ipo['company_name']}",
                f"📈 Symbol: {ipo['symbol']}",
                f"📅 Issue: {ipo['issue_start_date']} → "
                f"{ipo['issue_end_date']}",
                f"📦 Lot Size: {ipo['lot_size']}",
                f"💰 Cut-off: ₹"
                f"{ipo['cut_off_price']:,.2f}",
                f"💵 Lot Investment: ₹"
                f"{ipo['lot_investment_amount']:,.2f}",
                f"🏦 QIB Subscription: "
                f"{ipo['qib_subscription_times']}x",
                f"📊 Total Subscription: {total_text}",
                "",
                "────────────────────",
                "",
            ]
        )

    return "\n".join(lines)


def main():
    print("Starting IPO QIB Tracker...")

    ipos = get_qib_ipos()

    if not ipos:
        print("No qualifying IPOs found today.")

        # Don't send Telegram messages when nothing qualifies.
        return

    message = build_telegram_message(ipos)

    print("\n" + message)

    send_telegram_message(message)


if __name__ == "__main__":
    main()