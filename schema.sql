-- schema.sql
-- Business tracking database schema

-- Mileage tracking tables
CREATE TABLE IF NOT EXISTS mileage_raw (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    position TEXT NOT NULL CHECK(position IN ('start', 'mid', 'end')),
    distance REAL NOT NULL,
    received_at TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mileage_summary (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    date TEXT NOT NULL,
    total_miles REAL NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(name, date)
);

-- Hours tracking tables
CREATE TABLE IF NOT EXISTS hours (
    id TEXT PRIMARY KEY,
    date TEXT NOT NULL,
    hours_today REAL NOT NULL,
    hours_week REAL NOT NULL,
    received_at TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(date)
);

-- Optional: Pay period summary table for faster queries
CREATE TABLE IF NOT EXISTS pay_period_summary (
    id TEXT PRIMARY KEY,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    total_hours REAL NOT NULL,
    regular_hours REAL NOT NULL,
    overtime_hours REAL NOT NULL,
    days_worked INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(period_start, period_end)
);

-- Create indices for better query performance
CREATE INDEX IF NOT EXISTS idx_mileage_raw_date ON mileage_raw(date);
CREATE INDEX IF NOT EXISTS idx_mileage_raw_name_date ON mileage_raw(name, date);
CREATE INDEX IF NOT EXISTS idx_hours_date ON hours(date);
CREATE INDEX IF NOT EXISTS idx_mileage_summary_date ON mileage_summary(date);

-- Create a view for easy mileage querying
CREATE VIEW IF NOT EXISTS mileage_daily AS
SELECT 
    ms.date,
    ms.name,
    ms.total_miles,
    COUNT(mr.id) as num_entries,
    MIN(CASE WHEN mr.position = 'start' THEN mr.distance END) as start_reading,
    MAX(CASE WHEN mr.position = 'end' THEN mr.distance END) as end_reading
FROM mileage_summary ms
LEFT JOIN mileage_raw mr ON ms.name = mr.name AND ms.date = mr.date
GROUP BY ms.date, ms.name;