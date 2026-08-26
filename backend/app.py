"""
Backend for the BankAccount web application (Tasks 3.1 + 3.2).

Framework: Flask.

Layering:

    HTTP request
         |
         v
    Route function (this file)      <- HTTP layer: parse/validate the
         |                             request shape, translate results
         |                             and errors into HTTP responses
         v
    AccountManager                  <- application/integration layer
         |
         v
    BankAccount / Storage           <- already implemented (Tasks 1.x/2.x)

Route functions never touch account_storage.py or the JSON file directly,
and never implement banking rules themselves - they only ever call methods
on `app.account_manager`.

See API_CONTRACT.md for the full documented contract (this file implements it).
"""

from __future__ import annotations

import math
import os
import sys

# Make the previously-built layers importable. This project doesn't have a
# packaging setup (setup.py/pyproject.toml) yet, so each layer currently
# lives in its own flat folder - this mirrors the same approach already
# used by the Task 2.x test suites. A later task could turn this into a
# proper installable package if the project grows further.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _subdir in ("core", "storage", "app"):
    _path = os.path.join(_PROJECT_ROOT, _subdir)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from bank_account import InvalidAmountError, InsufficientBalanceError, SelfTransferError
from account_manager import AccountManager, AccountNotFoundError
from account_storage import StorageError

_FRONTEND_DIR = os.path.join(_PROJECT_ROOT, "frontend")


class BadRequestError(Exception):
    """Raised when the incoming HTTP request itself is structurally invalid
    (missing field, wrong basic type) - a client/request problem, distinct
    from a business-rule failure raised by the Core."""


def create_app(storage_path: str | os.PathLike) -> Flask:
    """
    Application factory.

    Initializes AccountManager exactly once (at startup), loading whatever
    exists at `storage_path`. If the storage file is missing, this starts
    with an empty account collection. If the storage file exists but is
    corrupted/invalid, AccountManager's constructor raises immediately -
    that exception is NOT caught here, so a broken data file causes
    startup to fail loudly rather than silently serving an empty app.
    """
    # `static_folder`/`static_url_path` make everything under frontend/css
    # and frontend/js reachable at /static/css/... and /static/js/... .
    # index.html itself is served separately below at "/", not under
    # /static, so the app's URL is just "/" rather than "/static/index.html".
    app = Flask(__name__, static_folder=_FRONTEND_DIR, static_url_path="/static")

    # Initialized once here, not per-request - the same AccountManager
    # instance (and its in-memory account collection) is reused for every
    # request this app handles.
    app.account_manager = AccountManager(storage_path)

    # ------------------------------------------------------------------
    # Frontend - served by this same Flask app/origin, so the frontend's
    # fetch() calls to /accounts etc. are same-origin requests and no CORS
    # configuration is needed (see Task 4.1 scope).
    # ------------------------------------------------------------------

    @app.route("/")
    def index():
        return send_from_directory(_FRONTEND_DIR, "index.html")

    # ------------------------------------------------------------------
    # Response helpers - keep the JSON envelope consistent everywhere.
    #
    # Success:  {"data": <resource or list of resources>}
    # Error:    {"error": {"code": "<machine_readable_code>", "message": "<human readable>"}}
    # ------------------------------------------------------------------

    def success(data, status: int = 200):
        return jsonify({"data": data}), status

    def error(code: str, message: str, status: int):
        return jsonify({"error": {"code": code, "message": message}}), status

    # ------------------------------------------------------------------
    # Error handling - translate application/Core/Storage exceptions into
    # HTTP responses. The client never sees a Python traceback.
    # ------------------------------------------------------------------

    @app.errorhandler(BadRequestError)
    def _handle_bad_request(exc: BadRequestError):
        return error("bad_request", str(exc), 400)

    @app.errorhandler(AccountNotFoundError)
    def _handle_account_not_found(exc: AccountNotFoundError):
        return error("account_not_found", str(exc), 404)

    @app.errorhandler(InvalidAmountError)
    def _handle_invalid_amount(exc: InvalidAmountError):
        return error("invalid_amount", str(exc), 422)

    @app.errorhandler(InsufficientBalanceError)
    def _handle_insufficient_balance(exc: InsufficientBalanceError):
        return error("insufficient_balance", str(exc), 422)

    @app.errorhandler(SelfTransferError)
    def _handle_self_transfer(exc: SelfTransferError):
        return error("self_transfer", str(exc), 422)

    @app.errorhandler(StorageError)
    def _handle_storage_error(exc: StorageError):
        # Storage problems are a server-side/infrastructure failure, not the
        # client's fault - respond 503, and don't leak file paths or
        # exception internals to the client.
        app.logger.exception("Storage error while handling request")
        return error("storage_error", "A storage error occurred. Please try again later.", 503)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException):
        # Werkzeug/Flask raise their own HTTPExceptions for things this app
        # never explicitly checks for - an unmatched route (e.g. a
        # non-integer account number segment, or a typo'd path), a wrong
        # HTTP method, etc. Without this handler, Flask's built-in Exception
        # MRO would let the generic `Exception` handler below catch these
        # too and misreport them as 500 internal_error, which is both the
        # wrong status code and a misleading error code. This handler keeps
        # Werkzeug's own status code (404, 405, ...) but still returns our
        # consistent JSON envelope instead of Werkzeug's default HTML page.
        code = (exc.name or "http_error").lower().replace(" ", "_")
        return error(code, exc.description or str(exc), exc.code or 500)

    @app.errorhandler(Exception)
    def _handle_unexpected_error(exc: Exception):
        app.logger.exception("Unexpected error while handling request")
        return error("internal_error", "An unexpected error occurred.", 500)

    # ------------------------------------------------------------------
    # Request-shape validation helpers (HTTP layer's job: "is this request
    # well-formed?" - NOT "is this a valid banking operation?", which stays
    # the Core's job).
    #
    # Numeric field decision (Task 3.2, resolves the Task 3.1 limitation):
    # a valid "amount" is a JSON number - int or float - and NOTHING else.
    #   100      -> accepted
    #   100.5    -> accepted
    #   "100"    -> rejected (400) - no numeric strings are coerced
    #   true     -> rejected (400) - bool is technically an int in Python,
    #               explicitly excluded so true/false can never mean 1/0
    #   null     -> rejected (400) - missing value, not a number
    #   NaN/Infinity -> rejected (400) - not a valid financial amount, even
    #               though Python's json module can parse these tokens
    # This same helper is used by deposit, withdraw, and transfer, so the
    # rule is identical across all three endpoints.
    # ------------------------------------------------------------------

    def require_json_object() -> dict:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise BadRequestError("Request body must be a JSON object")
        return payload

    def require_string_field(payload: dict, field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or value.strip() == "":
            raise BadRequestError(f"'{field}' is required and must be a non-empty string")
        return value

    def require_numeric_field(payload: dict, field: str) -> float:
        value = payload.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BadRequestError(f"'{field}' is required and must be a number")
        if not math.isfinite(value):
            raise BadRequestError(f"'{field}' must be a finite number")
        return value

    def require_int_field(payload: dict, field: str) -> int:
        value = payload.get(field)
        if not isinstance(value, int) or isinstance(value, bool):
            raise BadRequestError(f"'{field}' is required and must be an integer")
        return value

    # ------------------------------------------------------------------
    # Routes - see API_CONTRACT.md for the full documented contract.
    # ------------------------------------------------------------------

    @app.route("/accounts", methods=["POST"])
    def create_account():
        payload = require_json_object()
        name = require_string_field(payload, "name")
        account = app.account_manager.create_account(name)
        return success(account.to_dict(), status=201)

    @app.route("/accounts", methods=["GET"])
    def list_accounts():
        accounts = app.account_manager.all_accounts()
        return success([account.to_dict() for account in accounts])

    @app.route("/accounts/<int:account_number>", methods=["GET"])
    def get_account(account_number: int):
        account = app.account_manager.get_account(account_number)
        return success(account.to_dict())

    @app.route("/accounts/<int:account_number>/deposit", methods=["POST"])
    def deposit(account_number: int):
        payload = require_json_object()
        amount = require_numeric_field(payload, "amount")
        account = app.account_manager.deposit(account_number, amount)
        return success(account.to_dict())

    @app.route("/accounts/<int:account_number>/withdraw", methods=["POST"])
    def withdraw(account_number: int):
        payload = require_json_object()
        amount = require_numeric_field(payload, "amount")
        account = app.account_manager.withdraw(account_number, amount)
        return success(account.to_dict())

    @app.route("/accounts/<int:account_number>/transfer", methods=["POST"])
    def transfer(account_number: int):
        payload = require_json_object()
        destination_account_number = require_int_field(payload, "destination_account_number")
        amount = require_numeric_field(payload, "amount")
        # All banking rules (self-transfer, invalid amount, insufficient
        # balance, either account missing) are enforced inside
        # AccountManager.transfer / BankAccount.transfer_to - this route
        # does not duplicate or pre-check any of them.
        source, destination = app.account_manager.transfer(
            account_number, destination_account_number, amount
        )
        return success({"source": source.to_dict(), "destination": destination.to_dict()})

    return app


if __name__ == "__main__":
    default_storage_path = os.path.join(_PROJECT_ROOT, "accounts.json")
    flask_app = create_app(default_storage_path)
    # Debug mode is OFF by default: Flask's debugger, if left on, lets
    # anyone who can reach the app execute arbitrary code through the
    # browser after an unhandled exception. Set FLASK_DEBUG=1 in the
    # environment for local development if you want debug mode/auto-reload.
    debug_mode = os.environ.get("FLASK_DEBUG") == "1"
    flask_app.run(debug=debug_mode)
