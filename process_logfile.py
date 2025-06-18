# process_logfile.py
import json
import sqlite3
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
import logging
from config import DB_FILE, LOGFILE, SCHEMA, PAY_PERIOD_START  # Import from config

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


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


def get_hours_data(date=None, days=7, date_start=None, date_end=None):
    """Get hours data for API responses"""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        query = "SELECT date, hours_today, hours_week FROM hours WHERE 1=1"
        params = []

        if date_start and date_end:
            query += " AND date >= ? AND date <= ?"
            params.extend([date_start, date_end])
        elif date:
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


def get_pay_period_dates(date=None, pay_period_start_date=None):
    """
    Calculate pay period start and end dates for a given date.
    Pay periods start on Mondays, bi-weekly (14 days).
    Restaurant is closed Mondays.

    Args:
        date: The date to check (YYYY-MM-DD format), defaults to today
        pay_period_start_date: A known pay period start date (Monday)
    """
    if not pay_period_start_date:
        pay_period_start_date = PAY_PERIOD_START
        
    if date:
        check_date = datetime.strptime(date, "%Y-%m-%d")
    else:
        check_date = datetime.now()

    # Known pay period start (Monday)
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
    """Get hours for a pay period with proper weekly breakdown"""
    period = get_pay_period_dates(date)
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get the Sunday of week 1 (last day of week 1)
        period_start = datetime.strptime(period["start"], "%Y-%m-%d")
        week1_end = period_start + timedelta(days=6)  # Monday + 6 = Sunday
        week1_end_str = week1_end.strftime("%Y-%m-%d")
        
        # Get ALL entries for the pay period
        cursor.execute("""
            SELECT date, hours_today, hours_week
            FROM hours
            WHERE date >= ? AND date <= ?
            ORDER BY date
        """, (period["start"], period["end"]))
        
        all_entries = cursor.fetchall()
        
        # Process entries to get weekly totals
        week1_hours = 0
        week2_hours = 0
        daily_sum = 0
        daily_breakdown = []
        
        # Track the last hours_week value for each week
        last_week1_entry = None
        last_week2_entry = None
        
        for date_str, hours_today, hours_week in all_entries:
            daily_breakdown.append({"date": date_str, "hours": hours_today})
            daily_sum += hours_today
            
            # Determine which week this entry belongs to
            entry_date = datetime.strptime(date_str, "%Y-%m-%d")
            
            if entry_date <= week1_end:
                # Week 1 entry
                last_week1_entry = (date_str, hours_week)
            else:
                # Week 2 entry
                last_week2_entry = (date_str, hours_week)
        
        # Use the last hours_week value from each week
        if last_week1_entry:
            week1_hours = last_week1_entry[1]
            
        if last_week2_entry:
            week2_hours = last_week2_entry[1]
        
        # Total for pay period
        total_hours = week1_hours + week2_hours
        
        # Calculate regular vs overtime
        regular_hours = min(total_hours, 80)
        overtime_hours = max(0, total_hours - 80)
        
        return {
            "period_start": period["start"],
            "period_end": period["end"],
            "days_remaining": period["days_remaining"],
            "total_hours": total_hours,
            "week1_hours": week1_hours,
            "week2_hours": week2_hours,
            "daily_sum": daily_sum,
            "discrepancy": total_hours - daily_sum,
            "regular_hours": regular_hours,
            "overtime_hours": overtime_hours,
            "daily_breakdown": daily_breakdown,
            "days_worked": len(daily_breakdown)
        }


def get_current_pay_period_info(date=None):
    """Get current pay period status with weekly totals properly handled"""
    period = get_pay_period_dates(date)
    hours_data = get_pay_period_hours(date)
    
    # Determine which week we're in
    current_date = datetime.strptime(date or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
    period_start = datetime.strptime(period["start"], "%Y-%m-%d")
    days_into_period = (current_date - period_start).days + 1
    current_week = 1 if days_into_period <= 7 else 2
    
    info = {
        "period_start": period["start"],
        "period_end": period["end"],
        "current_day": days_into_period,
        "current_week": current_week,
        "hours_logged": hours_data["total_hours"],
        "week1_hours": hours_data["week1_hours"],
        "week2_hours": hours_data["week2_hours"],
        "days_worked": hours_data["days_worked"],
        "remaining_work_days": 0,
        "avg_hours_needed": 0
    }
    
    # Calculate remaining work days (exclude Mondays)
    remaining_days = []
    current = current_date + timedelta(days=1)
    end = datetime.strptime(period["end"], "%Y-%m-%d")
    
    while current <= end:
        if current.weekday() != 0:  # Not Monday
            remaining_days.append(current)
        current += timedelta(days=1)
    
    info["remaining_work_days"] = len(remaining_days)
    
    # Calculate hours needed per day
    if info["remaining_work_days"] > 0:
        hours_still_needed = max(0, 80 - info["hours_logged"])
        info["avg_hours_needed"] = round(hours_still_needed / info["remaining_work_days"], 1)
    
    return info


def get_pay_period_detail(date=None):
    """Get detailed daily hours for the pay period"""
    period = get_pay_period_dates(date)
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        
        # Get all daily entries in this pay period
        cursor.execute("""
            SELECT date, hours_today
            FROM hours
            WHERE date >= ? AND date <= ?
            ORDER BY date
        """, (period["start"], period["end"]))
        
        daily_hours = []
        total_hours = 0
        
        for row in cursor.fetchall():
            date, hours = row
            daily_hours.append({
                "date": date,
                "hours": hours
            })
            total_hours += hours
        
        return {
            "period_start": period["start"],
            "period_end": period["end"],
            "daily_hours": daily_hours,
            "total_hours": total_hours,
            "days_worked": len(daily_hours)
        }


def get_pay_history(num_periods=3):
    """Get pay period history with weekly breakdown"""
    results = []
    
    # Start from current period and work backwards
    current_period = get_pay_period_dates()
    check_date = datetime.strptime(current_period["start"], "%Y-%m-%d")
    
    for i in range(num_periods):
        # Calculate the date for this historical period
        period_date = (check_date - timedelta(days=14 * i)).strftime("%Y-%m-%d")
        
        # Get the data for this pay period
        period_data = get_pay_period_hours(period_date)
        period_info = get_pay_period_dates(period_date)
        
        # Add to results
        results.append({
            "period_start": period_info["start"],
            "period_end": period_info["end"],
            "total_hours": period_data["total_hours"],
            "week1_hours": period_data["week1_hours"],
            "week2_hours": period_data["week2_hours"],
            "regular_hours": period_data["regular_hours"],
            "overtime_hours": period_data["overtime_hours"],
            "days_worked": period_data["days_worked"]
        })
    
    return results


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