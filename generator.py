
import argparse
import hashlib
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from faker import Faker

from database import BASE_DIR, DB_PATH, SCHEMA


SEED = 20261022
TODAY = date(2026, 10, 31)

DATASET_DIR = BASE_DIR / "datasets"
REPORT_DIR = BASE_DIR / "reports"

DOC_TYPES = [
    "PAN",
    "IDENTITY_PROOF",
    "ADDRESS_PROOF",
    "PASSPORT",
    "BUSINESS_REGISTRATION",
    "TAX_CERTIFICATE",
]

REQUIREMENTS = {
    ("INDIVIDUAL", "LOW"): [
        "PAN", "IDENTITY_PROOF", "ADDRESS_PROOF"
    ],
    ("INDIVIDUAL", "MEDIUM"): [
        "PAN", "IDENTITY_PROOF", "ADDRESS_PROOF", "PASSPORT"
    ],
    ("INDIVIDUAL", "HIGH"): [
        "PAN", "IDENTITY_PROOF", "ADDRESS_PROOF",
        "PASSPORT", "TAX_CERTIFICATE"
    ],
    ("BUSINESS", "LOW"): [
        "PAN", "BUSINESS_REGISTRATION", "ADDRESS_PROOF"
    ],
    ("BUSINESS", "MEDIUM"): [
        "PAN", "BUSINESS_REGISTRATION",
        "ADDRESS_PROOF", "TAX_CERTIFICATE"
    ],
    ("BUSINESS", "HIGH"): [
        "PAN", "BUSINESS_REGISTRATION",
        "ADDRESS_PROOF", "TAX_CERTIFICATE",
        "IDENTITY_PROOF"
    ],
}


def daterange(rng, start_days=-1800, end_days=0):
    """Return a reproducible date relative to the fixed demonstration date."""
    return TODAY + timedelta(days=rng.randint(start_days, end_days))


def sha256_file(path):
    """Return the SHA-256 checksum of a file."""
    digest = hashlib.sha256()

    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()


def export_table(conn, table, output_dir):
    """Export a database table as CSV and JSON."""
    df = pd.read_sql_query(f"SELECT * FROM {table}", conn)

    csv_path = output_dir / f"{table}.csv"
    json_path = output_dir / f"{table}.json"

    df.to_csv(csv_path, index=False)
    df.to_json(
        json_path,
        orient="records",
        indent=2,
        date_format="iso",
    )

    return len(df)


def get_latest_verified_document_types(conn, customer_id):
    """
    Return document types whose latest verification is VERIFIED
    and whose document is not expired.
    """
    rows = conn.execute(
        """
        WITH latest_verification AS (
            SELECT
                document_id,
                verification_status,
                ROW_NUMBER() OVER (
                    PARTITION BY document_id
                    ORDER BY verification_date DESC, verification_id DESC
                ) AS row_num
            FROM verifications
        )
        SELECT DISTINCT d.document_type
        FROM documents d
        JOIN latest_verification lv
            ON lv.document_id = d.document_id
           AND lv.row_num = 1
        WHERE d.customer_id = ?
          AND d.lifecycle_status = 'VERIFIED'
          AND lv.verification_status = 'VERIFIED'
          AND (
              d.expiry_date IS NULL
              OR d.expiry_date >= ?
          )
        """,
        (customer_id, TODAY.isoformat()),
    ).fetchall()

    return {row[0] for row in rows}


def calculate_customer_completeness(conn, customer_id, customer_risks):
    """Calculate KYC completeness from source records."""
    risk, _, customer_type = customer_risks[customer_id]
    required_docs = REQUIREMENTS[(customer_type, risk)]

    verified_types = get_latest_verified_document_types(
        conn, customer_id
    )

    satisfied = sum(
        1 for doc_type in required_docs
        if doc_type in verified_types
    )

    required_count = len(required_docs)
    percentage = (
        round((satisfied / required_count) * 100, 2)
        if required_count
        else 100.0
    )

    return {
        "customer_id": customer_id,
        "required_count": required_count,
        "satisfied_count": satisfied,
        "completeness_pct": percentage,
        "kyc_complete": percentage == 100.0,
    }


def write_audit_event(
    cur,
    event_number,
    customer_id,
    entity_type,
    entity_id,
    action,
    old_value,
    new_value,
):
    """Insert an explicit audit event for a generated state change."""
    cur.execute(
        """
        INSERT INTO audit_events (
            audit_event_id,
            customer_id,
            entity_type,
            entity_id,
            action,
            old_value,
            new_value,
            actor,
            event_timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"AUD-{event_number:08d}",
            customer_id,
            entity_type,
            entity_id,
            action,
            old_value,
            new_value,
            "SYSTEM_GENERATOR",
            TODAY.isoformat(),
        ),
    )


def generate_data(
    customer_count=8000,
    document_count=20000,
    business_count=1000,
    review_count=3000,
    seed=SEED,
    confirm_replace=False,
    db_path=None,
    dataset_dir=None,
    report_dir=None,
):
    """
    Generate the synthetic KYC dataset.

    Existing database records are replaced only when
    confirm_replace=True is explicitly supplied.
    """

    if not confirm_replace:
        raise RuntimeError(
            "Generation stopped to protect the existing database. "
            "After reviewing the code and backup, run with "
            "--confirm-replace to replace existing generated records."
        )

    if customer_count < 1:
        raise ValueError("Customer count must be at least 1.")

    if business_count < 0 or business_count > customer_count:
        raise ValueError(
            "Business count must be between 0 and customer count."
        )

    if document_count < customer_count:
        raise ValueError(
            "Document count must be at least the customer count."
        )

    if review_count < 0:
        raise ValueError("Review count cannot be negative.")

    rng = random.Random(seed)

    fake = Faker()
    fake.seed_instance(seed)

    # Allow testing with isolated database and export directories.
    active_db_path = Path(db_path) if db_path else DB_PATH
    active_dataset_dir = (
        Path(dataset_dir) if dataset_dir else DATASET_DIR
    )
    active_report_dir = (
        Path(report_dir) if report_dir else REPORT_DIR
    )

    active_db_path.parent.mkdir(parents=True, exist_ok=True)
    active_dataset_dir.mkdir(parents=True, exist_ok=True)
    active_report_dir.mkdir(parents=True, exist_ok=True)

    # Create/open only the selected database.
    conn = sqlite3.connect(active_db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        # Create schema before starting the data transaction.
        conn.executescript(SCHEMA)
        conn.execute("BEGIN IMMEDIATE")

        cur = conn.cursor()

        # ---------------------------------------------------------
        # 1. Clear existing generated data.
        # ---------------------------------------------------------
        for table in [
            "audit_events",
            "alerts",
            "beneficial_owners",
            "review_cases",
            "risk_ratings",
            "verifications",
            "documents",
            "kyc_requirements",
            "customers",
            "customer_types",
        ]:
            cur.execute(f"DELETE FROM {table}")

        # ---------------------------------------------------------
        # 2. Master data: customer types.
        # ---------------------------------------------------------
        cur.executemany(
            """
            INSERT INTO customer_types (
                customer_type_id,
                type_name,
                description
            )
            VALUES (?, ?, ?)
            """,
            [
                (1, "INDIVIDUAL", "Natural person customer"),
                (2, "BUSINESS", "Legal entity or business customer"),
            ],
        )

        # ---------------------------------------------------------
        # 3. Master data: KYC requirements.
        # ---------------------------------------------------------
        requirement_rows = []
        requirement_number = 1

        for (customer_type, risk_level), document_types in REQUIREMENTS.items():
            type_id = 1 if customer_type == "INDIVIDUAL" else 2

            for document_type in document_types:
                requirement_rows.append(
                    (
                        f"KYC-2026-{requirement_number:06d}",
                        type_id,
                        risk_level,
                        document_type,
                        1,
                        "2026-01-01",
                        None,
                    )
                )
                requirement_number += 1

        cur.executemany(
            """
            INSERT INTO kyc_requirements (
                requirement_id,
                customer_type_id,
                risk_level,
                document_type,
                mandatory,
                effective_from,
                effective_to
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            requirement_rows,
        )

        # ---------------------------------------------------------
        # 4. Generate customers.
        # ---------------------------------------------------------
        customers = []
        customer_risks = {}

        for i in range(1, customer_count + 1):
            customer_id = f"CUS-{i:06d}"

            is_business = i <= business_count
            customer_type_id = 2 if is_business else 1
            customer_type = (
                "BUSINESS" if is_business else "INDIVIDUAL"
            )

            customer_name = (
                fake.company() if is_business else fake.name()
            )

            risk_level = rng.choices(
                ["LOW", "MEDIUM", "HIGH"],
                weights=[0.55, 0.30, 0.15],
            )[0]

            risk_score = {
                "LOW": rng.randint(0, 30),
                "MEDIUM": rng.randint(31, 65),
                "HIGH": rng.randint(66, 100),
            }[risk_level]

            registration_date = daterange(
                rng, -1500, 0
            ).isoformat()

            email = f"customer{i:06d}@example.test"

            initial_status = rng.choices(
                [
                    "ONBOARDING",
                    "PENDING_REVIEW",
                    "APPROVED",
                    "REJECTED",
                ],
                weights=[0.15, 0.20, 0.58, 0.07],
            )[0]

            date_of_birth = (
                daterange(rng, -20000, -5000).isoformat()
                if not is_business
                else None
            )

            customers.append(
                (
                    customer_id,
                    customer_name,
                    email,
                    customer_type_id,
                    date_of_birth,
                    registration_date,
                    "IN",
                    initial_status,
                )
            )

            customer_risks[customer_id] = (
                risk_level,
                risk_score,
                customer_type,
            )

        cur.executemany(
            """
            INSERT INTO customers (
                customer_id,
                full_name,
                email,
                customer_type_id,
                date_of_birth,
                registration_date,
                country,
                lifecycle_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            customers,
        )

        # ---------------------------------------------------------
        # 5. Generate risk ratings.
        # ---------------------------------------------------------
        risk_rows = []

        for i, (customer_id, risk_data) in enumerate(
            customer_risks.items(), start=1
        ):
            risk_level, risk_score, _ = risk_data

            risk_rows.append(
                (
                    f"RISK-{i:06d}",
                    customer_id,
                    risk_level,
                    risk_score,
                    "2026-01-01",
                    None,
                    "Synthetic rule-based risk score",
                )
            )

        cur.executemany(
            """
            INSERT INTO risk_ratings (
                risk_rating_id,
                customer_id,
                risk_level,
                risk_score,
                effective_from,
                effective_to,
                reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            risk_rows,
        )

        # ---------------------------------------------------------
        # 6. Distribute documents across customers.
        # ---------------------------------------------------------
        docs_per_customer = [1] * customer_count
        remaining_documents = document_count - customer_count

        for _ in range(remaining_documents):
            docs_per_customer[rng.randrange(customer_count)] += 1

        doc_rows = []
        verification_rows = []
        doc_counter_by_customer = {}
        global_doc_number = 1

        for idx, customer in enumerate(customers):
            customer_id = customer[0]
            customer_name = customer[1]

            risk_level, _, customer_type = customer_risks[
                customer_id
            ]

            required_docs = REQUIREMENTS[
                (customer_type, risk_level)
            ]

            for j in range(docs_per_customer[idx]):
                is_required_document = j < len(required_docs)

                if is_required_document:
                    document_type = required_docs[j]
                else:
                    document_type = rng.choice(DOC_TYPES)

                if is_required_document:
                   # Required baseline documents must be valid on the generation date.
                    issue_date = TODAY - timedelta(
                        days=rng.randint(1, 500)
                    )
                    expiry_date = TODAY + timedelta(
                        days=rng.randint(180, 1000)
                    )

                    holder_name = customer_name
                    verification_status = "VERIFIED"
                    lifecycle_status = "VERIFIED"
                    issue_type = None

                else:
                    expired = rng.random() < 0.13

                    if expired:
                        expiry_date = TODAY - timedelta(
                            days=rng.randint(1, 500)
                        )
                        issue_date = expiry_date - timedelta(
                            days=rng.randint(365, 3650)
                        )
                    else:
                        # Normal non-expired documents must remain valid on TODAY.
                        issue_date = TODAY - timedelta(
                            days=rng.randint(1, 500)
                        )
                        expiry_date = TODAY + timedelta(
                            days=rng.randint(180, 1000)
                        )

                    has_name_mismatch = rng.random() < 0.035

                    holder_name = (
                        fake.name()
                        if has_name_mismatch
                        else customer_name
                    )

                    if expired:
                        verification_status = rng.choice(
                            ["PENDING", "REJECTED"]
                        )
                        lifecycle_status = "EXPIRED"

                    elif has_name_mismatch:
                        verification_status = "MISMATCH"
                        lifecycle_status = "REJECTED"

                    else:
                        verification_status = rng.choices(
                            [
                                "VERIFIED",
                                "PENDING",
                                "REJECTED",
                                "MISMATCH",
                            ],
                            weights=[0.72, 0.15, 0.08, 0.05],
                        )[0]

                        lifecycle_status = (
                            "VERIFIED"
                            if verification_status == "VERIFIED"
                            else (
                                "REJECTED"
                                if verification_status in (
                                    "REJECTED",
                                    "MISMATCH",
                                )
                                else "SUBMITTED"
                            )
                        )

                    issue_type = (
                        "NAME_MISMATCH"
                        if has_name_mismatch
                        else None
                    )

                doc_counter_by_customer[customer_id] = (
                    doc_counter_by_customer.get(customer_id, 0) + 1
                )

                document_id = (
                    f"DOC-{customer_id}-"
                    f"{doc_counter_by_customer[customer_id]:03d}"
                )

                document_reference = (
                    f"REF-{rng.getrandbits(48):012X}"
                )

                doc_rows.append(
                    (
                        document_id,
                        customer_id,
                        document_type,
                        issue_date.isoformat(),
                        expiry_date.isoformat(),
                        document_reference,
                        holder_name,
                        lifecycle_status,
                        issue_type,
                        TODAY.isoformat(),
                    )
                )

                verification_rows.append(
                    (
                        f"VER-{global_doc_number:07d}",
                        document_id,
                        verification_status,
                        "SYSTEM_REVIEWER",
                        TODAY.isoformat(),
                        "Synthetic verification result",
                    )
                )

                global_doc_number += 1

        cur.executemany(
            """
            INSERT INTO documents (
                document_id,
                customer_id,
                document_type,
                issue_date,
                expiry_date,
                document_reference,
                holder_name,
                lifecycle_status,
                issue_type,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            doc_rows,
        )

        cur.executemany(
            """
            INSERT INTO verifications (
                verification_id,
                document_id,
                verification_status,
                verified_by,
                verification_date,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            verification_rows,
        )

        # ---------------------------------------------------------
        # 7. Reconcile customer approval against actual evidence.
        # ---------------------------------------------------------
        approval_adjustments = []

        for customer in customers:
            customer_id = customer[0]
            original_status = customer[7]

            if original_status != "APPROVED":
                continue

            completeness = calculate_customer_completeness(
                conn,
                customer_id,
                customer_risks,
            )

            if not completeness["kyc_complete"]:
                cur.execute(
                    """
                    UPDATE customers
                    SET lifecycle_status = 'PENDING_REVIEW'
                    WHERE customer_id = ?
                    """,
                    (customer_id,),
                )

                approval_adjustments.append(customer_id)

        # ---------------------------------------------------------
        # 8. Generate beneficial owners.
        # ---------------------------------------------------------
        owner_rows = []
        owner_counter = 1

        business_ids = [
            customer[0]
            for customer in customers[:business_count]
        ]

        for customer_id in business_ids:
            if rng.random() < 0.025:
                continue

            owner_count = rng.randint(1, 3)
            remaining_percentage = 100.0

            for owner_index in range(owner_count):
                if owner_index == owner_count - 1:
                    percentage = remaining_percentage
                else:
                    max_percentage = (
                        remaining_percentage
                        / max(1, owner_count - owner_index)
                    )

                    percentage = round(
                        rng.uniform(10, max(10, max_percentage)),
                        2,
                    )

                    percentage = min(
                        percentage,
                        remaining_percentage,
                    )

                percentage = max(0.1, percentage)

                remaining_percentage = round(
                    remaining_percentage - percentage,
                    2,
                )

                owner_rows.append(
                    (
                        f"OWN-{owner_counter:07d}",
                        customer_id,
                        fake.name(),
                        percentage,
                        1 if rng.random() > 0.1 else 0,
                        "2026-01-01",
                    )
                )

                owner_counter += 1

        # Deliberate ownership anomaly.
        anomaly_business = None

        if business_ids:
            anomaly_business = business_ids[-1]

            owner_rows = [
                row
                for row in owner_rows
                if row[1] != anomaly_business
            ]

            owner_rows.extend(
                [
                    (
                        f"OWN-{owner_counter:07d}",
                        anomaly_business,
                        "Synthetic Owner A",
                        60.0,
                        1,
                        "2026-01-01",
                    ),
                    (
                        f"OWN-{owner_counter + 1:07d}",
                        anomaly_business,
                        "Synthetic Owner B",
                        50.0,
                        1,
                        "2026-01-01",
                    ),
                ]
            )

        if owner_rows:
            cur.executemany(
                """
                INSERT INTO beneficial_owners (
                    owner_id,
                    customer_id,
                    owner_name,
                    ownership_percentage,
                    is_verified,
                    effective_from
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                owner_rows,
            )

        # ---------------------------------------------------------
        # 9. Generate review cases.
        # ---------------------------------------------------------
        review_rows = []

        for i in range(1, review_count + 1):
            customer_index = (i - 1) % customer_count
            customer_id = customers[customer_index][0]

            scheduled_date = daterange(rng, -500, 200)
            due_date = scheduled_date + timedelta(days=30)

            if due_date < TODAY:
                review_status = "OVERDUE"
            else:
                review_status = rng.choice(
                    ["SCHEDULED", "IN_PROGRESS", "COMPLETED"]
                )

            resolution = (
                "Evidence reviewed"
                if review_status == "COMPLETED"
                else None
            )

            closed_at = (
                TODAY.isoformat()
                if review_status == "COMPLETED"
                else None
            )

            review_rows.append(
                (
                    f"REV-{customer_id}-2026-{i:04d}",
                    customer_id,
                    scheduled_date.isoformat(),
                    due_date.isoformat(),
                    review_status,
                    resolution,
                    closed_at,
                    None,
                )
            )

        # Deliberate unresolved closure anomaly.
        if review_rows:
            first_review = list(review_rows[0])
            first_review[4] = "CLOSED"
            first_review[5] = None
            first_review[6] = TODAY.isoformat()
            first_review[7] = "CLOSED_WITHOUT_RESOLUTION"
            review_rows[0] = tuple(first_review)

        if review_rows:
            cur.executemany(
                """
                INSERT INTO review_cases (
                    review_id,
                    customer_id,
                    scheduled_date,
                    due_date,
                    review_status,
                    resolution,
                    closed_at,
                    issue_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                review_rows,
            )

        # ---------------------------------------------------------
        # 10. Generate expiry alerts.
        # ---------------------------------------------------------
        alert_rows = []
        alert_number = 1

        for document in doc_rows:
            (
                document_id,
                customer_id,
                document_type,
                issue_date,
                expiry_date,
                _,
                _,
                _,
                _,
                _,
            ) = document

            expiry = date.fromisoformat(expiry_date)
            days_left = (expiry - TODAY).days

            if days_left < 0:
                alert_rows.append(
                    (
                        f"ALT-2026-{alert_number:06d}",
                        customer_id,
                        document_id,
                        "DOCUMENT_EXPIRED",
                        "HIGH",
                        f"{document_type} expired {-days_left} days ago",
                        TODAY.isoformat(),
                        "OPEN",
                    )
                )
                alert_number += 1

            elif days_left <= 30:
                alert_rows.append(
                    (
                        f"ALT-2026-{alert_number:06d}",
                        customer_id,
                        document_id,
                        "DOCUMENT_EXPIRING",
                        "MEDIUM",
                        f"{document_type} expires in {days_left} days",
                        TODAY.isoformat(),
                        "OPEN",
                    )
                )
                alert_number += 1

        if alert_rows:
            cur.executemany(
                """
                INSERT INTO alerts (
                    alert_id,
                    customer_id,
                    document_id,
                    alert_type,
                    severity,
                    message,
                    created_at,
                    alert_status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                alert_rows,
            )

        # ---------------------------------------------------------
        # 11. Generate initial audit history.
        # ---------------------------------------------------------
        audit_number = 1

        for customer in customers:
            write_audit_event(
                cur,
                audit_number,
                customer[0],
                "CUSTOMER",
                customer[0],
                "CUSTOMER_CREATED",
                None,
                customer[7],
            )
            audit_number += 1

        for document in doc_rows:
            write_audit_event(
                cur,
                audit_number,
                document[1],
                "DOCUMENT",
                document[0],
                "DOCUMENT_CREATED",
                None,
                document[7],
            )
            audit_number += 1

        for customer_id in approval_adjustments:
            write_audit_event(
                cur,
                audit_number,
                customer_id,
                "CUSTOMER",
                customer_id,
                "APPROVAL_STATUS_ADJUSTED",
                "APPROVED",
                "PENDING_REVIEW",
            )
            audit_number += 1

        # ---------------------------------------------------------
        # 12. Inject deliberate, labelled anomalies.
        # ---------------------------------------------------------
        ground_truth = []

        def label(
            record_id,
            customer_id,
            issue,
            expected_decision,
            description,
        ):
            ground_truth.append(
                {
                    "record_id": record_id,
                    "customer_id": customer_id,
                    "issue_type": issue,
                    "expected_decision": expected_decision,
                    "description": description,
                }
            )

        # Anomaly 1: expired document marked as verified.
        expired_document = next(
            (
                document
                for document in doc_rows
                if date.fromisoformat(document[4]) < TODAY
            ),
            None,
        )

        if expired_document:
            document_id = expired_document[0]
            customer_id = expired_document[1]

            cur.execute(
                """
                UPDATE documents
                SET lifecycle_status = 'VERIFIED',
                    issue_type = 'EXPIRED_MARKED_VALID'
                WHERE document_id = ?
                """,
                (document_id,),
            )

            cur.execute(
                """
                UPDATE verifications
                SET verification_status = 'VERIFIED'
                WHERE document_id = ?
                """,
                (document_id,),
            )

            label(
                document_id,
                customer_id,
                "EXPIRED_MARKED_VALID",
                "FLAG",
                "Document expiry date is in the past but status is verified.",
            )

            write_audit_event(
                cur,
                audit_number,
                customer_id,
                "DOCUMENT",
                document_id,
                "EXPIRED_DOCUMENT_MARKED_VERIFIED",
                "EXPIRED",
                "VERIFIED",
            )
            audit_number += 1

        # Anomaly 2: approved customer missing mandatory PAN evidence.
        approved_customer_id = None

        for customer in customers:
            customer_id = customer[0]

            if customer[7] != "APPROVED":
                continue

            if customer_id in business_ids:
                continue

            completeness = calculate_customer_completeness(
                conn,
                customer_id,
                customer_risks,
            )

            if completeness["kyc_complete"]:
                approved_customer_id = customer_id
                break

        if approved_customer_id:
            cur.execute(
                """
                UPDATE documents
                SET document_type = 'OTHER',
                    issue_type = 'MANDATORY_EVIDENCE_MISSING'
                WHERE customer_id = ?
                  AND document_type = 'PAN'
                """,
                (approved_customer_id,),
            )

            label(
                approved_customer_id,
                approved_customer_id,
                "APPROVED_WITH_MISSING_EVIDENCE",
                "FLAG",
                "Approved customer has no PAN evidence.",
            )

            write_audit_event(
                cur,
                audit_number,
                approved_customer_id,
                "CUSTOMER",
                approved_customer_id,
                "MANDATORY_EVIDENCE_EXCEPTION_INJECTED",
                "KYC_COMPLETE",
                "PAN_EVIDENCE_MISSING",
            )
            audit_number += 1

        # Anomaly 3: beneficial ownership exceeds 100 percent.
        if anomaly_business:
            label(
                anomaly_business,
                anomaly_business,
                "OWNERSHIP_OVER_100",
                "FLAG",
                "Beneficial ownership total is 110 percent.",
            )

            write_audit_event(
                cur,
                audit_number,
                anomaly_business,
                "BENEFICIAL_OWNER",
                anomaly_business,
                "OWNERSHIP_EXCEPTION_INJECTED",
                "100_PERCENT",
                "110_PERCENT",
            )
            audit_number += 1

        # Anomaly 4: review closed without a resolution.
        if review_rows:
            first_review = review_rows[0]

            label(
                first_review[0],
                first_review[1],
                "CLOSED_WITHOUT_RESOLUTION",
                "FLAG",
                "Review is closed but resolution is blank.",
            )

            write_audit_event(
                cur,
                audit_number,
                first_review[1],
                "REVIEW",
                first_review[0],
                "REVIEW_CLOSED_WITHOUT_RESOLUTION",
                "IN_PROGRESS",
                "CLOSED",
            )
            audit_number += 1

        # Anomaly 5: duplicate document reference across customers.
        if len(doc_rows) >= 2:
            first_document = doc_rows[0]

            second_document = next(
                (
                    document
                    for document in doc_rows[1:]
                    if document[1] != first_document[1]
                ),
                None,
            )

            if second_document:
                cur.execute(
                    """
                    UPDATE documents
                    SET document_reference = ?,
                        issue_type = 'DUPLICATE_DOCUMENT'
                    WHERE document_id = ?
                    """,
                    (
                        first_document[5],
                        second_document[0],
                    ),
                )

                cur.execute(
                    """
                    UPDATE documents
                    SET issue_type = 'DUPLICATE_DOCUMENT'
                    WHERE document_id = ?
                    """,
                    (first_document[0],),
                )

                label(
                    second_document[0],
                    second_document[1],
                    "DUPLICATE_DOCUMENT",
                    "INVESTIGATE",
                    "Document reference is reused by another customer.",
                )

                write_audit_event(
                    cur,
                    audit_number,
                    second_document[1],
                    "DOCUMENT",
                    second_document[0],
                    "DUPLICATE_DOCUMENT_REFERENCE_DETECTED",
                    second_document[5],
                    first_document[5],
                )
                audit_number += 1

        # ---------------------------------------------------------
        # 13. Export derived KYC completeness.
        # ---------------------------------------------------------
        completeness_rows = []

        for customer in customers:
            customer_id = customer[0]

            completeness = calculate_customer_completeness(
                conn,
                customer_id,
                customer_risks,
            )

            completeness_rows.append(completeness)

        completeness_path = (
            active_dataset_dir / "kyc_completeness.csv"
        )

        pd.DataFrame(completeness_rows).to_csv(
            completeness_path,
            index=False,
        )

        # ---------------------------------------------------------
        # 14. Export ground truth separately.
        # ---------------------------------------------------------
        ground_truth_path = (
            active_dataset_dir / "ground_truth.csv"
        )

        pd.DataFrame(ground_truth).to_csv(
            ground_truth_path,
            index=False,
        )

        ground_truth_json_path = (
            active_dataset_dir / "ground_truth.json"
        )

        ground_truth_json_path.write_text(
            json.dumps(ground_truth, indent=2),
            encoding="utf-8",
        )

        # ---------------------------------------------------------
        # 15. Export database tables.
        # ---------------------------------------------------------
        table_names = [
            "customer_types",
            "customers",
            "kyc_requirements",
            "documents",
            "verifications",
            "risk_ratings",
            "review_cases",
            "beneficial_owners",
            "alerts",
            "audit_events",
        ]

        row_counts = {}

        for table in table_names:
            row_counts[table] = export_table(
                conn,
                table,
                active_dataset_dir,
            )

        # ---------------------------------------------------------
        # 16. Export schema SQL.
        # ---------------------------------------------------------
        schema_rows = cur.execute(
            """
            SELECT sql
            FROM sqlite_master
            WHERE sql IS NOT NULL
              AND type IN ('table', 'index')
            ORDER BY type, name
            """
        ).fetchall()

        schema_path = active_dataset_dir / "schema.sql"

        schema_path.write_text(
            ";\n\n".join(
                row[0].rstrip(";")
                for row in schema_rows
                if row[0]
            ) + ";\n",
            encoding="utf-8",
        )

        # ---------------------------------------------------------
        # 17. Generate summary and checksums.
        # ---------------------------------------------------------
        generated_files = sorted(
            path
            for path in active_dataset_dir.iterdir()
            if path.is_file()
        )

        file_checksums = {
            path.name: sha256_file(path)
            for path in generated_files
        }

        summary = {
            "seed": seed,
            "generated_at": TODAY.isoformat(),
            "requested_volumes": {
                "customers": customer_count,
                "documents": document_count,
                "business_customers": business_count,
                "review_cases": review_count,
            },
            "actual_row_counts": row_counts,
            "approval_status_adjustments": len(
                approval_adjustments
            ),
            "ground_truth_cases": len(ground_truth),
            "generator": "generator.py",
            "database": str(active_db_path),
            "provenance": (
                "Fully synthetic data generated locally with Faker; "
                "no real customer data."
            ),
            "checksums": file_checksums,
        }

        summary_path = (
            active_report_dir / "generation_summary.json"
        )

        summary_path.write_text(
            json.dumps(summary, indent=2),
            encoding="utf-8",
        )

        # Commit only after the generation and exports succeed.
        conn.commit()

        print(json.dumps(summary, indent=2))

        return summary

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate synthetic KYC onboarding data."
    )

    parser.add_argument(
        "--customers",
        type=int,
        default=8000,
    )

    parser.add_argument(
        "--documents",
        type=int,
        default=20000,
    )

    parser.add_argument(
        "--businesses",
        type=int,
        default=1000,
    )

    parser.add_argument(
        "--reviews",
        type=int,
        default=3000,
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
    )

    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional database path for isolated testing.",
    )

    parser.add_argument(
        "--dataset-dir",
        type=str,
        default=None,
        help="Optional dataset export directory.",
    )

    parser.add_argument(
        "--report-dir",
        type=str,
        default=None,
        help="Optional report export directory.",
    )

    parser.add_argument(
        "--confirm-replace",
        action="store_true",
        help=(
            "Required to replace existing records in the selected "
            "database. Make a verified backup before using this option."
        ),
    )

    args = parser.parse_args()

    generate_data(
        customer_count=args.customers,
        document_count=args.documents,
        business_count=args.businesses,
        review_count=args.reviews,
        seed=args.seed,
        confirm_replace=args.confirm_replace,
        db_path=args.db_path,
        dataset_dir=args.dataset_dir,
        report_dir=args.report_dir,
    )
