# config.py
import os
from pathlib import Path

# Determine if we're running in Docker
IN_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER", False)

# Set paths based on environment
if IN_DOCKER:
    DB_FILE = "/app/data/business_tracking.db"
    LOGFILE = "/app/logfile.txt"
else:
    DB_FILE = "business_tracking.db"
    LOGFILE = "logfile.txt"

# Ensure data directory exists
if IN_DOCKER:
    Path("/app/data").mkdir(parents=True, exist_ok=True)

# Other configuration
SCHEMA = "schema.sql"
PAY_PERIOD_START = os.environ.get("PAY_PERIOD_START", "2025-05-19")
