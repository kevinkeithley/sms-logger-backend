# SMS Logger Backend

Backend service for processing and storing SMS-based logging data for mileage and hours tracking.

## Overview

This service receives parsed SMS data from the [sms-logger](https://github.com/kevinkeithley/sms-logger) ingester via Tailscale and:
- Stores raw mileage entries (start/mid/end odometer readings)
- Calculates daily mileage totals
- Tracks hours worked with weekly totals
- Maintains all data in a local SQLite database

## Features

- **Flask API** for receiving log entries
- **SQLite database** for local storage
- **Automatic mileage calculation** from odometer readings
- **Pay period tracking** for hours worked
- **Eastern timezone** awareness for all timestamps

## Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/kevinkeithley/sms-logger-backend.git
   cd sms-logger-backend
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Initialize the database**
   ```bash
   python process_logfile.py
   ```
   This creates `business_tracking.db` with the necessary tables.

5. **Run the logger service**
   ```bash
   python logger.py
   ```
   The service will start on port 10000.

## API Endpoints

### POST /log
Receives and stores log entries.

**Request body:**
```json
{
  "type": "mileage",
  "date": "2025-06-07",
  "name": "Kevin",
  "position": "start",
  "distance": 100.5
}
```

**Response:**
```json
{
  "status": "logged",
  "message": "Entry saved"
}
```

## Data Processing

Run `process_logfile.py` to:
1. Read entries from `logfile.txt`
2. Insert mileage entries into `mileage_raw` table
3. Calculate daily totals and update `mileage_summary` table
4. Store hours entries in `hours` table
5. Clear the logfile after successful processing

```bash
python process_logfile.py
```

## Database Schema

- **mileage_raw**: Stores individual odometer readings
- **mileage_summary**: Stores calculated daily mileage totals
- **hours**: Stores daily hours worked with weekly totals

See `schema.sql` for complete structure.

## Integration with SMS Logger

This backend is designed to work with the SMS ingester running on Fly.io:
1. User sends SMS to Twilio number
2. Ingester parses the message
3. Ingester forwards valid entries to this backend via Tailscale
4. Backend stores data and responds with confirmation

### Tailscale Funnel Setup

To expose this service via Tailscale Funnel:

1. **Enable Tailscale Funnel** (if not already enabled):
   ```bash
   tailscale funnel 10000
   ```

2. **Run the funnel** to expose port 10000:
   ```bash
   tailscale funnel 10000
   ```

3. **Get your funnel URL**:
   ```bash
   tailscale funnel status
   ```
   This will show something like: `https://your-machine-name.ts.net`

4. **Configure the SMS ingester** with your Tailscale URL:
   ```
   TAILSCALE_LOGGER_URL=https://your-machine-name.ts.net/log
   ```

Note: Tailscale Funnel provides a secure HTTPS endpoint without needing to open firewall ports or configure certificates.

## Environment Variables

Create a `.env` file (see `.env.example`):
```
# Currently no required environment variables
# Future: PORT, DATABASE_PATH, etc.
```

License
MIT License - see LICENSE file for details
