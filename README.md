# KYC Onboarding Evidence Management System

A Python-based **Know Your Customer (KYC) Onboarding and Evidence Management System** built with Streamlit and SQLite. This prototype demonstrates customer onboarding, document verification, KYC completeness assessment, risk-based reviews, expiry monitoring, audit history, and business-exception detection using deterministic synthetic data.

## 1. Business Objective

Financial institutions must collect and verify customer identity evidence, monitor document validity, assess onboarding completeness, and conduct periodic KYC reviews.

This project demonstrates a practical workflow for:

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
| Synthetic data generation | Faker |
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

### Full Assignment Dataset

| Entity | Generated Records |
|---|---:|
| Customers | 8,000 |
| Documents | 20,000 |
| Verifications | 20,000 |
| Risk Ratings | 8,000 |
| Review Cases | 3,000 |
| Beneficial Owners | 1,988 |
| Alerts | 202 |
| Audit Events | 31,123 |
| Customer Types | 2 |
| KYC Requirements | 24 |

**Dataset configuration:**

- Random seed: `20261022`
- Demonstration date: `2026-10-31`
- Data provenance: Synthetic records generated using Faker.
- Generation supports configurable customer, document, business-customer, and review volumes.

All records are synthetic and intended for demonstration and testing, not actual customer onboarding.

## 5. Business Rules

The prototype implements example KYC controls:

- Mandatory document requirements vary by customer type and risk level.
- KYC completeness is calculated using required evidence and its latest verification status.
- Customer approval requires complete mandatory evidence.
- Review scheduling follows risk-based intervals.
- Expired documents are excluded from valid evidence.
- Review closure requires the applicable review conditions to be satisfied.
- Business exceptions are detected and reported against expected exception scenarios.
- Audit events maintain a history of relevant system activities.

## 6. Application Features

- Customer onboarding and record management.
- Document and verification tracking.
- KYC completeness assessment.
- Risk rating and review monitoring.
- Expiry alerts and exception reporting.
- Audit history.
- Dataset statistics and validation results.
- Interactive dashboards and visualizations.

## 7. Project Structure

```text
kyc-onboarding-system/
│
├── app.py
├── database.py
├── business_rules.py
├── generator.py
├── validation.py
├── requirements.txt
├── README.md
│
├── data/
├── datasets/
├── reports/
├── src/
└── test_artifacts/
    └── full/
        ├── datasets/
        └── reports/
```

The SQLite database is generated or maintained locally and is not necessarily included in the GitHub repository.

## 8. Installation and Setup

### Prerequisites

Install the following before running the project:

- Python 3.10 or later
- pip (Python package installer)
- Git (optional, for cloning the repository)

Check your Python installation:

```powershell
python --version
pip --version
```

### Step 1: Clone the Repository

```powershell
git clone https://github.com/Srija-154/kyc-onboarding-evidence-management.git
```

Navigate into the project folder:

```powershell
cd kyc-onboarding-evidence-management
```

### Step 2: Create a Virtual Environment

```powershell
python -m venv venv
```

### Step 3: Activate the Virtual Environment

For Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

If PowerShell blocks script execution, run:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Then activate again:

```powershell
.\venv\Scripts\Activate.ps1
```

### Step 4: Install Dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Step 5: Run the Application

From the project root directory:

```powershell
streamlit run app.py
```

The application will normally open in your browser at:

```text
http://localhost:8501
```

If it does not open automatically, copy the URL into your browser.

### Step 6: Stop the Application

To stop the Streamlit server, press:

```text
Ctrl + C
```

## 9. Database and Dataset Notes

- The application uses SQLite for local data storage.
- The database location can be configured using the `KYC_DB_PATH` environment variable.
- The full assignment database and generated test outputs are maintained separately from the source code.
- The full test database used during development is located at:

```text
test_artifacts/full/data/kyc_full_test.db
```

**Important:** Local SQLite databases are excluded from the Git repository to avoid committing generated database files or potentially sensitive records. A fresh clone therefore needs the required dataset/database to be generated or supplied using the project's data-generation workflow before the full dataset dashboard can display the assignment records.

## 10. Validation and Testing

The full assignment dataset was checked using structural and business-rule validation.

### Validation Results

| Validation Check | Result |
|---|---|
| Structural Integrity | PASSED |
| Business Rule Validation | EXPECTED EXCEPTIONS ONLY |
| Overall Validation | PASSED |
| Foreign Key Violations | 0 |
| Unexpected Business Exceptions | 0 |

Five labelled expected business exceptions were detected and matched against the ground-truth cases. No unexpected business exceptions were identified.

Database verification:

- Customers: 8,000
- Documents: 20,000
- Review Cases: 3,000
- Foreign key violations: 0

## 11. Project Purpose

This project was developed as a practical demonstration of KYC onboarding workflows, relational database management, business-rule implementation, data validation, compliance monitoring, and interactive reporting.

It uses synthetic data and simplified example controls. It is an educational prototype, not a production-ready banking compliance platform or a substitute for regulatory review.

## 12. Author

**Srija Aruri**

GitHub: https://github.com/Srija-154

LinkedIn: https://linkedin.com/in/srija-aruri

---

*Built using Python, Streamlit, SQLite, Pandas, Plotly, and Faker.*