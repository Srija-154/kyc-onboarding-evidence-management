# KYC Onboarding Evidence Management System

A Python-based KYC (Know Your Customer) onboarding and evidence management prototype built with Streamlit and SQLite. The system demonstrates customer onboarding, document verification, KYC completeness assessment, risk-based reviews, expiry monitoring, audit history, and business-exception detection using deterministic synthetic data.

## 1. Business Objective

Financial institutions need to collect and verify customer identity evidence, monitor document validity, assess onboarding completeness, and conduct periodic KYC reviews.

This project demonstrates a workflow for:

- Managing individual and business customer records.
- Defining mandatory evidence requirements based on customer type and risk.
- Recording document submissions and verification outcomes.
- Calculating KYC completeness.
- Applying approval controls.
- Scheduling risk-based periodic reviews.
- Detecting expired documents and generating alerts.
- Maintaining audit events and review history.
- Identifying and reporting data-quality and compliance exceptions.

## 2. Technology Stack

| Component | Technology |
|---|---|
| Programming language | Python |
| User interface | Streamlit |
| Database | SQLite |
| Data processing | Pandas |
| Data visualization | Plotly |
| Synthetic data | Faker |
| Validation | Python and SQLite queries |

## 3. Database Entities

The database contains ten core entities:

1. Customer
2. Customer Type
3. KYC Requirement
4. Document
5. Verification
6. Risk Rating
7. Review Case
8. Beneficial Owner
9. Alert
10. Audit Event

Primary keys and foreign keys establish relationships between customers, documents, verifications, reviews, risk ratings, and related records.

## 4. Dataset Generation

The project includes a deterministic synthetic-data generator.

**Full assignment dataset:**

| Entity | Generated records |
|---|---:|
| Customers | 8,000 |
| Documents | 20,000 |
| Verifications | 20,000 |
| Risk ratings | 8,000 |
| Review cases | 3,000 |
| Beneficial owners | 1,988 |
| Alerts | 202 |
| Audit events | 31,123 |
| Customer types | 2 |
| KYC requirements | 24 |

- Random seed: `20261022`
- Demonstration date: `2026-10-31`
- Data provenance: Synthetic records generated using Faker.
- Generation supports configurable customer, document, business-customer, and review volumes.

## 5. Business Rules

The prototype implements the following example rules:

- Mandatory document requirements vary by customer type and risk level.
- KYC completeness is calculated from required evidence and its latest verification status.
- Customer approval requires complete mandatory evidence.
- Review scheduling follows risk-based intervals.
- Expired documents are excluded from valid evidence.
- Review closure requires a