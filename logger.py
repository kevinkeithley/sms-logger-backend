# logger.py
from flask import Flask, request, jsonify
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from config import LOGFILE  # Import from config
from process_logfile import (
    get_summary_data,
    get_hours_data,
    get_pay_period_hours,
    get_current_pay_period_info,
    get_pay_period_detail,  # Add this import
    process_all,
)

EASTERN = ZoneInfo("America/New_York")
app = Flask(__name__)


@app.route("/log", methods=["POST"])
def log_entry():
    """Log SMS entries to file"""
    data = request.get_json()
    if data.get("type") not in ("mileage", "hours"):
        return jsonify({"status": "ignored", "message": "Unsupported log type"}), 200

    # Add timestamp
    data["received_at"] = datetime.now(EASTERN).isoformat()

    with open(LOGFILE, "a") as f:
        f.write(json.dumps(data) + "\n")

    print(f"📥 Logged: {data}")
    return jsonify({"status": "logged", "message": "Entry saved"}), 200


@app.route("/query", methods=["POST"])
def query_data():
    """Handle various query types for SMS responses"""
    data = request.get_json()
    query_type = data.get("type")

    try:
        if query_type == "pay_status":
            info = get_current_pay_period_info()
            response = (
                f"Pay Period: {info['period_start']} - {info['period_end']}\n"
                f"Day {info['current_day']} of 14 (Week {info['current_week']})\n"
                f"Hours: {info['hours_logged']:.1f} (W1: {info['week1_hours']:.1f}, W2: {info['week2_hours']:.1f})\n"
            )
            
            response += f"Work days left: {info['remaining_work_days']}\n"

            if info["avg_hours_needed"] > 0:
                response += f"Need {info['avg_hours_needed']:.1f} hrs/day for 80 total"

        elif query_type == "pay_detail":
            # New PAYDETAIL function - replaces pay_period
            result = get_pay_period_detail()
            response = f"Pay Period: {result['period_start']} - {result['period_end']}\n"
            
            if result['daily_hours']:
                for entry in result['daily_hours']:
                    response += f"{entry['date']}: {entry['hours']:.1f} hrs\n"
                response += f"Total: {result['total_hours']:.1f} hrs ({result['days_worked']} days)"
            else:
                response = "No hours logged this pay period"

        elif query_type == "hours_check":
            # Validate hours with bi-weekly handling
            result = get_pay_period_hours()
            if abs(result["discrepancy"]) < 0.1:
                response = "✅ Hours match! No discrepancies found."
            else:
                response = (
                    f"Pay period total: {result['total_hours']:.1f}hrs\n"
                    f"Week 1: {result['week1_hours']:.1f}hrs\n"
                    f"Week 2: {result['week2_hours']:.1f}hrs\n"
                    f"Daily sum: {result['daily_sum']:.1f}hrs\n"
                    f"Difference: {result['discrepancy']:+.1f}hrs"
                )

        elif query_type == "mileage_summary":
            # Get recent mileage
            results = get_summary_data(
                name=data.get("name"), date=data.get("date"), days=data.get("days", 7)
            )
            if results:
                if data.get("name"):
                    response = f"Mileage for {data.get('name')}:\n"
                else:
                    response = "Recent mileage:\n"

                for r in results[:5]:  # Limit for SMS
                    response += f"{r['date']}: {r['name']} - {r['miles']:.1f}mi\n"

                total = sum(r["miles"] for r in results)
                response += f"Total: {total:.1f}mi"
            else:
                response = "No mileage data found"

        elif query_type == "mileage_today":
            # Today's mileage
            today = datetime.now().strftime("%Y-%m-%d")
            results = get_summary_data(date=today)
            if results:
                response = "Today's mileage:\n"
                for r in results:
                    response += f"{r['name']}: {r['miles']:.1f}mi\n"
            else:
                response = "No mileage logged today"

        elif query_type == "hours_week":
            # This week's hours
            results = get_hours_data(days=7)
            if results:
                response = "This week's hours:\n"
                total = 0
                for r in results[:7]:
                    response += f"{r['date']}: {r['hours_today']:.1f}hrs\n"
                    total += r["hours_today"]
                response += f"Week total: {total:.1f}hrs"
            else:
                response = "No hours data found"

        else:
            response = "Unknown query type. Try: PAYSTATUS, PAYDETAIL, HOURSCHECK, MILES"

        return jsonify({"status": "success", "message": response}), 200

    except Exception as e:
        print(f"Query error: {e}")
        return jsonify({"status": "error", "message": "Error processing query"}), 500


@app.route("/process", methods=["POST"])
def trigger_processing():
    """Manually trigger processing of logfile"""
    try:
        result = process_all()
        return jsonify({"status": "success", "processed": result}), 200
    except Exception as e:
        print(f"Processing error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    return jsonify({"status": "healthy"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)