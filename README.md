> **Status:** Alpha
>
> This is an educational prototype and is not intended for real banking or financial use.

# BankAccount Web App

## Project Overview

This is a small **educational** banking web application. It exists to demonstrate, in a way a beginner can follow end to end, how a real web application's pieces fit together: a browser-based frontend, a REST-style API, a business-logic layer, and file-based persistence.

**This is not a real banking system.** It has no authentication, no database, and no real financial or security guarantees. Its only job is to teach the relationship between these layers clearly.

## Architecture

```text
Frontend (HTML/CSS/JavaScript)
        |
        |  HTTP requests (fetch), JSON bodies
        v
Flask API (backend/app.py)
        |
        |  plain Python method calls
        v
AccountManager (app/account_manager.py)
        |
        v
BankAccount (core/bank_account.py)
        |
        v
JSON Storage (storage/account_storage.py -> accounts.json)
```

For production deployment, `wsgi.py` acts as the WSGI entry point used by Gunicorn. It creates the Flask application by calling the same `create_app()` factory defined in `backend/app.py`.

Each layer has exactly one job, and only talks to the layer directly below it:

* **Frontend** — everything the user sees and clicks. It never touches storage or business rules directly; it only ever sends HTTP requests to the API and displays whatever comes back.

* **Flask API (backend)** — receives HTTP requests, checks that the request itself is well-formed (right fields, right types), calls into `AccountManager`, and turns the result (or an error) into an HTTP response. It contains no banking rules of its own.

* **AccountManager (app layer)** — keeps track of all accounts while the app is running, and is the one place that coordinates `BankAccount` (the business logic) with `account_storage` (the persistence). It loads accounts once at startup and saves after every successful change.

* **BankAccount (core/business logic)** — the actual banking rules: creating an account, depositing, withdrawing, transferring, and rejecting invalid operations (bad amounts, insufficient balance, transferring to yourself). This layer knows nothing about HTTP, JSON files, or the browser — it's plain Python that could be reused anywhere.

* **JSON Storage** — reads and writes `accounts.json` on disk. It doesn't know or care what a "valid deposit" is; its only job is to load and save data reliably.

## Technologies

* **Python** — the whole backend and business logic
* **Flask** — the web framework serving both the API and the frontend
* **HTML / CSS / JavaScript** (no frameworks, no build step) — the frontend
* **JSON** — the persistence format (`accounts.json`), and the API's request/response format
* **Gunicorn** — the production WSGI server used to run the Flask application on deployment platforms such as Render
* **pytest** — the automated test suites for each layer
* **requests** and **Playwright** (optional, dev-only) — used by the full-system tests in `tests/` to drive the real app over real HTTP and a real headless browser

No database, no frontend framework, and no authentication system are used — this is intentional (see Project Overview). Gunicorn is used only for production deployment; local development still uses Flask's development server.

## Requirements

* Python 3.10+
* Flask
* Gunicorn (for production deployment)

Development and testing dependencies are listed separately in `requirements-dev.txt`.

## Installation

From the project root, ideally inside a virtual environment:

```bash
pip install -r requirements.txt
```

To also run the automated test suites:

```bash
pip install -r requirements-dev.txt
```

The `requests` and `playwright` entries in `requirements-dev.txt` are only needed for the optional full-system tests in `tests/`.

## Running the Application

### Local development

From the project root:

```bash
python backend/app.py
```

This starts the Flask development server at `http://127.0.0.1:5000/`, loading (or creating) `accounts.json` in the project root.

Then open `http://127.0.0.1:5000/` in a browser. Flask serves the frontend itself, so there is nothing else to start.

The page stays loaded the whole time (it's a Single Page Application): creating accounts, depositing, withdrawing, and transferring all happen without navigating to a different page. The browser's JavaScript talks to the API with `fetch()` calls to the same origin that served the page, so no CORS configuration is needed.

By default, debug mode is **off**. For local development, you can explicitly enable it.

On Linux/macOS:

```bash
FLASK_DEBUG=1 python backend/app.py
```

On Windows PowerShell:

```powershell
$env:FLASK_DEBUG="1"
python backend/app.py
```

### Production deployment

For production deployment, the application is served by Gunicorn through `wsgi.py`.

The production start command is:

```bash
gunicorn --bind 0.0.0.0:$PORT wsgi:app
```

`wsgi.py` is a deployment entry point. It imports the `create_app()` factory from `backend/app.py`, provides the storage path for `accounts.json`, and exposes the resulting Flask application to Gunicorn.

On platforms such as Render, `$PORT` is provided by the platform and the application must bind to `0.0.0.0`.

## Deployment

The application can be deployed as a Python web service on platforms that support Flask and Gunicorn.

### Render

For Render, use:

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
gunicorn --bind 0.0.0.0:$PORT wsgi:app
```

The `wsgi.py` file is included in the repository so that the deployment platform can create the Flask application without modifying the application code in `backend/app.py`.

### File-based storage on Render

This project uses `accounts.json` as a simple educational storage layer.

On Render, the default filesystem is **ephemeral**. Changes made to local files can be lost when a service restarts, redeploys, or a Free Web Service spins down. Therefore, `accounts.json` should **not** be considered persistent production storage when running on the default Render filesystem.

This limitation is acceptable for this educational prototype. A real application would use a proper persistent datastore instead.

## Testing

Each layer has its own `pytest` suite next to its code:

```bash
cd core && python -m pytest test_bank_account.py -v
cd storage && python -m pytest test_account_storage.py -v
cd app && python -m pytest test_account_manager.py -v
cd backend && python -m pytest test_backend.py -v
```

What each covers:

* **core** — the banking rules themselves: account creation, deposit, withdrawal, transfer, validation, insufficient balance, self-transfer, and independence between accounts.

* **storage** — reading/writing `accounts.json`: saving, loading, handling a missing or corrupted file, account-number continuity, and atomic writes.

* **app (AccountManager)** — that Core and Storage are wired together correctly: loading at startup, persisting only after a successful operation, and ensuring a failed operation never touches the saved file.

* **backend** — the HTTP layer: every endpoint's status codes, JSON response shape, input validation, and error mapping; also confirms the frontend is served correctly from the same Flask app.

`tests/` holds full-system tests that exercise the whole running application together, rather than one layer in isolation:

* `test_full_system_restart.py` — starts the real app as a subprocess, drives it over real HTTP, restarts it, and confirms data and account numbering survive an actual process restart. Needs `requests`.

* `test_browser_playwright.py` — drives the real UI in a headless browser (create accounts, deposit, withdraw, transfer, trigger errors, and refresh the page) using [Playwright](https://playwright.dev/python/). Needs `pip install playwright && playwright install chromium`.

Run either directly, for example:

```bash
python tests/test_full_system_restart.py
```

**Testing environment limitations:** this project was developed in a sandbox with no network access, so `pytest` itself could not always be installed there — plain-assertion runner scripts (`manual_test_run*.py`, alongside each `test_*.py`) were used as a stand-in in that environment and mirror the pytest files one-to-one. In a normal development environment with internet access, just use `pytest` directly as shown above.

## API

The backend exposes a small REST-style JSON API:

| Method | Path                                         | Purpose                       |
| ------ | -------------------------------------------- | ----------------------------- |
| `POST` | `/accounts`                                  | Create an account             |
| `GET`  | `/accounts`                                  | List all accounts             |
| `GET`  | `/accounts/<account_number>`                 | Get one account               |
| `POST` | `/accounts/<account_number>/deposit`         | Deposit money                 |
| `POST` | `/accounts/<account_number>/withdraw`        | Withdraw money                |
| `POST` | `/accounts/<source_account_number>/transfer` | Transfer between two accounts |

Every response is JSON, either `{"data": ...}` on success or `{"error": {"code": ..., "message": ...}}` on failure.

For full request/response examples, field types, and every possible error code and status, see [API_CONTRACT.md](./API_CONTRACT.md).

## Project Structure

```text
core/                  BankAccount business logic - no HTTP, no files, no terminal I/O
storage/               JSON persistence - reads/writes accounts.json
app/                   AccountManager - connects Core + Storage for the app to use
backend/               Flask API + frontend serving
frontend/              HTML/CSS/vanilla JS Single Page Application
tests/                 Full-system tests that span more than one layer
wsgi.py                WSGI entry point for production deployment
accounts.json          File-based application data (created/updated at runtime)
API_CONTRACT.md        Full API reference
requirements.txt       Runtime dependencies (Flask + Gunicorn)
requirements-dev.txt   Development and testing dependencies
```
