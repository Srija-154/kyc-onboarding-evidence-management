
from contextlib import closing
from datetime import date, timedelta

from database import get_connection


TODAY = date(2026, 10, 31)


def requirements_for(conn, customer_id):
    """
    Return mandatory KYC document requirements based on
    the customer's currently effective risk rating.
    """

    row = conn.execute("""
        SELECT c.customer_type_id, r.risk_level
        FROM customers c
        JOIN risk_ratings r
            ON r.customer_id = c.customer_id
        WHERE c.customer_id = ?
          AND r.effective_from <= ?
          AND (
              r.effective_to IS NULL
              OR r.effective_to >= ?
          )
        ORDER BY r.effective_from DESC, r.risk_rating_id DESC
        LIMIT 1
    """, (
        customer_id,
        TODAY.isoformat(),
        TODAY.isoformat()
    )).fetchone()

    if not row:
        return []

    requirements = conn.execute("""
        SELECT DISTINCT document_type
        FROM kyc_requirements
        WHERE customer_type_id = ?
          AND risk_level = ?
          AND mandatory = 1
          AND effective_from <= ?
          AND (
              effective_to IS NULL
              OR effective_to >= ?
          )
        ORDER BY document_type
    """, (
        row["customer_type_id"],
        row["risk_level"],
        TODAY.isoformat(),
        TODAY.isoformat()
    )).fetchall()

    return [item["document_type"] for item in requirements]


def _calculate_completeness(conn, customer_id):
    """
    Calculate KYC completeness using valid, verified,
    unexpired documents.

    Only the latest verification record for each document
    determines its current verification status.
    """

    required = requirements_for(conn, customer_id)

    if not required:
        return {
            "customer_id": customer_id,
            "required": 0,
            "satisfied": 0,
            "percentage": 0.0
        }

    verified = {
        row["document_type"]
        for row in conn.execute("""
            WITH latest_verification AS (
                SELECT
                    document_id,
                    verification_status,
                    ROW_NUMBER() OVER (
                        PARTITION BY document_id
                        ORDER BY verification_date DESC,
                                 verification_id DESC
                    ) AS row_num
                FROM verifications
            )
            SELECT DISTINCT d.document_type
            FROM documents d
            JOIN latest_verification v
                ON v.document_id = d.document_id
               AND v.row_num = 1
            WHERE d.customer_id = ?
              AND d.lifecycle_status = 'VERIFIED'
              AND v.verification_status = 'VERIFIED'
              AND (
                  d.expiry_date IS NULL
                  OR d.expiry_date >= ?
              )
        """, (
            customer_id,
            TODAY.isoformat()
        )).fetchall()
    }

    satisfied = sum(
        1 for document_type in required
        if document_type in verified
    )

    percentage = round(
        satisfied / len(required) * 100,
        2
    )

    return {
        "customer_id": customer_id,
        "required": len(required),
        "satisfied": satisfied,
        "percentage": percentage
    }


def calculate_completeness(customer_id):
    """
    Public function used by the Streamlit application.
    """

    with closing(get_connection()) as conn:
        return _calculate_completeness(conn, customer_id)


def schedule_review(customer_id):
    """
    Schedule a periodic KYC review based on risk level.
    Prevent multiple active reviews for the same customer.
    """

    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            customer = conn.execute("""
                SELECT customer_id
                FROM customers
                WHERE customer_id = ?
            """, (customer_id,)).fetchone()

            if not customer:
                raise ValueError("Customer not found.")

            risk = conn.execute("""
                SELECT risk_level
                FROM risk_ratings
                WHERE customer_id = ?
                  AND effective_from <= ?
                  AND (
                      effective_to IS NULL
                      OR effective_to >= ?
                  )
                ORDER BY effective_from DESC, risk_rating_id DESC
                LIMIT 1
            """, (
                customer_id,
                TODAY.isoformat(),
                TODAY.isoformat()
            )).fetchone()

            if not risk:
                raise ValueError(
                    "Currently effective customer risk rating not found."
                )

            review_intervals = {
                "LOW": 3,
                "MEDIUM": 2,
                "HIGH": 1
            }

            risk_level = risk["risk_level"]

            if risk_level not in review_intervals:
                raise ValueError(
                    f"Unsupported risk level: {risk_level}"
                )

            active_review = conn.execute("""
                SELECT review_id
                FROM review_cases
                WHERE customer_id = ?
                  AND review_status IN (
                      'SCHEDULED',
                      'IN_PROGRESS',
                      'OVERDUE'
                  )
                LIMIT 1
            """, (customer_id,)).fetchone()

            if active_review:
                raise ValueError(
                    f"An active review already exists: "
                    f"{active_review['review_id']}"
                )

            years = review_intervals[risk_level]

            due_date = (
                TODAY + timedelta(days=365 * years)
            ).isoformat()

            existing = conn.execute("""
                SELECT COUNT(*) AS n
                FROM review_cases
                WHERE customer_id = ?
            """, (customer_id,)).fetchone()["n"]

            review_id = (
                f"REV-{customer_id}-{TODAY.year}-{existing + 1:04d}"
            )

            while conn.execute("""
                SELECT 1
                FROM review_cases
                WHERE review_id = ?
            """, (review_id,)).fetchone():
                existing += 1
                review_id = (
                    f"REV-{customer_id}-{TODAY.year}-{existing + 1:04d}"
                )

            conn.execute("""
                INSERT INTO review_cases (
                    review_id,
                    customer_id,
                    scheduled_date,
                    due_date,
                    review_status
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                review_id,
                customer_id,
                TODAY.isoformat(),
                due_date,
                "SCHEDULED"
            ))

            conn.execute("""
                INSERT INTO audit_events (
                    audit_event_id,
                    customer_id,
                    entity_type,
                    entity_id,
                    action,
                    new_value,
                    actor,
                    event_timestamp
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                f"AUD-MANUAL-{review_id}",
                customer_id,
                "REVIEW",
                review_id,
                "REVIEW_SCHEDULED",
                due_date,
                "OPERATIONS_ANALYST",
                TODAY.isoformat()
            ))

            conn.commit()
            return review_id

        except Exception:
            conn.rollback()
            raise


def approve_customer(customer_id):
    """
    Approve a customer only when all mandatory KYC
    requirements are satisfied.
    """

    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            customer = conn.execute("""
                SELECT lifecycle_status
                FROM customers
                WHERE customer_id = ?
            """, (customer_id,)).fetchone()

            if not customer:
                raise ValueError("Customer not found.")

            if customer["lifecycle_status"] == "APPROVED":
                raise ValueError("Customer is already approved.")

            result = _calculate_completeness(
                conn,
                customer_id
            )

            if result["required"] == 0:
                raise ValueError(
                    "Cannot approve: No active mandatory KYC "
                    "requirements were found."
                )

            if result["percentage"] < 100:
                raise ValueError(
                    f"Cannot approve: KYC is only "
                    f"{result['percentage']}% complete "
                    f"({result['satisfied']}/{result['required']} "
                    f"requirements satisfied)."
                )

            conn.execute("""
                UPDATE customers
                SET lifecycle_status = 'APPROVED'
                WHERE customer_id = ?
            """, (customer_id,))

            conn.execute("""
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
            """, (
                f"AUD-APPROVE-{customer_id}-{TODAY.isoformat()}",
                customer_id,
                "CUSTOMER",
                customer_id,
                "CUSTOMER_APPROVED",
                customer["lifecycle_status"],
                "APPROVED",
                "COMPLIANCE_REVIEWER",
                TODAY.isoformat()
            ))

            conn.commit()
            return True

        except Exception:
            conn.rollback()
            raise


def close_review(review_id, resolution):
    """
    Close an active review only when a valid resolution
    has been provided.
    """

    if not resolution or not resolution.strip():
        raise ValueError(
            "A review cannot be closed without a resolution."
        )

    with closing(get_connection()) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute("""
                SELECT customer_id, review_status
                FROM review_cases
                WHERE review_id = ?
            """, (review_id,)).fetchone()

            if not row:
                raise ValueError("Review not found.")

            if row["review_status"] in ("CLOSED", "COMPLETED"):
                raise ValueError(
                    "This review is already closed or completed."
                )

            conn.execute("""
                UPDATE review_cases
                SET review_status = 'CLOSED',
                    resolution = ?,
                    closed_at = ?
                WHERE review_id = ?
            """, (
                resolution.strip(),
                TODAY.isoformat(),
                review_id
            ))

            conn.execute("""
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
            """, (
                f"AUD-CLOSE-{review_id}",
                row["customer_id"],
                "REVIEW",
                review_id,
                "REVIEW_CLOSED",
                row["review_status"],
                "CLOSED",
                "OPERATIONS_ANALYST",
                TODAY.isoformat()
            ))

            conn.commit()
            return True

        except Exception:
            conn.rollback()
            raise
