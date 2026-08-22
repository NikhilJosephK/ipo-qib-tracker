import datetime
from email.message import EmailMessage
import os
import re
import smtplib
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
# PARSING HELPERS
# ============================================================

def get_issue_info_field(
    issue_info_fields: List[Dict],
    target_titles: List[str],
) -> Optional[str]:

    for field in issue_info_fields:
        title = field.get("title", "").strip()
        for target in target_titles:
            if target.lower() in title.lower():
                val = field.get("value")
                if val:
                    return str(val).strip()
    return None


def parse_lot_size(
    issue_info_fields: List[Dict],
) -> Optional[int]:

    for field in issue_info_fields:

        if field.get("title") in (
            "Bid Lot",
            "Lot Size",
            "Market Lot",
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

            digits = "".join(filter(str.isdigit, value))
            if digits:
                return int(digits)

    return None


def parse_price_info(
    issue_info_fields: List[Dict],
) -> Tuple[Optional[str], Optional[float]]:

    price_band_str = None
    cut_off_price = None

    for field in issue_info_fields:

        title = field.get("title", "")

        if "Price" in title:

            value = field.get("value") or ""
            price_band_str = value

            match = PRICE_RANGE_PATTERN.search(value)

            if match:
                cut_off_price = float(
                    match.group(2).replace(",", "")
                )
            else:
                numbers = re.findall(r"[\d,]+(?:\.\d+)?", value)
                if numbers:
                    cut_off_price = float(numbers[-1].replace(",", ""))

    return price_band_str, cut_off_price


def parse_all_subscriptions(
    bid_details: List[Dict],
) -> Dict[str, Optional[float]]:

    subs = {
        "QIB": None,
        "NII": None,
        "Retail": None,
        "Total": None,
    }

    for row in bid_details:

        category = row.get("category", "")
        times_str = row.get("noOfTime")

        try:
            times = float(times_str) if times_str else None
        except (ValueError, TypeError):
            times = None

        cat_upper = category.upper()

        if "QIB" in cat_upper or "QUALIFIED INSTITUTIONAL" in cat_upper:
            subs["QIB"] = times
        elif "NON INSTITUTIONAL" in cat_upper or "NII" in cat_upper:
            subs["NII"] = times
        elif "RETAIL" in cat_upper or "INDIVIDUAL" in cat_upper:
            subs["Retail"] = times
        elif category == "Total":
            subs["Total"] = times

    return subs


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

def process_all_ipos() -> Tuple[List[str], List[Dict], List[Dict]]:

    scraper = NSEIPOScraper()
    active_issues = scraper.fetch_active_ipos()

    today = datetime.datetime.now(INDIA_TIMEZONE).date()

    print(f"\nIndia date: {today}")
    print(
        f"Filters: Lot ₹{MIN_LOT_COST:,.0f} - ₹{MAX_LOT_COST:,.0f} "
        f"| QIB >= {MIN_QIB_SUBSCRIPTION}x"
    )

    active_ipo_names = []
    qualifying_ipos = []
    all_detailed_ipos = []

    for issue in active_issues:

        symbol = issue.get("symbol")
        company_name = issue.get("companyName", symbol)
        series = issue.get("series", "")
        start_date_str = issue.get("issueStartDate")
        end_date_str = issue.get("issueEndDate")

        name = company_name or symbol
        if name:
            active_ipo_names.append(name)

        if not symbol or not start_date_str or not end_date_str:
            continue

        try:
            end_date = parse_nse_date(end_date_str)
            is_final_day = (today == end_date)
        except ValueError:
            end_date = None
            is_final_day = False

        time.sleep(0.5)
        issue_info_fields = scraper.fetch_issue_info(symbol, series)
        time.sleep(0.5)
        bid_details = scraper.fetch_bid_details(symbol)

        lot_size = parse_lot_size(issue_info_fields)
        price_band, cut_off_price = parse_price_info(issue_info_fields)
        subs = parse_all_subscriptions(bid_details)

        issue_size = get_issue_info_field(
            issue_info_fields,
            ["Issue Size", "Issue Amount", "Total Issue"],
        ) or issue.get("issueSize", "N/A")

        listing_date = get_issue_info_field(
            issue_info_fields,
            ["Listing Date", "Tentative Listing Date"],
        ) or "N/A"

        lot_investment = None
        if lot_size and cut_off_price:
            lot_investment = round(lot_size * cut_off_price, 2)

        ipo_record = {
            "symbol": symbol,
            "company_name": company_name,
            "series": series,
            "issue_start_date": start_date_str,
            "issue_end_date": end_date_str,
            "is_final_day": is_final_day,
            "price_band": price_band or "N/A",
            "cut_off_price": cut_off_price,
            "lot_size": lot_size,
            "lot_investment_amount": lot_investment,
            "issue_size": issue_size,
            "listing_date": listing_date,
            "qib_subscription_times": subs["QIB"],
            "nii_subscription_times": subs["NII"],
            "retail_subscription_times": subs["Retail"],
            "total_subscription_times": subs["Total"],
        }

        all_detailed_ipos.append(ipo_record)

        # Telegram Qualification Check (Final Day + Lot Cost + QIB >= 10x)
        if is_final_day and lot_investment and subs["QIB"] is not None:
            if (
                MIN_LOT_COST <= lot_investment <= MAX_LOT_COST
                and subs["QIB"] >= MIN_QIB_SUBSCRIPTION
            ):
                qualifying_ipos.append(ipo_record)

    return active_ipo_names, qualifying_ipos, all_detailed_ipos


# ============================================================
# TELEGRAM BUILDER & SENDER (UNCHANGED)
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

    if active_ipo_names:
        for name in active_ipo_names:
            lines.append(f"• {name}")
    else:
        lines.append("No active IPOs found.")

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
            "No IPOs currently meet the qualification criteria."
        )
    else:
        for index, ipo in enumerate(qualifying_ipos, start=1):
            qib = ipo["qib_subscription_times"]
            total = ipo["total_subscription_times"]

            qib_text = f"{qib}x" if qib is not None else "N/A"
            total_text = f"{total}x" if total is not None else "N/A"

            lines.extend(
                [
                    f"🏢 {ipo['company_name']}",
                    f"📈 Symbol: {ipo['symbol']}",
                    f"📊 Series: {ipo['series']}",
                    "",
                    f"📅 Issue: {ipo['issue_start_date']} → {ipo['issue_end_date']}",
                    "",
                    f"📦 Lot Size: {ipo['lot_size']}",
                    f"💰 Cut-off: ₹{ipo['cut_off_price']:,.2f}",
                    f"💵 Lot Investment: ₹{ipo['lot_investment_amount']:,.2f}",
                    "",
                    f"🏦 QIB: {qib_text}",
                    f"📊 Total: {total_text}",
                    "",
                ]
            )

            if index < len(qualifying_ipos):
                lines.extend(["──────────────────", ""])

    lines.extend(
        [
            "",
            "⚠️ Automated NSE tracker.",
            "Verify subscription data before making investment decisions.",
        ]
    )

    return "\n".join(lines)


def send_telegram_message(message: str):

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        raise RuntimeError("Telegram credentials missing in environment.")

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    response = requests.post(
        url,
        json={"chat_id": chat_id, "text": message},
        timeout=20,
    )

    if response.status_code != 200:
        response.raise_for_status()

    print("✅ Telegram message sent.")


# ============================================================
# EMAIL BUILDER (RICH DETAILS FOR GEMINI) & SENDER
# ============================================================

def build_email_message(all_detailed_ipos: List[Dict]) -> str:

    today_str = datetime.datetime.now(INDIA_TIMEZONE).strftime("%d %b %Y, %I:%M %p IST")

    lines = [
        f"NSE IPO COMPREHENSIVE MARKET REPORT - {today_str}",
        "============================================================",
        "",
    ]

    if not all_detailed_ipos:
        lines.append("No active IPO data available.")
        return "\n".join(lines)

    for index, ipo in enumerate(all_detailed_ipos, start=1):

        qib = ipo["qib_subscription_times"]
        nii = ipo["nii_subscription_times"]
        retail = ipo["retail_subscription_times"]
        total = ipo["total_subscription_times"]
        lot_inv = ipo["lot_investment_amount"]

        qib_str = f"{qib}x" if qib is not None else "N/A"
        nii_str = f"{nii}x" if nii is not None else "N/A"
        retail_str = f"{retail}x" if retail is not None else "N/A"
        total_str = f"{total}x" if total is not None else "N/A"
        lot_inv_str = f"₹{lot_inv:,.2f}" if lot_inv else "N/A"
        cutoff_str = f"₹{ipo['cut_off_price']:,.2f}" if ipo["cut_off_price"] else "N/A"

        # Evaluation criteria checks
        qib_pass = "YES" if (qib is not None and qib >= MIN_QIB_SUBSCRIPTION) else "NO"
        cost_pass = "YES" if (lot_inv and MIN_LOT_COST <= lot_inv <= MAX_LOT_COST) else "NO"
        final_day_pass = "YES" if ipo["is_final_day"] else "NO"

        lines.extend(
            [
                f"[{index}] COMPANY: {ipo['company_name']}",
                f"• Symbol / Series: {ipo['symbol']} / {ipo['series']}",
                f"• Price Band: {ipo['price_band']}",
                f"• Cut-off / Issue Price: {cutoff_str}",
                f"• Market Lot: {ipo['lot_size']} Equity Shares",
                f"• Minimum Lot Cost (Retail): {lot_inv_str}",
                f"• Issue Size: {ipo['issue_size']}",
                f"• Bidding Period: {ipo['issue_start_date']} to {ipo['issue_end_date']}",
                f"• Final Day to Bid Today: {final_day_pass}",
                f"• Tentative Listing Date: {ipo['listing_date']}",
                "",
                "  SUBSCRIPTION BREAKDOWN:",
                f"  - QIB Subscription: {qib_str}",
                f"  - NII / HNI Subscription: {nii_str}",
                f"  - Retail (RII) Subscription: {retail_str}",
                f"  - Total Subscription: {total_str}",
                "",
                "  CRITERIA VERIFICATION:",
                f"  - QIB >= 10x: {qib_pass} ({qib_str})",
                f"  - Retail Lot between ₹15k - ₹20k: {cost_pass} ({lot_inv_str})",
                f"  - Final Day to Bid: {final_day_pass}",
                "------------------------------------------------------------",
                "",
            ]
        )

    return "\n".join(lines)


def send_email_message(message: str):

    gmail_user = os.environ.get("GMAIL_USER")
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")

    if not gmail_user or not gmail_app_password:
        raise RuntimeError("GMAIL_USER or GMAIL_APP_PASSWORD missing in environment.")

    msg = EmailMessage()
    msg["Subject"] = "[NSE QIB] Daily Market Data"
    msg["From"] = gmail_user
    msg["To"] = gmail_user
    msg.set_content(message)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(gmail_user, gmail_app_password)
        smtp.send_message(msg)

    print("✅ Full IPO report email sent to Gmail.")


# ============================================================
# MAIN
# ============================================================

def main():

    print("🚀 Starting IPO QIB Tracker...")
    print("India time:", datetime.datetime.now(INDIA_TIMEZONE))

    # Process all active IPOs
    active_ipo_names, qualifying_ipos, all_detailed_ipos = process_all_ipos()

    print(f"\nActive IPOs: {len(active_ipo_names)}")
    print(f"Qualified IPOs: {len(qualifying_ipos)}")

    # 1. Build and send Telegram message (unchanged format)
    telegram_msg = build_telegram_message(active_ipo_names, qualifying_ipos)
    print("\n--- TELEGRAM MESSAGE ---\n" + telegram_msg)
    send_telegram_message(telegram_msg)

    # 2. Build and send Rich Email for Gemini Scheduled Action
    email_msg = build_email_message(all_detailed_ipos)
    print("\n--- GMAIL MESSAGE ---\n" + email_msg)
    send_email_message(email_msg)


if __name__ == "__main__":
    main()