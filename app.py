import json
import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

# Connect the dashboard to the isolated full dataset.
BASE_DIR = Path(__file__).resolve().parent

os.environ["KYC_DB_PATH"] = str(
    BASE_DIR
    / "test_artifacts"
    / "full"
    / "data"
    / "kyc_full_test.db"
)

from database import BASE_DIR, DB_PATH, initialize_database, get_connection
from business_rules import (
    calculate_completeness,
    schedule_review,
    approve_customer,
    close_review
)
from validation import run_validation

st.set_page_config(
    page_title="KYC Evidence Management",
    page_icon="🛡️",
    layout="wide"
)

initialize_database()


st.markdown("""
<style>
/* Main application */
.stApp {
    background: #f5f7fb;
    color: #17243a;
}

.block-container {
    max-width: 1550px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: #101c33;
    border-right: 1px solid #263550;
}

[data-testid="stSidebar"] * {
    color: #e8eef8;
}

[data-testid="stSidebar"] [data-testid="stRadio"] label {
    padding: 7px 10px;
    border-radius: 8px;
}

/* Headings */
h1 {
    color: #14213a;
    font-weight: 750;
    letter-spacing: -1px;
}

h2, h3 {
    color: #1b2c49;
    font-weight: 650;
}

/* Metric cards */
[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e4eaf2;
    border-radius: 14px;
    padding: 20px;
    box-shadow: 0 3px 12px rgba(25, 45, 75, 0.05);
}

[data-testid="stMetricLabel"] {
    color: #65748b;
    font-size: 14px;
    font-weight: 600;
}

[data-testid="stMetricValue"] {
    color: #142d50;
    font-weight: 750;
}

/* Buttons */
.stButton > button,
.stFormSubmitButton > button {
    background: #1769aa;
    color: white;
    border: none;
    border-radius: 9px;
    padding: 9px 18px;
    font-weight: 600;
    transition: 0.2s ease;
}

.stButton > button:hover,
.stFormSubmitButton > button:hover {
    background: #105486;
    color: white;
    border: none;
}

/* Inputs */
[data-testid="stTextInput"] input,
[data-testid="stSelectbox"] div[data-baseweb="select"] {
    border-radius: 8px;
}

/* Tables */
[data-testid="stDataFrame"] {
    border: 1px solid #e2e8f0;
    border-radius: 11px;
    overflow: hidden;
    background: white;
}

/* Expanders and containers */
[data-testid="stExpander"] {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 11px;
}

/* Charts */
[data-testid="stPlotlyChart"] {
    background: white;
    border: 1px solid #e6ebf2;
    border-radius: 13px;
    padding: 10px;
}

/* Dividers */
hr {
    border-color: #e2e8f0;
}
</style>
""", unsafe_allow_html=True)


header_left, header_right = st.columns([5, 1])

with header_left:
    st.markdown(
        """
        <h1 style="margin-bottom:0;">
            🛡️ KYC Compliance Platform
        </h1>
        <p style="color:#718096; font-size:15px; margin-top:8px;">
            Customer onboarding · Evidence verification ·
            Risk monitoring · Compliance operations
        </p>
        """,
        unsafe_allow_html=True
    )

with header_right:
    st.markdown(
        """
        <div style="
            text-align:right;
            padding:10px;
            background:#e8f3ff;
            border-radius:10px;
            color:#1769aa;
            font-weight:600;
            margin-top:8px;">
            DEMO ENVIRONMENT
        </div>
        """,
        unsafe_allow_html=True
    )

st.divider()
with st.sidebar:
    st.header("Navigation")
    page = st.radio("Go to", ["Dashboard","Customers","Documents","Reviews","Alerts & Exceptions","Beneficial Owners","Audit Trail","System Information","Data & Validation"])
    st.divider()
    st.caption("Synthetic demonstration data only")
    if st.button("Refresh dashboard", use_container_width=True):
        st.rerun()

def query_df(sql, params=()):
    with get_connection() as conn:
        return pd.read_sql_query(sql, conn, params=params)

def has_data():
    return query_df("SELECT COUNT(*) AS n FROM customers").iloc[0]["n"] > 0

if not has_data() and page != "Data & Validation":
    st.warning("No KYC dataset found yet. Open **Data & Validation** in the sidebar to generate it.")
    st.info("First generate the starter test volume, run validation, and then generate the full assignment volume.")
    st.stop()

if page == "Dashboard":
    st.subheader("KYC Compliance Overview")
    st.caption(
        "Executive monitoring of customer onboarding, risk exposure, "
        "document health and periodic reviews."
    )

    TODAY = "2026-10-31"

    # 1. Customer KPIs
    customer_kpis = query_df("""
        SELECT
            COUNT(*) AS total_customers,
            SUM(CASE WHEN lifecycle_status = 'APPROVED'
                THEN 1 ELSE 0 END) AS approved_customers,
            SUM(CASE WHEN lifecycle_status = 'ONBOARDING'
                THEN 1 ELSE 0 END) AS onboarding_customers,
            SUM(CASE WHEN lifecycle_status = 'PENDING_REVIEW'
                THEN 1 ELSE 0 END) AS pending_customers,
            SUM(CASE WHEN lifecycle_status = 'REJECTED'
                THEN 1 ELSE 0 END) AS rejected_customers,
            SUM(CASE WHEN lifecycle_status = 'SUSPENDED'
                THEN 1 ELSE 0 END) AS suspended_customers
        FROM customers
    """)

    customer_stats = customer_kpis.iloc[0]

    total_customers = int(customer_stats["total_customers"] or 0)
    approved = int(customer_stats["approved_customers"] or 0)
    onboarding = int(customer_stats["onboarding_customers"] or 0)
    pending = int(customer_stats["pending_customers"] or 0)
    rejected = int(customer_stats["rejected_customers"] or 0)
    suspended = int(customer_stats["suspended_customers"] or 0)

    # 2. Document KPIs
    document_kpis = query_df("""
        SELECT
            COUNT(*) AS total_documents,
            SUM(CASE WHEN v.verification_status = 'VERIFIED'
                THEN 1 ELSE 0 END) AS verified_documents,
            SUM(CASE WHEN v.verification_status = 'PENDING'
                THEN 1 ELSE 0 END) AS pending_documents,
            SUM(CASE WHEN v.verification_status = 'REJECTED'
                THEN 1 ELSE 0 END) AS rejected_documents,
            SUM(CASE WHEN d.expiry_date IS NOT NULL
                      AND d.expiry_date < ?
                THEN 1 ELSE 0 END) AS expired_documents
        FROM documents d
        LEFT JOIN verifications v
            ON v.document_id = d.document_id
    """, (TODAY,))

    doc_stats = document_kpis.iloc[0]

    total_documents = int(doc_stats["total_documents"] or 0)
    verified_documents = int(doc_stats["verified_documents"] or 0)
    pending_documents = int(doc_stats["pending_documents"] or 0)
    rejected_documents = int(doc_stats["rejected_documents"] or 0)
    expired_documents = int(doc_stats["expired_documents"] or 0)

    # 3. Review KPIs
    review_kpis = query_df("""
        SELECT
            COUNT(*) AS total_reviews,
            SUM(CASE WHEN review_status IN ('SCHEDULED', 'IN_PROGRESS', 'OVERDUE')
                THEN 1 ELSE 0 END) AS open_reviews,
            SUM(CASE WHEN review_status = 'OVERDUE'
                OR (review_status NOT IN ('COMPLETED', 'CLOSED')
                    AND due_date < ?)
                THEN 1 ELSE 0 END) AS overdue_reviews,
            SUM(CASE WHEN review_status IN ('COMPLETED', 'CLOSED')
                THEN 1 ELSE 0 END) AS completed_reviews
        FROM review_cases
    """, (TODAY,))

    review_stats = review_kpis.iloc[0]

    total_reviews = int(review_stats["total_reviews"] or 0)
    open_reviews = int(review_stats["open_reviews"] or 0)
    overdue_reviews = int(review_stats["overdue_reviews"] or 0)
    completed_reviews = int(review_stats["completed_reviews"] or 0)

    # 4. Risk KPIs using latest risk rating per customer
    risk_data = query_df("""
        SELECT risk_level, COUNT(*) AS customer_count
        FROM (
            SELECT customer_id, risk_level,
                   ROW_NUMBER() OVER (
                       PARTITION BY customer_id
                       ORDER BY effective_from DESC
                   ) AS rn
            FROM risk_ratings
        )
        WHERE rn = 1
        GROUP BY risk_level
        ORDER BY risk_level
    """)

    # 5. Dashboard KPI cards
    st.markdown("### Customer Overview")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Customers", f"{total_customers:,}")
    c2.metric("Approved", f"{approved:,}")
    c3.metric("Onboarding", f"{onboarding:,}")
    c4.metric("Pending Review", f"{pending:,}")

    st.markdown("### Document & Review Health")

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Total Documents", f"{total_documents:,}")
    d2.metric("Verified Documents", f"{verified_documents:,}")
    d3.metric("Expired Documents", f"{expired_documents:,}")
    d4.metric("Overdue Reviews", f"{overdue_reviews:,}")

    st.divider()

    # 6. Risk distribution and lifecycle
    st.markdown("### Customer Risk & Lifecycle")

    left, right = st.columns(2)

    with left:
        st.markdown("**Latest Customer Risk Distribution**")

        if risk_data.empty:
            st.info("No risk ratings available.")
        else:
            risk_chart = px.pie(
                risk_data,
                names="risk_level",
                values="customer_count",
                hole=0.55,
                title="Customers by Risk Level"
            )

            risk_chart.update_layout(
                legend_title_text="Risk Level",
                margin=dict(t=50, b=20, l=10, r=10)
            )

            st.plotly_chart(
                risk_chart,
                use_container_width=True
            )

    with right:
        st.markdown("**Customer Lifecycle Distribution**")

        lifecycle_data = pd.DataFrame({
            "Lifecycle Status": [
                "Approved",
                "Onboarding",
                "Pending Review",
                "Rejected",
                "Suspended"
            ],
            "Customers": [
                approved,
                onboarding,
                pending,
                rejected,
                suspended
            ]
        })

        lifecycle_chart = px.bar(
            lifecycle_data,
            x="Lifecycle Status",
            y="Customers",
            title="Customers by Lifecycle Status",
            text="Customers"
        )

        lifecycle_chart.update_layout(
            xaxis_title="Lifecycle Status",
            yaxis_title="Customer Count",
            margin=dict(t=50, b=20, l=10, r=10)
        )

        st.plotly_chart(
            lifecycle_chart,
            use_container_width=True
        )

    st.divider()

    # 7. Document verification status
    st.markdown("### Document Verification Status")

    verification_data = query_df("""
        SELECT
            COALESCE(v.verification_status, 'NO VERIFICATION') AS status,
            COUNT(*) AS document_count
        FROM documents d
        LEFT JOIN verifications v
            ON v.document_id = d.document_id
        GROUP BY COALESCE(v.verification_status, 'NO VERIFICATION')
        ORDER BY document_count DESC
    """)

    if verification_data.empty:
        st.info("No document verification data available.")
    else:
        verification_chart = px.bar(
            verification_data,
            x="status",
            y="document_count",
            text="document_count",
            title="Documents by Verification Status"
        )

        verification_chart.update_layout(
            xaxis_title="Verification Status",
            yaxis_title="Document Count"
        )

        st.plotly_chart(
            verification_chart,
            use_container_width=True
        )

    # 8. Review performance
    st.markdown("### Periodic Review Performance")

    review_data = pd.DataFrame({
        "Review Status": [
            "Open",
            "Overdue",
            "Completed / Closed"
        ],
        "Count": [
            open_reviews,
            overdue_reviews,
            completed_reviews
        ]
    })

    review_chart = px.bar(
        review_data,
        x="Review Status",
        y="Count",
        text="Count",
        title="Review Status Summary"
    )

    review_chart.update_layout(
        xaxis_title="Review Status",
        yaxis_title="Number of Reviews"
    )

    st.plotly_chart(
        review_chart,
        use_container_width=True
    )

    # 9. Recent alerts
    st.divider()
    st.markdown("### Recent Compliance Alerts")

    recent_alerts = query_df("""
        SELECT
            a.alert_id,
            a.customer_id,
            c.full_name AS customer_name,
            a.alert_type,
            a.severity,
            a.message,
            a.created_at,
            a.alert_status
        FROM alerts a
        LEFT JOIN customers c
            ON c.customer_id = a.customer_id
        ORDER BY a.created_at DESC
        LIMIT 10
    """)

    if recent_alerts.empty:
        st.info("No compliance alerts available.")
    else:
        st.dataframe(
            recent_alerts,
            use_container_width=True,
            hide_index=True
        )

    st.caption(
        "Dashboard metrics are calculated from existing SQLite records. "
        "Demonstration date: 31 October 2026."
    )

elif page == "Customers":
    st.subheader("Customer Management")
    st.caption("Customer registration, onboarding status and 360-degree KYC profile")

    with st.expander("＋ Register a new customer"):
        with st.form("new_customer"):
            name = st.text_input("Full name / Business name")
            email = st.text_input("Email")
            ctype = st.selectbox("Customer type", ["INDIVIDUAL", "BUSINESS"])
            country = st.text_input("Country code", "IN")
            risk = st.selectbox("Initial risk level", ["LOW", "MEDIUM", "HIGH"])
            submitted = st.form_submit_button("Create customer")

        if submitted:
            if not name.strip() or not email.strip():
                st.error("Name and email are required.")
            else:
                try:
                    with get_connection() as conn:
                        next_no = conn.execute(
                            "SELECT COUNT(*)+1 n FROM customers"
                        ).fetchone()["n"]

                        cid = f"CUS-{next_no:06d}"
                        type_id = 1 if ctype == "INDIVIDUAL" else 2

                        conn.execute("""
                            INSERT INTO customers
                            (customer_id, full_name, email, customer_type_id,
                             registration_date, country, lifecycle_status)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            cid, name.strip(), email.strip(), type_id,
                            "2026-10-31", country.upper(), "ONBOARDING"
                        ))

                        score = {"LOW": 15, "MEDIUM": 48, "HIGH": 82}[risk]

                        conn.execute("""
                            INSERT INTO risk_ratings
                            (risk_rating_id, customer_id, risk_level,
                             risk_score, effective_from, reason)
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            f"RISK-MANUAL-{cid}", cid, risk,
                            score, "2026-10-31", "Manual registration"
                        ))

                        conn.execute("""
                            INSERT INTO audit_events
                            (audit_event_id, customer_id, entity_type,
                             entity_id, action, new_value, actor, event_timestamp)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            f"AUD-MANUAL-{cid}", cid, "CUSTOMER",
                            cid, "CUSTOMER_CREATED", name, "SYSTEM",
                            "2026-10-31"
                        ))

                        conn.commit()

                    st.success(f"Customer {cid} created successfully.")
                    st.rerun()

                except Exception as e:
                    st.error(f"Customer registration failed: {e}")

    st.divider()

    # Customer search and directory
    st.markdown("### Customer Directory")

    search = st.text_input(
        "Search by customer ID, name or email",
        placeholder="Enter customer ID, customer name or email"
    )

    df = query_df("""
        SELECT
            c.customer_id,
            c.full_name,
            c.email,
            ct.type_name AS customer_type,
            rr.risk_level,
            c.lifecycle_status
        FROM customers c
        JOIN customer_types ct
            ON ct.customer_type_id = c.customer_type_id
        LEFT JOIN risk_ratings rr
            ON rr.customer_id = c.customer_id
        ORDER BY c.customer_id
        LIMIT 2000
    """)

    if search:
        df = df[
            df.astype(str).apply(
                lambda col: col.str.contains(
                    search, case=False, na=False
                )
            ).any(axis=1)
        ]

    st.caption(f"Showing {len(df):,} matching customer records.")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.divider()

    
    # Customer 360-degree profile
    st.markdown("### Customer 360° Profile")
    st.caption(
        "Centralized customer view covering onboarding, risk, "
        "KYC evidence and document health."
    )

    if df.empty:
        st.info("No customers match your search.")
    else:
        customer_options = df["customer_id"].tolist()

        selected_id = st.selectbox(
            "Select a customer",
            customer_options,
            format_func=lambda x: (
                f"{x} — "
                f"{df.loc[df['customer_id'] == x, 'full_name'].iloc[0]}"
            ),
            key="customer_360_selector"
        )

        customer = query_df("""
            SELECT
                c.customer_id,
                c.full_name,
                c.email,
                c.country,
                c.registration_date,
                c.lifecycle_status,
                ct.type_name AS customer_type,
                (
                    SELECT rr.risk_level
                    FROM risk_ratings rr
                    WHERE rr.customer_id = c.customer_id
                    ORDER BY rr.effective_from DESC
                    LIMIT 1
                ) AS risk_level,
                (
                    SELECT rr.risk_score
                    FROM risk_ratings rr
                    WHERE rr.customer_id = c.customer_id
                    ORDER BY rr.effective_from DESC
                    LIMIT 1
                ) AS risk_score,
                (
                    SELECT rr.reason
                    FROM risk_ratings rr
                    WHERE rr.customer_id = c.customer_id
                    ORDER BY rr.effective_from DESC
                    LIMIT 1
                ) AS risk_reason
            FROM customers c
            JOIN customer_types ct
                ON ct.customer_type_id = c.customer_type_id
            WHERE c.customer_id = ?
        """, (selected_id,))

        if not customer.empty:
            profile = customer.iloc[0]

            st.divider()
            st.markdown(f"#### {profile['full_name']}")
            st.caption(f"Customer reference: {profile['customer_id']}")

            p1, p2, p3, p4 = st.columns(4)

            p1.metric(
                "Customer type",
                str(profile["customer_type"])
            )
            p2.metric(
                "Risk level",
                str(profile["risk_level"] or "N/A")
            )
            p3.metric(
                "Risk score",
                str(profile["risk_score"])
                if pd.notna(profile["risk_score"]) else "N/A"
            )
            p4.metric(
                "Lifecycle status",
                str(profile["lifecycle_status"])
            )

            # Customer information
            with st.container(border=True):
                st.markdown("**Customer Information**")

                info1, info2 = st.columns(2)

                with info1:
                    st.write("**Email:**", profile["email"])
                    st.write("**Country:**", profile["country"])

                with info2:
                    st.write(
                        "**Registration date:**",
                        profile["registration_date"]
                    )
                    st.write(
                        "**Risk reason:**",
                        profile["risk_reason"] or "Not available"
                    )

            # KYC completeness
            st.divider()
            st.markdown("#### KYC Completeness")

            try:
                completeness = calculate_completeness(selected_id)

                required = int(completeness["required"])
                satisfied = int(completeness["satisfied"])
                percentage = float(completeness["percentage"])

                if required == 0:
                    st.warning(
                        "No active mandatory KYC requirements were found "
                        "for this customer's current risk profile. "
                        "Completeness cannot be meaningfully assessed."
                    )
                else:
                    st.progress(
                        max(0.0, min(1.0, percentage / 100))
                    )

                    k1, k2, k3 = st.columns(3)

                    k1.metric("Completeness", f"{percentage:.1f}%")
                    k2.metric("Satisfied", f"{satisfied}")
                    k3.metric("Outstanding", f"{required - satisfied}")

                    if percentage == 100:
                        st.success("All configured mandatory requirements are satisfied.")
                    else:
                        st.warning(
                            "Some mandatory KYC evidence is still outstanding."
                        )

            except Exception as e:
                st.error(f"Could not calculate KYC completeness: {e}")

            # Document evidence
            st.divider()
            st.markdown("#### Document Evidence")

            documents = query_df("""
                SELECT
                    d.document_id,
                    d.document_type,
                    d.document_reference,
                    d.issue_date,
                    d.expiry_date,
                    d.lifecycle_status,
                    v.verification_status,
                    CASE
                        WHEN d.expiry_date IS NOT NULL
                             AND d.expiry_date < '2026-10-31'
                            THEN 'EXPIRED'
                        WHEN d.expiry_date IS NOT NULL
                             AND d.expiry_date <= '2026-11-30'
                            THEN 'EXPIRING SOON'
                        WHEN v.verification_status = 'REJECTED'
                            THEN 'REJECTED'
                        WHEN v.verification_status = 'MISMATCH'
                            THEN 'MISMATCH'
                        WHEN v.verification_status = 'VERIFIED'
                             AND d.lifecycle_status = 'VERIFIED'
                            THEN 'VERIFIED'
                        WHEN v.verification_status = 'PENDING'
                            THEN 'PENDING'
                        ELSE 'UNDER REVIEW'
                    END AS evidence_health
                FROM documents d
                LEFT JOIN verifications v
                    ON v.document_id = d.document_id
                WHERE d.customer_id = ?
                ORDER BY
                    CASE
                        WHEN d.expiry_date IS NOT NULL
                             AND d.expiry_date < '2026-10-31'
                            THEN 1
                        ELSE 2
                    END,
                    d.expiry_date
            """, (selected_id,))

            total_docs = len(documents)

            expired_count = (
                len(documents[documents["evidence_health"] == "EXPIRED"])
                if total_docs else 0
            )

            expiring_count = (
                len(documents[documents["evidence_health"] == "EXPIRING SOON"])
                if total_docs else 0
            )

            verified_count = (
                len(documents[documents["evidence_health"] == "VERIFIED"])
                if total_docs else 0
            )

            d1, d2, d3, d4 = st.columns(4)

            d1.metric("Total documents", total_docs)
            d2.metric("Verified", verified_count)
            d3.metric("Expired", expired_count)
            d4.metric("Expiring soon", expiring_count)

            if documents.empty:
                st.info("No documents are linked to this customer.")
            else:
                st.dataframe(
                    documents,
                    use_container_width=True,
                    hide_index=True
                )

                if expired_count > 0:
                    st.error(
                        f"{expired_count} document(s) have expired. "
                        "Review replacement evidence."
                    )

                if expiring_count > 0:
                    st.warning(
                        f"{expiring_count} document(s) are expiring "
                        "within the next 30 days."
                    )

            st.caption(
                "Document expiry is evaluated against the demonstration "
                "date: 31 October 2026."
            )


            # Reviews
            st.markdown("#### Review History")

            reviews = query_df("""
                SELECT
                    review_id,
                    scheduled_date,
                    due_date,
                    review_status,
                    resolution,
                    closed_at
                FROM review_cases
                WHERE customer_id = ?
                ORDER BY scheduled_date DESC
            """, (selected_id,))

            if reviews.empty:
                st.info("No review cases found.")
            else:
                st.dataframe(
                    reviews,
                    use_container_width=True,
                    hide_index=True
                )

            # Alerts
            st.markdown("#### Customer Alerts")

            alerts = query_df("""
                SELECT
                    alert_id,
                    alert_type,
                    severity,
                    message,
                    created_at,
                    alert_status
                FROM alerts
                WHERE customer_id = ?
                ORDER BY created_at DESC
            """, (selected_id,))

            if alerts.empty:
                st.success("No alerts recorded for this customer.")
            else:
                st.dataframe(
                    alerts,
                    use_container_width=True,
                    hide_index=True
                )

            # Customer actions
            st.markdown("#### Customer Actions")

            action1, action2 = st.columns(2)

            if action1.button(
                "Schedule Periodic Review",
                use_container_width=True
            ):
                try:
                    review = schedule_review(selected_id)
                    st.success(f"Review created: {review}")
                except Exception as e:
                    st.error(str(e))

            if action2.button(
                "Approve Customer",
                use_container_width=True
            ):
                try:
                    approve_customer(selected_id)
                    st.success("Customer approval action completed.")
                    st.rerun()
                except Exception as e:
                    st.error(str(e))

elif page == "Documents":
    st.subheader("Document Verification Workspace")
    st.caption(
        "Review customer evidence, verification status and document expiry."
    )

    TODAY = "2026-10-31"

    documents = query_df("""
        SELECT
            d.document_id,
            d.customer_id,
            c.full_name AS customer_name,
            d.document_type,
            d.document_reference,
            d.issue_date,
            d.expiry_date,
            d.lifecycle_status AS document_status,
            v.verification_status,
            v.verified_by,
            v.verification_date,
            v.notes,
            CASE
                WHEN d.expiry_date IS NOT NULL
                     AND d.expiry_date < ?
                    THEN 'EXPIRED'
                WHEN d.expiry_date IS NOT NULL
                     AND d.expiry_date <= '2026-11-30'
                    THEN 'EXPIRING SOON'
                WHEN v.verification_status = 'REJECTED'
                    THEN 'REJECTED'
                WHEN v.verification_status = 'MISMATCH'
                    THEN 'MISMATCH'
                WHEN v.verification_status = 'VERIFIED'
                     AND d.lifecycle_status = 'VERIFIED'
                    THEN 'VERIFIED'
                WHEN v.verification_status = 'PENDING'
                    THEN 'PENDING'
                ELSE 'UNDER REVIEW'
            END AS evidence_health
        FROM documents d
        JOIN customers c
            ON c.customer_id = d.customer_id
        LEFT JOIN verifications v
            ON v.document_id = d.document_id
        ORDER BY d.created_at DESC
        LIMIT 5000
    """, (TODAY,))

    # Summary metrics
    total_docs = len(documents)

    def document_count(status):
        return int(
            (documents["evidence_health"] == status).sum()
        ) if not documents.empty else 0

    verified_count = document_count("VERIFIED")
    pending_count = document_count("PENDING")
    rejected_count = document_count("REJECTED")
    expired_count = document_count("EXPIRED")
    mismatch_count = document_count("MISMATCH")
    expiring_count = document_count("EXPIRING SOON")

    m1, m2, m3 = st.columns(3)
    m1.metric("Total Documents", f"{total_docs:,}")
    m2.metric("Verified", f"{verified_count:,}")
    m3.metric("Pending", f"{pending_count:,}")

    m4, m5, m6 = st.columns(3)
    m4.metric("Rejected", f"{rejected_count:,}")
    m5.metric("Expired", f"{expired_count:,}")
    m6.metric("Mismatches", f"{mismatch_count:,}")

    if expiring_count:
        st.warning(
            f"{expiring_count} document(s) are expiring within 30 days."
        )

    st.divider()

    # Filters
    st.markdown("### Search and Filter Documents")

    search_text = st.text_input(
        "Search document, customer ID, name or reference",
        key="document_search"
    )

    status_options = sorted(
        documents["evidence_health"].dropna().unique().tolist()
    ) if not documents.empty else []

    selected_statuses = st.multiselect(
        "Verification and expiry status",
        options=status_options,
        default=status_options,
        key="document_status_filter"
    )

    if documents.empty:
        st.info("No document records found.")
    else:
        filtered_docs = documents.copy()

        if search_text.strip():
            search = search_text.strip().lower()

            searchable_columns = [
                "document_id",
                "customer_id",
                "customer_name",
                "document_type",
                "document_reference"
            ]

            mask = filtered_docs[searchable_columns].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(
                    search, regex=False
                )
            ).any(axis=1)

            filtered_docs = filtered_docs[mask]

        filtered_docs = filtered_docs[
            filtered_docs["evidence_health"].isin(selected_statuses)
        ]

        st.markdown("### Document Register")

        st.caption(
            f"Showing {len(filtered_docs):,} of {total_docs:,} documents."
        )

        st.dataframe(
            filtered_docs,
            use_container_width=True,
            hide_index=True
        )

        # Download
        st.download_button(
            "Download Document Register (CSV)",
            data=filtered_docs.to_csv(index=False),
            file_name="kyc_document_register_2026-10-31.csv",
            mime="text/csv",
            key="download_document_register"
        )

        # Individual document details
        st.divider()
        st.markdown("### Document Details")

        document_ids = filtered_docs["document_id"].tolist()

        if document_ids:
            selected_document = st.selectbox(
                "Select a document",
                document_ids,
                key="selected_document_details"
            )

            selected_row = filtered_docs[
                filtered_docs["document_id"] == selected_document
            ].iloc[0]

            with st.container(border=True):
                st.write("**Document ID:**", selected_row["document_id"])
                st.write("**Customer:**", selected_row["customer_name"])
                st.write("**Customer ID:**", selected_row["customer_id"])
                st.write("**Document type:**", selected_row["document_type"])
                st.write(
                    "**Reference:**",
                    selected_row["document_reference"]
                )
                st.write(
                    "**Document status:**",
                    selected_row["document_status"]
                )
                st.write(
                    "**Verification status:**",
                    selected_row["verification_status"]
                )
                st.write(
                    "**Evidence health:**",
                    selected_row["evidence_health"]
                )
                st.write("**Verified by:**", selected_row["verified_by"])
                st.write(
                    "**Verification date:**",
                    selected_row["verification_date"]
                )
                st.write("**Expiry date:**", selected_row["expiry_date"])
                st.write("**Verification notes:**", selected_row["notes"])

    st.caption(
        "This page is a read-only demonstration. "
        "It does not alter document or verification statuses."
    )

elif page == "Reviews":
    st.subheader("Periodic KYC Review Management")
    st.caption(
        "Monitor scheduled reviews, overdue cases and customer risk."
    )

    TODAY = "2026-10-31"

    reviews = query_df("""
        SELECT
            rc.review_id,
            rc.customer_id,
            c.full_name AS customer_name,
            rc.scheduled_date,
            rc.due_date,
            rc.review_status,
            rc.resolution,
            rc.closed_at,
            (
                SELECT rr.risk_level
                FROM risk_ratings rr
                WHERE rr.customer_id = rc.customer_id
                ORDER BY rr.effective_from DESC
                LIMIT 1
            ) AS risk_level,
            CASE
                WHEN rc.review_status IN ('COMPLETED', 'CLOSED')
                    THEN 'COMPLETED'
                WHEN rc.due_date < ?
                    THEN 'OVERDUE'
                WHEN rc.due_date <= date(?, '+30 days')
                    THEN 'DUE SOON'
                ELSE 'ON TRACK'
            END AS review_health
        FROM review_cases rc
        JOIN customers c
            ON c.customer_id = rc.customer_id
        ORDER BY
            CASE
                WHEN rc.review_status NOT IN ('COMPLETED', 'CLOSED')
                     AND rc.due_date < ? THEN 1
                WHEN rc.review_status NOT IN ('COMPLETED', 'CLOSED')
                     AND rc.due_date <= date(?, '+30 days') THEN 2
                ELSE 3
            END,
            rc.due_date
        LIMIT 5000
    """, (TODAY, TODAY, TODAY, TODAY))

    # Summary metrics
    total_reviews = len(reviews)

    def review_count(status):
        return int(
            (reviews["review_health"] == status).sum()
        ) if not reviews.empty else 0

    overdue_count = review_count("OVERDUE")
    due_soon_count = review_count("DUE SOON")
    on_track_count = review_count("ON TRACK")
    completed_count = review_count("COMPLETED")

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Reviews", f"{total_reviews:,}")
    c2.metric("Overdue", f"{overdue_count:,}")
    c3.metric("Due Soon", f"{due_soon_count:,}")

    c4, c5, c6 = st.columns(3)
    c4.metric("On Track", f"{on_track_count:,}")
    c5.metric("Completed / Closed", f"{completed_count:,}")
    c6.metric(
        "Open Reviews",
        f"{overdue_count + due_soon_count + on_track_count:,}"
    )

    if overdue_count:
        st.error(
            f"{overdue_count} review(s) are overdue and require attention."
        )

    st.divider()

    # Search and filters
    st.markdown("### Review Register")

    search_review = st.text_input(
        "Search by review ID, customer ID or customer name",
        key="review_search"
    )

    status_options = sorted(
        reviews["review_status"].dropna().unique().tolist()
    ) if not reviews.empty else []

    selected_review_statuses = st.multiselect(
        "Filter by review status",
        options=status_options,
        default=status_options,
        key="review_status_filter"
    )

    if reviews.empty:
        st.info("No review records found.")
    else:
        filtered_reviews = reviews.copy()

        if search_review.strip():
            search = search_review.strip().lower()

            search_columns = [
                "review_id",
                "customer_id",
                "customer_name"
            ]

            mask = filtered_reviews[search_columns].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(
                    search, regex=False
                )
            ).any(axis=1)

            filtered_reviews = filtered_reviews[mask]

        filtered_reviews = filtered_reviews[
            filtered_reviews["review_status"].isin(
                selected_review_statuses
            )
        ]

        st.caption(
            f"Showing {len(filtered_reviews):,} of {total_reviews:,} reviews."
        )

        st.dataframe(
            filtered_reviews,
            use_container_width=True,
            hide_index=True
        )

        # Export
        st.download_button(
            "Download Review Register (CSV)",
            data=filtered_reviews.to_csv(index=False),
            file_name="kyc_review_register_2026-10-31.csv",
            mime="text/csv",
            key="download_review_register"
        )

        # Review details and closure
        st.divider()
        st.markdown("### Review Case Details")

        review_ids = filtered_reviews["review_id"].tolist()

        if review_ids:
            selected_review_id = st.selectbox(
                "Select a review case",
                review_ids,
                key="selected_review_case"
            )

            selected_review = filtered_reviews[
                filtered_reviews["review_id"] == selected_review_id
            ].iloc[0]

            with st.container(border=True):
                r1, r2, r3 = st.columns(3)

                r1.metric(
                    "Customer",
                    str(selected_review["customer_name"])
                )
                r2.metric(
                    "Risk Level",
                    str(selected_review["risk_level"] or "N/A")
                )
                r3.metric(
                    "Review Health",
                    str(selected_review["review_health"])
                )

                st.write("**Review ID:**", selected_review["review_id"])
                st.write("**Customer ID:**", selected_review["customer_id"])
                st.write("**Scheduled date:**", selected_review["scheduled_date"])
                st.write("**Due date:**", selected_review["due_date"])
                st.write("**Current status:**", selected_review["review_status"])
                st.write(
                    "**Existing resolution:**",
                    selected_review["resolution"] or "Not available"
                )
                st.write(
                    "**Closed at:**",
                    selected_review["closed_at"] or "Not closed"
                )

            # Close review
            if selected_review["review_status"] not in (
                "COMPLETED", "CLOSED"
            ):
                st.markdown("#### Close Review")

                with st.form(
                    "close_review_form",
                    clear_on_submit=True
                ):
                    resolution = st.text_area(
                        "Review resolution",
                        placeholder=(
                            "Enter the findings and actions taken "
                            "during this KYC review."
                        ),
                        key="review_resolution_input"
                    )

                    confirm_close = st.checkbox(
                        "I confirm that this review has been completed.",
                        key="confirm_review_closure"
                    )

                    submit_close = st.form_submit_button(
                        "Close Review",
                        type="primary"
                    )

                    if submit_close:
                        if not resolution.strip():
                            st.error(
                                "A resolution is required before closing."
                            )
                        elif not confirm_close:
                            st.error(
                                "Please confirm completion before closing."
                            )
                        else:
                            try:
                                close_review(
                                    selected_review_id,
                                    resolution
                                )
                                st.success(
                                    f"Review {selected_review_id} closed successfully."
                                )
                                st.rerun()
                            except Exception as e:
                                st.error(f"Could not close review: {e}")
            else:
                st.info("This review is already completed or closed.")

    st.caption(
        "Review health is calculated using the demonstration date "
        "31 October 2026. Closing a review records its resolution "
        "and audit event."
    )


elif page == "Alerts & Exceptions":
    st.subheader("Alerts & Exceptions")
    st.caption(
        "Monitor KYC control failures and prioritize compliance investigations."
    )

    TODAY = "2026-10-31"

    # 1. Expired documents marked as verified
    expired = query_df("""
        SELECT
            d.document_id AS "Record ID",
            d.customer_id AS "Customer ID",
            'Expired document marked verified' AS "Exception",
            'CRITICAL' AS "Priority",
            'Document ' || d.document_id ||
            ' expired on ' || d.expiry_date AS "Details"
        FROM documents d
        JOIN verifications v ON v.document_id = d.document_id
        WHERE v.verification_status = 'VERIFIED'
          AND d.expiry_date IS NOT NULL
          AND d.expiry_date < ?
    """, (TODAY,))

    # 2. Beneficial ownership exceeds 100%
    ownership = query_df("""
        SELECT
            CAST(customer_id AS TEXT) AS "Record ID",
            customer_id AS "Customer ID",
            'Beneficial ownership exceeds 100%' AS "Exception",
            'HIGH' AS "Priority",
            'Total ownership: ' ||
            ROUND(SUM(ownership_percentage), 2) || '%' AS "Details"
        FROM beneficial_owners
        GROUP BY customer_id
        HAVING SUM(ownership_percentage) > 100
    """)

    # 3. Closed reviews without resolution
    unresolved = query_df("""
        SELECT
            review_id AS "Record ID",
            customer_id AS "Customer ID",
            'Closed review without resolution' AS "Exception",
            'MEDIUM' AS "Priority",
            'Review was closed without a resolution.' AS "Details"
        FROM review_cases
        WHERE review_status = 'CLOSED'
          AND (resolution IS NULL OR TRIM(resolution) = '')
    """)

    # 4. Duplicate document references across customers
    duplicate = query_df("""
        SELECT
            d.document_id AS "Record ID",
            d.customer_id AS "Customer ID",
            'Duplicate document reference' AS "Exception",
            'HIGH' AS "Priority",
            'Reference: ' || d.document_reference AS "Details"
        FROM documents d
        JOIN (
            SELECT document_reference
            FROM documents
            WHERE document_reference IS NOT NULL
              AND TRIM(document_reference) <> ''
            GROUP BY document_reference
            HAVING COUNT(DISTINCT customer_id) > 1
        ) duplicates
          ON d.document_reference = duplicates.document_reference
    """)

    # 5. Approved customers missing mandatory KYC evidence
    missing_evidence = query_df("""
        WITH latest_risk AS (
            SELECT customer_id, risk_level
            FROM (
                SELECT
                    customer_id,
                    risk_level,
                    ROW_NUMBER() OVER (
                        PARTITION BY customer_id
                        ORDER BY effective_from DESC
                    ) AS rn
                FROM risk_ratings
            )
            WHERE rn = 1
        ),
        active_requirements AS (
            SELECT
                c.customer_id,
                r.document_type
            FROM customers c
            JOIN latest_risk lr
              ON lr.customer_id = c.customer_id
            JOIN kyc_requirements r
              ON r.customer_type_id = c.customer_type_id
             AND r.risk_level = lr.risk_level
            WHERE c.lifecycle_status = 'APPROVED'
              AND r.mandatory = 1
              AND r.effective_from <= ?
              AND (r.effective_to IS NULL OR r.effective_to >= ?)
        )
        SELECT
            CAST(ar.customer_id AS TEXT) || '-' ||
            ar.document_type AS "Record ID",
            ar.customer_id AS "Customer ID",
            'Approved customer missing mandatory evidence' AS "Exception",
            'CRITICAL' AS "Priority",
            'Missing verified document: ' ||
            ar.document_type AS "Details"
        FROM active_requirements ar
        WHERE NOT EXISTS (
            SELECT 1
            FROM documents d
            JOIN verifications v
              ON v.document_id = d.document_id
            WHERE d.customer_id = ar.customer_id
              AND d.document_type = ar.document_type
              AND d.lifecycle_status = 'VERIFIED'
              AND v.verification_status = 'VERIFIED'
              AND (d.expiry_date IS NULL OR d.expiry_date >= ?)
        )
    """, (TODAY, TODAY, TODAY))

    # 6. Customers with multiple active reviews
    duplicate_reviews = query_df("""
        SELECT
            CAST(customer_id AS TEXT) AS "Record ID",
            customer_id AS "Customer ID",
            'Multiple active reviews' AS "Exception",
            'MEDIUM' AS "Priority",
            'Active review count: ' || COUNT(*) AS "Details"
        FROM review_cases
        WHERE review_status IN ('SCHEDULED', 'IN_PROGRESS', 'OVERDUE')
        GROUP BY customer_id
        HAVING COUNT(*) > 1
    """)

    # 7. Closed reviews missing closure timestamp
    missing_timestamp = query_df("""
        SELECT
            review_id AS "Record ID",
            customer_id AS "Customer ID",
            'Closed review missing timestamp' AS "Exception",
            'MEDIUM' AS "Priority",
            'Closed review has no closed_at value.' AS "Details"
        FROM review_cases
        WHERE review_status = 'CLOSED'
          AND (closed_at IS NULL OR TRIM(closed_at) = '')
    """)

    # Combine exception records
    exceptions = pd.concat(
        [
            expired,
            ownership,
            unresolved,
            duplicate,
            missing_evidence,
            duplicate_reviews,
            missing_timestamp
        ],
        ignore_index=True
    )

    # 2. Summary metrics
    total = len(exceptions)
    critical_count = len(exceptions[exceptions["Priority"] == "CRITICAL"])
    high_count = len(exceptions[exceptions["Priority"] == "HIGH"])
    medium_count = len(exceptions[exceptions["Priority"] == "MEDIUM"])

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Total Exceptions", f"{total:,}")
    col2.metric("Critical", f"{critical_count:,}")
    col3.metric("High Priority", f"{high_count:,}")
    col4.metric("Medium Priority", f"{medium_count:,}")

    st.divider()

    # 3. Exception category summary
    st.markdown("### Exception Breakdown")

    if exceptions.empty:
        st.success("No exceptions detected. All monitored checks are clean.")
    else:
        category_summary = (
            exceptions.groupby("Exception")
            .size()
            .reset_index(name="Count")
            .sort_values("Count", ascending=False)
        )

        st.dataframe(
            category_summary,
            use_container_width=True,
            hide_index=True
        )

        # 4. Filter and investigate
        st.markdown("### Investigation Queue")

        categories = sorted(exceptions["Exception"].unique().tolist())

        selected_categories = st.multiselect(
            "Filter by exception category",
            options=categories,
            default=categories,
            key="exception_category_filter"
        )

        filtered = exceptions[
            exceptions["Exception"].isin(selected_categories)
        ].copy()

        priority_order = {
            "CRITICAL": 0,
            "HIGH": 1,
            "MEDIUM": 2
        }

        filtered["_priority_order"] = filtered["Priority"].map(priority_order)
        filtered = filtered.sort_values(
            ["_priority_order", "Customer ID"]
        ).drop(columns=["_priority_order"])

        st.dataframe(
            filtered,
            use_container_width=True,
            hide_index=True
        )

        # 5. Download investigation report
        st.download_button(
            label="Download Exception Report (CSV)",
            data=filtered.to_csv(index=False),
            file_name="kyc_exception_report_2026-10-31.csv",
            mime="text/csv",
            key="download_kyc_exception_report"
        )

        st.caption(
            "Priority labels are demonstration triage classifications, "
            "not official regulatory severity ratings."
        )

elif page == "Beneficial Owners":
    st.subheader("Beneficial Ownership Management")
    st.caption(
        "Review ultimate beneficial owners, ownership percentages "
        "and verification coverage."
    )

    owners = query_df("""
        SELECT
            bo.owner_id,
            bo.customer_id,
            c.full_name AS customer_name,
            bo.owner_name,
            bo.ownership_percentage,
            bo.is_verified,
            bo.effective_from
        FROM beneficial_owners bo
        JOIN customers c
            ON c.customer_id = bo.customer_id
        ORDER BY bo.customer_id, bo.ownership_percentage DESC
    """)

    if owners.empty:
        st.info("No beneficial-owner records found.")
    else:
        # Normalize verification values for display
        owners["verification_status"] = owners["is_verified"].apply(
            lambda value: (
                "VERIFIED"
                if str(value).strip().lower() in ("1", "true", "yes")
                else "UNVERIFIED"
            )
        )

        total_owners = len(owners)
        verified_owners = int(
            (owners["verification_status"] == "VERIFIED").sum()
        )
        unverified_owners = total_owners - verified_owners

        customer_ownership = (
            owners.groupby(
                ["customer_id", "customer_name"],
                as_index=False
            )
            .agg(
                total_ownership=("ownership_percentage", "sum"),
                owner_count=("owner_id", "count")
            )
        )

        over_100 = int(
            (customer_ownership["total_ownership"] > 100).sum()
        )

        below_100 = int(
            (customer_ownership["total_ownership"] < 100).sum()
        )

        exact_100 = int(
            (customer_ownership["total_ownership"] == 100).sum()
        )

        # Summary metrics
        st.markdown("### Ownership Overview")

        m1, m2, m3, m4 = st.columns(4)

        m1.metric("Total Owners", f"{total_owners:,}")
        m2.metric("Verified Owners", f"{verified_owners:,}")
        m3.metric("Unverified Owners", f"{unverified_owners:,}")
        m4.metric("Ownership Groups Over 100%", f"{over_100:,}")

        st.divider()

        # Ownership group analysis
        st.markdown("### Ownership Group Analysis")

        g1, g2, g3 = st.columns(3)

        g1.metric("Exactly 100%", f"{exact_100:,}")
        g2.metric("Below 100%", f"{below_100:,}")
        g3.metric("Above 100%", f"{over_100:,}")

        if over_100 > 0:
            st.error(
                f"{over_100} customer ownership group(s) exceed 100%. "
                "These require investigation."
            )

        # Ownership distribution chart
        st.markdown("### Ownership Distribution")

        ownership_chart = px.histogram(
            owners,
            x="ownership_percentage",
            nbins=10,
            title="Distribution of Individual Ownership Percentages",
            labels={
                "ownership_percentage": "Ownership Percentage",
                "count": "Number of Owners"
            }
        )

        ownership_chart.update_layout(
            xaxis_title="Ownership Percentage",
            yaxis_title="Number of Owners"
        )

        st.plotly_chart(
            ownership_chart,
            use_container_width=True
        )

        st.divider()

        # Customer ownership totals
        st.markdown("### Customer Ownership Summary")

        ownership_summary = customer_ownership.copy()

        ownership_summary["ownership_check"] = ownership_summary[
            "total_ownership"
        ].apply(
            lambda value: (
                "OVER 100%"
                if value > 100
                else "BELOW 100%"
                if value < 100
                else "100%"
            )
        )

        st.dataframe(
            ownership_summary.sort_values(
                "total_ownership",
                ascending=False
            ),
            use_container_width=True,
            hide_index=True
        )

        # Owner register
        st.divider()
        st.markdown("### Beneficial Owner Register")

        search_owner = st.text_input(
            "Search owner name, customer ID or customer name",
            key="owner_search"
        )

        verification_options = [
            "VERIFIED",
            "UNVERIFIED"
        ]

        selected_verification = st.multiselect(
            "Verification status",
            options=verification_options,
            default=verification_options,
            key="owner_verification_filter"
        )

        filtered_owners = owners[
            owners["verification_status"].isin(selected_verification)
        ].copy()

        if search_owner.strip():
            search = search_owner.strip().lower()

            search_columns = [
                "owner_name",
                "customer_id",
                "customer_name"
            ]

            mask = filtered_owners[search_columns].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(
                    search,
                    regex=False
                )
            ).any(axis=1)

            filtered_owners = filtered_owners[mask]

        st.caption(
            f"Showing {len(filtered_owners):,} of {total_owners:,} owners."
        )

        st.dataframe(
            filtered_owners,
            use_container_width=True,
            hide_index=True
        )

        st.download_button(
            "Download Beneficial Owners Report (CSV)",
            data=filtered_owners.to_csv(index=False),
            file_name="kyc_beneficial_owners_2026-10-31.csv",
            mime="text/csv",
            key="download_beneficial_owners"
        )

    st.caption(
        "Ownership percentages are summed by customer. "
        "A total below 100% may indicate missing ownership information "
        "and should be reviewed against the applicable policy."
    )



elif page == "Audit Trail":
    st.subheader("Audit Trail & Activity Monitoring")
    st.caption(
        "Review recorded system actions and customer-level activity."
    )

    audit = query_df("""
        SELECT
            ae.audit_event_id,
            ae.customer_id,
            c.full_name AS customer_name,
            ae.entity_type,
            ae.entity_id,
            ae.action,
            ae.old_value,
            ae.new_value,
            ae.actor,
            ae.event_timestamp
        FROM audit_events ae
        LEFT JOIN customers c
            ON c.customer_id = ae.customer_id
        ORDER BY ae.event_timestamp DESC, ae.audit_event_id DESC
        LIMIT 10000
    """)

    if audit.empty:
        st.info("No audit events are available.")
    else:
        # Summary metrics
        total_events = len(audit)
        unique_actors = audit["actor"].nunique()
        unique_customers = audit["customer_id"].nunique()
        unique_actions = audit["action"].nunique()

        a1, a2, a3, a4 = st.columns(4)

        a1.metric("Total Events", f"{total_events:,}")
        a2.metric("Unique Actors", f"{unique_actors:,}")
        a3.metric("Customers Affected", f"{unique_customers:,}")
        a4.metric("Action Types", f"{unique_actions:,}")

        st.divider()

        # Search
        st.markdown("### Search Audit Events")

        audit_search = st.text_input(
            "Search event ID, customer ID, customer name, actor or action",
            key="audit_search"
        )

        # Entity filter
        entity_options = sorted(
            audit["entity_type"].dropna().unique().tolist()
        )

        selected_entities = st.multiselect(
            "Filter by entity type",
            options=entity_options,
            default=entity_options,
            key="audit_entity_filter"
        )

        # Action filter
        action_options = sorted(
            audit["action"].dropna().unique().tolist()
        )

        selected_actions = st.multiselect(
            "Filter by action",
            options=action_options,
            default=action_options,
            key="audit_action_filter"
        )

        filtered_audit = audit.copy()

        filtered_audit = filtered_audit[
            filtered_audit["entity_type"].isin(selected_entities)
            & filtered_audit["action"].isin(selected_actions)
        ]

        if audit_search.strip():
            search = audit_search.strip().lower()

            search_columns = [
                "audit_event_id",
                "customer_id",
                "customer_name",
                "actor",
                "action",
                "entity_type",
                "entity_id"
            ]

            mask = filtered_audit[search_columns].fillna("").astype(str).apply(
                lambda column: column.str.lower().str.contains(
                    search, regex=False
                )
            ).any(axis=1)

            filtered_audit = filtered_audit[mask]

        st.markdown("### Audit Event Register")

        st.caption(
            f"Showing {len(filtered_audit):,} of "
            f"{total_events:,} events."
        )

        st.dataframe(
            filtered_audit,
            use_container_width=True,
            hide_index=True
        )

        # CSV export
        st.download_button(
            "Download Audit Trail (CSV)",
            data=filtered_audit.to_csv(index=False),
            file_name="kyc_audit_trail_2026-10-31.csv",
            mime="text/csv",
            key="download_audit_trail"
        )

        # Customer activity history
        st.divider()
        st.markdown("### Customer Activity History")

        customer_options = (
            audit.dropna(subset=["customer_id"])
            [["customer_id", "customer_name"]]
            .drop_duplicates()
            .sort_values("customer_id")
        )

        if not customer_options.empty:
            selected_customer = st.selectbox(
                "Select customer",
                customer_options["customer_id"].tolist(),     
                format_func=lambda x: (
                    f"{x} — {customer_options.loc[customer_options['customer_id'] == x, 'customer_name'].iloc[0]}"
                ),
                key="audit_customer_selector"
            )

            customer_history = audit[
                audit["customer_id"] == selected_customer
            ].copy()

            st.caption(
                f"{len(customer_history):,} recorded events for "
                f"customer {selected_customer}."
            )

            st.dataframe(
                customer_history,
                use_container_width=True,
                hide_index=True
            )

    st.caption(
        "This page displays recorded audit events. "
        "The current demonstration audit log is not tamper-proof."
    )
elif page == "System Information":
    st.subheader("System Information")
    st.caption("Application configuration, database health, and dataset overview.")

    st.markdown("### Application Details")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Application", "KYC Compliance Platform")

    with col2:
        st.metric("Technology", "Python + Streamlit")

    with col3:
        st.metric("Database", "SQLite")

    st.divider()

    st.markdown("### Database Health")

    try:
        with get_connection() as conn:
            sqlite_version = conn.execute(
                "SELECT sqlite_version()"
            ).fetchone()[0]

            table_names = [
                row["name"]
                for row in conn.execute("""
                    SELECT name
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """).fetchall()
            ]

            st.success("Database connection successful.")

            col1, col2 = st.columns(2)

            with col1:
                st.metric("SQLite Version", sqlite_version)

            with col2:
                st.metric("Database Tables", len(table_names))

            st.markdown("### Database Record Counts")

            counts = []

            for table_name in table_names:
                count = conn.execute(
                    f'SELECT COUNT(*) AS total FROM "{table_name}"'
                ).fetchone()["total"]

                counts.append({
                    "Table Name": table_name,
                    "Record Count": count
                })

            counts_df = pd.DataFrame(counts)

            st.dataframe(
                counts_df,
                use_container_width=True,
                hide_index=True
            )

            st.metric(
                "Total Database Records",
                int(counts_df["Record Count"].sum())
            )

    except Exception as error:
        st.error(f"Database connection failed: {error}")

    st.divider()

    st.markdown("### Platform Components")

    components = pd.DataFrame([
        {"Component": "Customer Management", "Purpose": "Customer onboarding and profiles"},
        {"Component": "Document Management", "Purpose": "KYC document tracking"},
        {"Component": "Verification", "Purpose": "Evidence verification records"},
        {"Component": "Risk Management", "Purpose": "Customer risk classification"},
        {"Component": "Review Management", "Purpose": "Periodic KYC reviews"},
        {"Component": "Beneficial Ownership", "Purpose": "Ownership tracking"},
        {"Component": "Alerts & Exceptions", "Purpose": "Data quality exception monitoring"},
        {"Component": "Audit Trail", "Purpose": "Activity and change history"},
        {"Component": "Data Validation", "Purpose": "Structural and business rule checks"}
    ])

    st.dataframe(
        components,
        use_container_width=True,
        hide_index=True
    )

    st.caption(
        "Demonstration environment | Synthetic data only | "
        "Reference date: 31 October 2026"
    )


elif page == "Data & Validation":
    st.subheader("Dataset Information")

    st.info(
        "The dashboard is connected to the pre-generated full assignment "
        "dataset. Dataset generation is disabled to protect existing records."
    )

    st.write("**Active database**")
    st.code(str(DB_PATH))

    st.write("**Full assignment dataset volume**")

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Customers", "8,000")
    col2.metric("Documents", "20,000")
    col3.metric("Businesses", "1,000")
    col4.metric("Reviews", "3,000")

    st.divider()

    st.subheader("Data Quality and Validation")

    if st.button("Run validation", key="run_data_validation"):
        with st.spinner("Validating the full dataset..."):
            result = run_validation(
                db_path=DB_PATH,
                dataset_dir=(
                    BASE_DIR / "test_artifacts" / "full" / "datasets"
                ),
                report_dir=(
                    BASE_DIR / "test_artifacts" / "full" / "reports"
                )
            )

        if result["structural_status"] == "PASSED":
            st.success("Structural Integrity: PASSED")
        else:
            st.error("Structural Integrity: FAILED")

        if result["business_status"] == "EXPECTED_EXCEPTIONS_ONLY":
            st.success("Business Rule Validation: EXPECTED EXCEPTIONS ONLY")
        elif result["business_status"] == "CLEAN":
            st.success("Business Rule Validation: CLEAN")
        else:
            st.warning("Business Rule Validation: EXCEPTIONS FOUND")

        if result["validation_passed"]:
            st.success("Overall Validation: PASSED")
        else:
            st.error("Overall Validation: FAILED")

        st.json(result)

    # Previous generation report
    summary_path = (
        BASE_DIR
        / "test_artifacts"
        / "full"
        / "reports"
        / "generation_summary.json"
    )

    if summary_path.exists():
        st.markdown("**Full dataset generation summary**")
        st.json(json.loads(summary_path.read_text(encoding="utf-8")))

    st.markdown("**Output folders**")
    st.code(
        "test_artifacts/full/datasets/  -> CSV and JSON exports\n"
        "test_artifacts/full/reports/   -> Generation and validation reports\n"
        "test_artifacts/full/data/      -> SQLite database"
    )

st.divider()
st.caption("KYC Evidence Management MVP · Synthetic data only · Demonstration date: 31 October 2026")
