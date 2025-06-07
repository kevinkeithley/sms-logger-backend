# process_logfile.py
import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

DB_FILE = "business_tracking.db"  # More descriptive name
LOGFILE = "logfile.txt"
SCHEMA = "schema.sql"


def init_db():
    """Initialize database with schema"""
    with sqlite3.connect(DB_FILE) as conn:
        with open(SCHEMA) as f:
            conn.executescript(f.read())
    logger.info("Database initialized")


def load_entries():
    """Load and parse entries from logfile"""
    entries = []
    try:
        with open(LOGFILE, "r") as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line.strip()))
                    except json.JSONDecodeError:
                        logger.warning(f"Skipped malformed line: {line}")
    except FileNotFoundError:
        logger.warning("Logfile not found")

    return entries


def process_mileage(entries):
    """Process mileage entries into raw and summary tables"""
    mileage_entries = [e for e in entries if e.get("type") == "mileage"]

    if not mileage_entries:
        return 0

    processed_count = 0

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Insert into mileage_raw
        for entry in mileage_entries:
            try:
                entry_id = entry.get("id") or str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT INTO mileage_raw (id, name, date, position, distance, received_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry_id,
                        entry["name"],
                        entry["date"],
                        entry["position"],
                        entry["distance"],
                        entry["received_at"],
                    ),
                )
                processed_count += 1
            except sqlite3.IntegrityError:
                logger.debug(f"Skipped duplicate mileage: {entry}")

        conn.commit()

        # Calculate and update summaries
        cursor.execute(
            """
            SELECT name, date, position, distance 
            FROM mileage_raw 
            ORDER BY name, date, position
        """
        )
        rows = cursor.fetchall()

        grouped = defaultdict(lambda: {"start": None, "mid": None, "end": None})
        for name, date, position, distance in rows:
            grouped[(name, date)][position] = distance

        # Update mileage_summary
        for (name, date), parts in grouped.items():
            start = parts["start"]
            mid = parts["mid"]
            end = parts["end"]

            total_miles = None

            if start is not None and end is not None:
                total_miles = end - start
            elif mid is not None:
                # Estimate from midpoint
                total_miles = mid * 2
                logger.info(
                    f"Estimated mileage for {name} on {date} from midpoint: {total_miles:.1f}"
                )

            if total_miles is not None and total_miles > 0:
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO mileage_summary (id, name, date, total_miles)
                    VALUES (
                        COALESCE(
                            (SELECT id FROM mileage_summary WHERE name = ? AND date = ?),
                            ?
                        ),
                        ?, ?, ?
                    )
                    """,
                    (name, date, str(uuid.uuid4()), name, date, total_miles),
                )

        conn.commit()

    logger.info(f"Processed {processed_count} mileage entries")
    return processed_count


def process_hours(entries):
    """Process hours entries"""
    hours_entries = [e for e in entries if e.get("type") == "hours"]

    if not hours_entries:
        return 0

    processed_count = 0

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        for entry in hours_entries:
            try:
                entry_id = entry.get("id") or str(uuid.uuid4())
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO hours (id, date, hours_today, hours_week, received_at)
                    VALUES (
                        COALESCE(
                            (SELECT id FROM hours WHERE date = ?),
                            ?
                        ),
                        ?, ?, ?, ?
                    )
                    """,
                    (
                        entry["date"],
                        entry_id,
                        entry["date"],
                        entry["hours_today"],
                        entry["hours_week"],
                        entry["received_at"],
                    ),
                )
                processed_count += 1
            except sqlite3.IntegrityError:
                logger.debug(f"Skipped duplicate hours: {entry}")

        conn.commit()

    logger.info(f"Processed {processed_count} hours entries")
    return processed_count


def clear_logfile():
    """Clear the logfile after successful processing"""
    open(LOGFILE, "w").close()
    logger.info("Logfile cleared")


def get_summary_data(name=None, date=None, days=7):
    """
    Get summary data for API responses
    This could be called by your Flask app to respond to SMS queries
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Build query based on parameters
        query = "SELECT name, date, total_miles FROM mileage_summary WHERE 1=1"
        params = []

        if name:
            query += " AND name = ?"
            params.append(name)

        if date:
            query += " AND date = ?"
            params.append(date)
        else:
            # Get last N days
            query += " AND date >= date('now', '-' || ? || ' days')"
            params.append(days)

        query += " ORDER BY date DESC, name"

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append({"name": row[0], "date": row[1], "miles": row[2]})

        return results


def get_hours_data(date=None, days=7):
    """Get hours data for API responses"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        query = "SELECT date, hours_today, hours_week FROM hours WHERE 1=1"
        params = []

        if date:
            query += " AND date = ?"
            params.append(date)
        else:
            query += " AND date >= date('now', '-' || ? || ' days')"
            params.append(days)

        query += " ORDER BY date DESC"

        cursor.execute(query, params)

        results = []
        for row in cursor.fetchall():
            results.append(
                {"date": row[0], "hours_today": row[1], "hours_week": row[2]}
            )

        return results


def get_weekly_hours_summary():
    """Get weekly hours summary with totals and averages"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Get the most recent week's data
        cursor.execute(
            """
            SELECT 
                MAX(date) as week_ending,
                MAX(hours_week) as total_hours,
                COUNT(*) as days_logged,
                AVG(hours_today) as avg_daily_hours
            FROM hours
            WHERE date >= date('now', '-7 days')
        """
        )

        row = cursor.fetchone()
        if row and row[1]:  # Check if we have data
            return {
                "week_ending": row[0],
                "total_hours": row[1],
                "days_logged": row[2],
                "avg_daily_hours": row[3],
                "overtime": max(0, row[1] - 40),  # Assuming 40 hour work week
            }
        return None


def get_pay_period_dates(date=None, pay_period_start_date="2025-05-19"):
    """
    Calculate pay period start and end dates for a given date.
    Pay periods start on Mondays, bi-weekly (14 days).
    Restaurant is closed Mondays.

    Args:
        date: The date to check (YYYY-MM-DD format), defaults to today
        pay_period_start_date: A known pay period start date (Monday)
    """
    from datetime import datetime, timedelta

    if date:
        check_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        check_date = datetime.now()

    # Known pay period start (Monday May 19, 2025)
    known_start = datetime.strptime(pay_period_start_date, "%Y-%m-%d")

    # Verify it's a Monday (0 = Monday in Python)
    if known_start.weekday() != 0:
        logger.warning(
            f"Pay period start date {pay_period_start_date} is not a Monday!"
        )

    # Calculate days since known start
    days_diff = (check_date - known_start).days

    # Find the pay period number and offset
    pay_period_num = days_diff // 14
    days_into_period = days_diff % 14

    # Calculate this pay period's start and end
    period_start = known_start + timedelta(days=pay_period_num * 14)
    period_end = period_start + timedelta(days=13)  # 14 days total, Monday to Sunday

    return {
        "start": period_start.strftime("%Y-%m-%d"),
        "end": period_end.strftime("%Y-%m-%d"),
        "days_remaining": 13 - days_into_period,
        "current_day": days_into_period + 1,  # Day 1-14 of pay period
    }


def get_pay_period_hours(date=None):
    """Get total hours for the current or specified pay period"""
    period = get_pay_period_dates(date)

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # Get all hours entries in this pay period
        cursor.execute(
            """
            SELECT 
                date,
                hours_today,
                hours_week
            FROM hours
            WHERE date >= ? AND date <= ?
            ORDER BY date
        """,
            (period["start"], period["end"]),
        )

        daily_hours = []
        total_hours = 0

        for row in cursor.fetchall():
            daily_hours.append({"date": row[0], "hours": row[1]})
            total_hours += row[1]

        # Calculate regular vs overtime (over 80 hours per pay period)
        regular_hours = min(total_hours, 80)
        overtime_hours = max(0, total_hours - 80)

        return {
            "period_start": period["start"],
            "period_end": period["end"],
            "days_remaining": period["days_remaining"],
            "total_hours": total_hours,
            "regular_hours": regular_hours,
            "overtime_hours": overtime_hours,
            "daily_breakdown": daily_hours,
            "days_worked": len(daily_hours),
        }


def get_pay_period_comparison(num_periods=3):
    """Compare hours across multiple pay periods"""
    results = []

    # Get current pay period
    current_period = get_pay_period_dates()
    check_date = datetime.strptime(current_period["start"], "%Y-%m-%d")

    for i in range(num_periods):
        # Go back i pay periods
        period_date = (check_date - timedelta(days=14 * i)).strftime("%Y-%m-%d")
        period_data = get_pay_period_hours(period_date)

        results.append(
            {
                "period": f"{period_data['period_start']} to {period_data['period_end']}",
                "total_hours": period_data["total_hours"],
                "regular_hours": period_data["regular_hours"],
                "overtime_hours": period_data["overtime_hours"],
                "days_worked": period_data["days_worked"],
            }
        )

    return results


def get_current_pay_period_info():
    """Get detailed info about the current pay period"""
    period = get_pay_period_dates()
    period_hours = get_pay_period_hours()

    # Calculate expected remaining work days (excluding Mondays)
    remaining_days = []
    current_date = datetime.now()
    end_date = datetime.strptime(period["end"], "%Y-%m-%d")

    while current_date.date() <= end_date.date():
        # Skip Mondays (restaurant closed)
        if current_date.weekday() != 0:  # 0 = Monday
            remaining_days.append(current_date.strftime("%Y-%m-%d"))
        current_date += timedelta(days=1)

    return {
        "period_start": period["start"],
        "period_end": period["end"],
        "current_day": period["current_day"],
        "total_days": 14,
        "hours_logged": period_hours["total_hours"],
        "days_worked": period_hours["days_worked"],
        "remaining_work_days": len(remaining_days),
        "avg_hours_needed": (
            (80 - period_hours["total_hours"]) / max(1, len(remaining_days))
            if len(remaining_days) > 0
            else 0
        ),
    }


def process_all():
    """Main processing function - could be called by cron or on-demand"""
    init_db()
    entries = load_entries()

    if not entries:
        logger.info("No entries to process")
        return {"mileage": 0, "hours": 0}

    logger.info(f"Processing {len(entries)} total entries")

    mileage_count = process_mileage(entries)
    hours_count = process_hours(entries)

    clear_logfile()

    return {"mileage": mileage_count, "hours": hours_count, "total": len(entries)}


if __name__ == "__main__":
    result = process_all()
    print(f"Processing complete: {result}")
