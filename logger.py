# logger.py
from flask import Flask, request, jsonify
import json
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

app = Flask(__name__)

LOGFILE = "logfile.txt"


@app.route("/log", methods=["POST"])
def log_entry():
    data = request.get_json()

    if data.get("type") not in ("mileage", "hours"):
        return jsonify({"status": "ignored", "message": "Unsupported log type"}), 200

    # Add timestamp
    data["received_at"] = datetime.now(EASTERN).isoformat()

    with open("logfile.txt", "a") as f:
        f.write(json.dumps(data) + "\n")

    print(f"📥 Logged: {data}")
    return jsonify({"status": "logged", "message": "Entry saved"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
