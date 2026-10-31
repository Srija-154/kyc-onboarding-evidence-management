
import json
import sqlite3
from pathlib import Path
from datetime import date

import pandas as pd

from database import BASE_DIR, DB_PATH


TODAY = date(2026, 10, 31)


def run_validation(
    db_path=None,
    dataset_dir=None,
    report_dir=None,
):
    """
    Validate the KYC database and generated datasets.

    Optional paths allow validation to run against an isolated
    test database without modifying the original project data.
    """

    active_db_path = Path(db_path) if db_path else DB_PATH

    active_dataset_dir = (
        Path(dataset_dir)
        if dataset_dir
        else BASE_DIR / "datasets"
    )

    active_report_dir = (
        Path(report_dir)
        if report_dir
        else BASE_DIR / "reports"
    )

    if not active_db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {active_db_path}"
        )

    structural_errors = []
    business_exceptions = []
    operational_warnings = []

    checks = {}
    counts = {}

    with sqlite3.connect(active_db_path) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")

        # ---------------------------------------------------------
        # 1. SQLite database integrity
        # ---------------------------------------------------------
        integrity = conn.execute(
            "PRAGMA integrity_check"
        ).fetchall()

        integrity_messages = [
            row[0] for row in integrity
        ]

        checks["database_integrity"] = integrity_messages

        if integrity_messages != ["ok"]:
            structural_errors.append(
                "SQLite database integrity check failed."
            )

        # ---------------------------------------------------------
        # 2. Foreign-key integrity
        # ---------------------------------------------------------
        fk = [
            dict(row)
            for row in conn.execute(
                "PRAGMA foreign_key_check"
            ).fetchall()
        ]

        checks["foreign_key_violations"] = len(fk)

        if fk:
            structural_errors.append(
                "Foreign-key violations found."
            )

        # ---------------------------------------------------------
        # 3. Table counts and primary-key checks
        # ---------------------------------------------------------
        tables = [
            "customers",
            "documents",
            "verifications",
            "risk_ratings",
            "review_cases",
            "beneficial_owners",
            "alerts",
            "audit_events",
            "kyc_requirements",
            "customer_types",
        ]

        for table in tables:

            counts[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]

            table_info = conn.execute(
                f"PRAGMA table_info({table})"
            ).fetchall()

            pk_col = next(
                (
                    row["name"]
                    for row in table_info
                    if row["pk"] == 1
                ),
                None,
            )

            if pk_col:
                duplicates = conn.execute(
                    f"""
                    SELECT COUNT(*)
                    FROM (
                        SELECT {pk_col}
                        FROM {table}
                        GROUP BY {pk_col}
                        HAVING COUNT(*) > 1
                    )
                    """
                ).fetchone()[0]

                checks[
                    f"{table}_duplicate_primary_keys"
                ] = duplicates

                if duplicates:
                    structural_errors.append(
                        f"Duplicate primary keys found in {table}."
                    )

        checks["row_counts"] = counts

        # ---------------------------------------------------------
        # 4. Duplicate document references
        # ---------------------------------------------------------
        duplicate_documents = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT document_reference
                FROM documents
                WHERE document_reference IS NOT NULL
                  AND TRIM(document_reference) != ''
                GROUP BY document_reference
                HAVING COUNT(DISTINCT customer_id) > 1
            )
            """
        ).fetchone()[0]

        checks["duplicate_document_references"] = (
            duplicate_documents
        )

        if duplicate_documents:
            business_exceptions.append(
                "Document references are shared across unrelated customers."
            )

        # ---------------------------------------------------------
        # 5. Beneficial ownership percentage validation
        # ---------------------------------------------------------
        ownership_over_100 = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT customer_id
                FROM beneficial_owners
                GROUP BY customer_id
                HAVING SUM(ownership_percentage) > 100
            )
            """
        ).fetchone()[0]

        checks["ownership_groups_over_100"] = ownership_over_100

        if ownership_over_100:
            business_exceptions.append(
                "Beneficial ownership totals exceed 100%."
            )

        # ---------------------------------------------------------
        # 6. Closed reviews without resolution
        # ---------------------------------------------------------
        unresolved_reviews = conn.execute(
            """
            SELECT COUNT(*)
            FROM review_cases
            WHERE review_status IN ('CLOSED', 'COMPLETED')
              AND (
                  resolution IS NULL
                  OR TRIM(resolution) = ''
              )
            """
        ).fetchone()[0]

        checks["closed_reviews_without_resolution"] = (
            unresolved_reviews
        )

        if unresolved_reviews:
            business_exceptions.append(
                "Closed reviews exist without a resolution."
            )

        # ---------------------------------------------------------
        # 7. Expired documents marked as verified
        # ---------------------------------------------------------
        expired_verified = conn.execute(
            """
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
            SELECT COUNT(DISTINCT d.document_id)
            FROM documents d
            LEFT JOIN latest_verification v
                ON v.document_id = d.document_id
               AND v.row_num = 1
            WHERE d.expiry_date < ?
              AND (
                  d.lifecycle_status = 'VERIFIED'
                  OR v.verification_status = 'VERIFIED'
              )
            """,
            (TODAY.isoformat(),),
        ).fetchone()[0]

        checks["expired_documents_marked_verified"] = (
            expired_verified
        )

        if expired_verified:
            business_exceptions.append(
                "Expired documents are marked as verified."
            )

        # ---------------------------------------------------------
        # 8. Approved customers missing mandatory KYC evidence
        # ---------------------------------------------------------
        approved_missing = conn.execute(
            """
            WITH latest_risk AS (
                SELECT
                    customer_id,
                    risk_level,
                    ROW_NUMBER() OVER (
                        PARTITION BY customer_id
                        ORDER BY effective_from DESC,
                                 risk_rating_id DESC
                    ) AS rn
                FROM risk_ratings
                WHERE effective_from <= ?
                  AND (
                      effective_to IS NULL
                      OR effective_to >= ?
                  )
            ),

            active_requirements AS (
                SELECT DISTINCT
                    customer_type_id,
                    risk_level,
                    document_type
                FROM kyc_requirements
                WHERE mandatory = 1
                  AND effective_from <= ?
                  AND (
                      effective_to IS NULL
                      OR effective_to >= ?
                  )
            ),

            latest_verification AS (
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

            SELECT COUNT(DISTINCT c.customer_id)
            FROM customers c

            LEFT JOIN latest_risk rr
                ON rr.customer_id = c.customer_id
               AND rr.rn = 1

            WHERE c.lifecycle_status = 'APPROVED'

              AND (
                  rr.customer_id IS NULL

                  OR NOT EXISTS (
                      SELECT 1
                      FROM active_requirements kr
                      WHERE kr.customer_type_id =
                            c.customer_type_id
                        AND kr.risk_level = rr.risk_level
                  )

                  OR EXISTS (
                      SELECT 1
                      FROM active_requirements kr
                      WHERE kr.customer_type_id =
                            c.customer_type_id
                        AND kr.risk_level = rr.risk_level

                        AND NOT EXISTS (
                            SELECT 1
                            FROM documents d

                            JOIN latest_verification v
                                ON v.document_id = d.document_id
                               AND v.row_num = 1

                            WHERE d.customer_id = c.customer_id
                              AND d.document_type = kr.document_type
                              AND d.lifecycle_status = 'VERIFIED'
                              AND v.verification_status = 'VERIFIED'
                              AND (
                                  d.expiry_date IS NULL
                                  OR d.expiry_date >= ?
                              )
                        )
                  )
              )
            """,
            (
                TODAY.isoformat(),
                TODAY.isoformat(),
                TODAY.isoformat(),
                TODAY.isoformat(),
                TODAY.isoformat(),
            ),
        ).fetchone()[0]

        checks["approved_customers_missing_evidence"] = (
            approved_missing
        )

        if approved_missing:
            business_exceptions.append(
                "Approved customers have incomplete or invalid "
                "mandatory KYC evidence."
            )

        # ---------------------------------------------------------
        # 9. Customers with duplicate active reviews
        # ---------------------------------------------------------
        duplicate_active_reviews = conn.execute(
            """
            SELECT COUNT(*)
            FROM (
                SELECT customer_id
                FROM review_cases
                WHERE review_status IN (
                    'SCHEDULED',
                    'IN_PROGRESS',
                    'OVERDUE'
                )
                GROUP BY customer_id
                HAVING COUNT(*) > 1
            )
            """
        ).fetchone()[0]

        checks["customers_with_duplicate_active_reviews"] = (
            duplicate_active_reviews
        )

        if duplicate_active_reviews:
            business_exceptions.append(
                "Customers have multiple active review cases."
            )

        # ---------------------------------------------------------
        # 10. Closed reviews missing closing timestamps
        # ---------------------------------------------------------
        missing_close_timestamp = conn.execute(
            """
            SELECT COUNT(*)
            FROM review_cases
            WHERE review_status IN ('CLOSED', 'COMPLETED')
              AND (
                  closed_at IS NULL
                  OR TRIM(closed_at) = ''
              )
            """
        ).fetchone()[0]

        checks["closed_reviews_missing_timestamp"] = (
            missing_close_timestamp
        )

        if missing_close_timestamp:
            business_exceptions.append(
                "Closed reviews are missing closing timestamps."
            )

    # -------------------------------------------------------------
    # 11. Ground-truth dataset validation
    # -------------------------------------------------------------
    gt_path = active_dataset_dir / "ground_truth.csv"

    if gt_path.exists():

        try:
            ground_truth = pd.read_csv(gt_path)

            checks["ground_truth_rows"] = len(
                ground_truth
            )

            if ground_truth.empty:
                operational_warnings.append(
                    "Ground-truth dataset exists but contains no records."
                )

            required_gt_columns = {
                "record_id",
                "customer_id",
                "issue_type",
            }

            missing_gt_columns = (
                required_gt_columns
                - set(ground_truth.columns)
            )

            checks["ground_truth_missing_columns"] = sorted(
                missing_gt_columns
            )

            if missing_gt_columns:
                structural_errors.append(
                    "Ground-truth dataset is missing required columns."
                )

        except Exception as exc:
            checks["ground_truth_rows"] = None
            checks["ground_truth_error"] = str(exc)

            operational_warnings.append(
                "Ground-truth dataset could not be read."
            )

    else:
        checks["ground_truth_rows"] = 0

        operational_warnings.append(
            "Ground-truth dataset is missing."
        )

    # -------------------------------------------------------------
    # 12. Dataset presence validation
    # -------------------------------------------------------------
    if counts.get("customers", 0) == 0:
        operational_warnings.append(
            "No customer records found."
        )

    if counts.get("documents", 0) == 0:
        operational_warnings.append(
            "No document records found."
        )

      
    # -------------------------------------------------------------
    # 13. Record-level ground-truth matching
    # -------------------------------------------------------------

    exception_mapping = {
        "DUPLICATE_DOCUMENT": "duplicate_document_references",
        "OWNERSHIP_OVER_100": "ownership_groups_over_100",
        "CLOSED_WITHOUT_RESOLUTION": "closed_reviews_without_resolution",
        "EXPIRED_MARKED_VALID": "expired_documents_marked_verified",
        "APPROVED_WITH_MISSING_EVIDENCE": (
            "approved_customers_missing_evidence"
        ),
    }

    ground_truth_issue_counts = {}
    expected_business_exceptions = []
    unexpected_business_exceptions = []
    unmatched_ground_truth = []

    detected_records = {
        issue_type: set()
        for issue_type in exception_mapping
    }

    if "ground_truth" in locals() and not ground_truth.empty:
        ground_truth_issue_counts = (
            ground_truth["issue_type"]
            .fillna("")
            .astype(str)
            .value_counts()
            .to_dict()
        )

        # Reopen the selected database for record-level queries.
        with sqlite3.connect(active_db_path) as gt_conn:

            # 1. Duplicate document references
            rows = gt_conn.execute(
                """
                SELECT d.document_id, d.customer_id
                FROM documents d
                JOIN (
                    SELECT document_reference
                    FROM documents
                    WHERE document_reference IS NOT NULL
                      AND TRIM(document_reference) != ''
                    GROUP BY document_reference
                    HAVING COUNT(DISTINCT customer_id) > 1
                ) dup
                ON dup.document_reference = d.document_reference
                """
            ).fetchall()

            detected_records["DUPLICATE_DOCUMENT"] = set(rows)

            # 2. Ownership totals over 100 percent
            rows = gt_conn.execute(
                """
                SELECT customer_id
                FROM beneficial_owners
                GROUP BY customer_id
                HAVING SUM(ownership_percentage) > 100
                """
            ).fetchall()

            detected_records["OWNERSHIP_OVER_100"] = {
                (row[0], row[0]) for row in rows
            }

            # 3. Closed reviews without resolution
            rows = gt_conn.execute(
                """
                SELECT review_id, customer_id
                FROM review_cases
                WHERE review_status IN ('CLOSED', 'COMPLETED')
                  AND (
                      resolution IS NULL
                      OR TRIM(resolution) = ''
                  )
                """
            ).fetchall()

            detected_records["CLOSED_WITHOUT_RESOLUTION"] = set(rows)

            # 4. Expired documents marked verified
            rows = gt_conn.execute(
                """
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
                SELECT DISTINCT d.document_id, d.customer_id
                FROM documents d
                LEFT JOIN latest_verification v
                    ON v.document_id = d.document_id
                   AND v.row_num = 1
                WHERE d.expiry_date < ?
                  AND (
                      d.lifecycle_status = 'VERIFIED'
                      OR v.verification_status = 'VERIFIED'
                  )
                """,
                (TODAY.isoformat(),),
            ).fetchall()

            detected_records["EXPIRED_MARKED_VALID"] = set(rows)

            # 5. Approved customers missing mandatory evidence
            rows = gt_conn.execute(
                """
                WITH latest_risk AS (
                    SELECT
                        customer_id,
                        risk_level,
                        ROW_NUMBER() OVER (
                            PARTITION BY customer_id
                            ORDER BY effective_from DESC,
                                     risk_rating_id DESC
                        ) AS rn
                    FROM risk_ratings
                    WHERE effective_from <= ?
                      AND (
                          effective_to IS NULL
                          OR effective_to >= ?
                      )
                ),
                active_requirements AS (
                    SELECT DISTINCT
                        customer_type_id,
                        risk_level,
                        document_type
                    FROM kyc_requirements
                    WHERE mandatory = 1
                      AND effective_from <= ?
                      AND (
                          effective_to IS NULL
                          OR effective_to >= ?
                      )
                ),
                latest_verification AS (
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
                SELECT DISTINCT c.customer_id, c.customer_id
                FROM customers c
                LEFT JOIN latest_risk rr
                    ON rr.customer_id = c.customer_id
                   AND rr.rn = 1
                WHERE c.lifecycle_status = 'APPROVED'
                  AND (
                      rr.customer_id IS NULL
                      OR NOT EXISTS (
                          SELECT 1
                          FROM active_requirements kr
                          WHERE kr.customer_type_id =
                                c.customer_type_id
                            AND kr.risk_level = rr.risk_level
                      )
                      OR EXISTS (
                          SELECT 1
                          FROM active_requirements kr
                          WHERE kr.customer_type_id =
                                c.customer_type_id
                            AND kr.risk_level = rr.risk_level
                            AND NOT EXISTS (
                                SELECT 1
                                FROM documents d
                                JOIN latest_verification v
                                    ON v.document_id = d.document_id
                                   AND v.row_num = 1
                                WHERE d.customer_id = c.customer_id
                                  AND d.document_type = kr.document_type
                                  AND d.lifecycle_status = 'VERIFIED'
                                  AND v.verification_status = 'VERIFIED'
                                  AND (
                                      d.expiry_date IS NULL
                                      OR d.expiry_date >= ?
                                  )
                            )
                      )
                  )
                """,
                (
                    TODAY.isoformat(),
                    TODAY.isoformat(),
                    TODAY.isoformat(),
                    TODAY.isoformat(),
                    TODAY.isoformat(),
                ),
            ).fetchall()

            detected_records[
                "APPROVED_WITH_MISSING_EVIDENCE"
            ] = set(rows)

    expected_issue_types = set(exception_mapping.keys())

    unknown_issue_types = (
        set(ground_truth_issue_counts.keys())
        - expected_issue_types
    )

    if unknown_issue_types:
        operational_warnings.append(
            "Ground-truth contains unrecognized issue types: "
            + ", ".join(sorted(unknown_issue_types))
        )

    for issue_type in exception_mapping:

        labelled_rows = set()

        if "ground_truth" in locals() and not ground_truth.empty:
            issue_rows = ground_truth[
                ground_truth["issue_type"].astype(str) == issue_type
            ]

            labelled_rows = {
                (str(row["record_id"]), str(row["customer_id"]))
                for _, row in issue_rows.iterrows()
            }

        detected_rows = {
            (str(record_id), str(customer_id))
            for record_id, customer_id in detected_records[issue_type]
        }

        matched_rows = labelled_rows & detected_rows
        missing_rows = labelled_rows - detected_rows

        # The second document in a duplicate pair can also be detected
        # without being separately labelled in ground_truth.csv.
        extra_rows = (
            detected_rows - labelled_rows
            if issue_type != "DUPLICATE_DOCUMENT"
            else set()
        )

        if matched_rows:
            expected_business_exceptions.append({
                "issue_type": issue_type,
                "count": len(matched_rows),
                "matched_records": [
                    {
                        "record_id": record_id,
                        "customer_id": customer_id,
                    }
                    for record_id, customer_id in sorted(matched_rows)
                ],
            })

        if missing_rows:
            unmatched_ground_truth.append({
                "issue_type": issue_type,
                "count": len(missing_rows),
                "records": [
                    {
                        "record_id": record_id,
                        "customer_id": customer_id,
                    }
                    for record_id, customer_id in sorted(missing_rows)
                ],
                "reason": "Ground-truth record was not detected.",
            })

        if extra_rows:
            unexpected_business_exceptions.append({
                "issue_type": issue_type,
                "count": len(extra_rows),
                "records": [
                    {
                        "record_id": record_id,
                        "customer_id": customer_id,
                    }
                    for record_id, customer_id in sorted(extra_rows)
                ],
                "reason": "Detected record has no matching ground-truth label.",
            })

    # Checks that have no intentional anomaly labels.
    unlabelled_checks = {
        "customers_with_duplicate_active_reviews": (
            "Customers have multiple active review cases."
        ),
        "closed_reviews_missing_timestamp": (
            "Closed reviews are missing closing timestamps."
        ),
    }

    for check_name, description in unlabelled_checks.items():
        detected_count = checks.get(check_name, 0)

        if detected_count:
            unexpected_business_exceptions.append({
                "issue_type": check_name,
                "count": detected_count,
                "reason": description,
            })


    # -------------------------------------------------------------
    # 14. Final validation report
    # -------------------------------------------------------------

    checks["ground_truth_issue_counts"] = (
        ground_truth_issue_counts
    )

    checks["expected_business_exceptions"] = (
        expected_business_exceptions
    )

    checks["unexpected_business_exceptions"] = (
        unexpected_business_exceptions
    )

    checks["unmatched_ground_truth"] = (
        unmatched_ground_truth
    )

    checks["structural_errors"] = structural_errors

    checks["business_exceptions"] = business_exceptions

    checks["operational_warnings"] = operational_warnings

    checks["expected_exception_count"] = sum(
        item["count"]
        for item in expected_business_exceptions
    )

    checks["unexpected_exception_count"] = sum(
        item["count"]
        for item in unexpected_business_exceptions
    )

    checks["unmatched_ground_truth_count"] = sum(
        item["count"]
        for item in unmatched_ground_truth
    )

    checks["structural_status"] = (
        "PASSED"
        if not structural_errors
        else "FAILED"
    )

    if unexpected_business_exceptions:
        checks["business_status"] = "UNEXPECTED_EXCEPTIONS_FOUND"
    elif expected_business_exceptions:
        checks["business_status"] = "EXPECTED_EXCEPTIONS_ONLY"
    else:
        checks["business_status"] = "CLEAN"

    # Required data and ground-truth checks
    
    # Required data and ground-truth checks
    required_tables_present = all(
        checks.get("row_counts", {}).get(table, 0) > 0
        for table in [
            "customers",
            "documents",
            "verifications",
            "risk_ratings",
            "kyc_requirements",
            "customer_types",
        ]
    )

    ground_truth_valid = (
        checks.get("ground_truth_rows", 0) > 0
        and not checks.get("ground_truth_missing_columns", [])
        and "ground_truth_error" not in checks
    )

    checks["validation_passed"] = (
        len(structural_errors) == 0
        and checks["unexpected_exception_count"] == 0
        and checks["unmatched_ground_truth_count"] == 0
        and required_tables_present
        and ground_truth_valid
        and len(operational_warnings) == 0
    )

    checks["validation_status"] = (
        "PASSED"
        if checks["validation_passed"]
        else "ATTENTION_REQUIRED"
    )

    checks["notes"] = (
        structural_errors
        + business_exceptions
        + operational_warnings
    )

    checks["database"] = str(active_db_path)
    checks["dataset_directory"] = str(active_dataset_dir)

    # -------------------------------------------------------------
    # 15. Save validation report
    # -------------------------------------------------------------

    active_report_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        active_report_dir / "validation_summary.json"
    )

    report_path.write_text(
        json.dumps(checks, indent=2),
        encoding="utf-8",
    )

    return checks

if __name__ == "__main__":
    print(
        json.dumps(
            run_validation(),
            indent=2,
        )
    )
