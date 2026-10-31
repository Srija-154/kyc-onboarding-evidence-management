from pathlib import Path
import os
import sqlite3

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

DB_PATH = Path(
    os.environ.get(
        "KYC_DB_PATH",
        str(DATA_DIR / "kyc.db")
    )
)

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customer_types (
    customer_type_id INTEGER PRIMARY KEY,
    type_name TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    customer_type_id INTEGER NOT NULL,
    date_of_birth TEXT,
    registration_date TEXT NOT NULL,
    country TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN
      ('ONBOARDING','PENDING_REVIEW','APPROVED','REJECTED','SUSPENDED')),
    FOREIGN KEY(customer_type_id) REFERENCES customer_types(customer_type_id)
);

CREATE TABLE IF NOT EXISTS kyc_requirements (
    requirement_id TEXT PRIMARY KEY,
    customer_type_id INTEGER NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN ('LOW','MEDIUM','HIGH')),
    document_type TEXT NOT NULL,
    mandatory INTEGER NOT NULL CHECK(mandatory IN (0,1)),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    UNIQUE(customer_type_id, risk_level, document_type, effective_from),
    FOREIGN KEY(customer_type_id) REFERENCES customer_types(customer_type_id)
);

CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    issue_date TEXT NOT NULL,
    expiry_date TEXT,
    document_reference TEXT NOT NULL,
    holder_name TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL CHECK(lifecycle_status IN
      ('SUBMITTED','UNDER_REVIEW','VERIFIED','REJECTED','EXPIRED')),
    issue_type TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS verifications (
    verification_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK(verification_status IN
      ('PENDING','VERIFIED','REJECTED','MISMATCH')),
    verified_by TEXT,
    verification_date TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY(document_id) REFERENCES documents(document_id)
);

CREATE TABLE IF NOT EXISTS risk_ratings (
    risk_rating_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    risk_level TEXT NOT NULL CHECK(risk_level IN ('LOW','MEDIUM','HIGH')),
    risk_score INTEGER NOT NULL CHECK(risk_score BETWEEN 0 AND 100),
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    reason TEXT,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS review_cases (
    review_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    due_date TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK(review_status IN
      ('SCHEDULED','IN_PROGRESS','COMPLETED','OVERDUE','CLOSED')),
    resolution TEXT,
    closed_at TEXT,
    issue_type TEXT,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS beneficial_owners (
    owner_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    ownership_percentage REAL NOT NULL CHECK(ownership_percentage >= 0 AND ownership_percentage <= 100),
    is_verified INTEGER NOT NULL DEFAULT 0 CHECK(is_verified IN (0,1)),
    effective_from TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    document_id TEXT,
    alert_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,
    alert_status TEXT NOT NULL CHECK(alert_status IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id),
    FOREIGN KEY(document_id) REFERENCES documents(document_id)
);

CREATE TABLE IF NOT EXISTS audit_events (
    audit_event_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL,
    event_timestamp TEXT NOT NULL,
    FOREIGN KEY(customer_id) REFERENCES customers(customer_id)
);

CREATE INDEX IF NOT EXISTS idx_documents_customer ON documents(customer_id);
CREATE INDEX IF NOT EXISTS idx_reviews_customer ON review_cases(customer_id);
CREATE INDEX IF NOT EXISTS idx_alerts_status ON alerts(alert_status);
CREATE INDEX IF NOT EXISTS idx_risk_customer ON risk_ratings(customer_id);
"""

def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize_database():
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()