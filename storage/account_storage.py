"""
JSON persistence layer for the BankAccount web application.

Responsibilities of this module (and only this module):
    - Reading the JSON file from disk
    - Writing the JSON file to disk
    - Validating the *structure* of stored data (right keys, right types,
      no duplicate account numbers)
    - Converting validated raw data into BankAccount objects (by delegating
      to BankAccount.from_dict - see bank_account.py) and back into plain
      dicts (via BankAccount.to_dict)

This module does NOT:
    - Decide whether a deposit/withdrawal amount is valid (that's the Core)
    - Know about HTTP, the API, or the frontend

JSON file structure
--------------------
{
    "accounts": [
        {"account_number": 1000, "name": "Alice", "balance": 100.0},
        {"account_number": 1001, "name": "Bob",   "balance": 50.0}
    ]
}

The top level is a dict (not a bare list) so that new top-level keys -
e.g. a schema "version", or later a "transactions" section - can be added
without breaking existing files. Each account record is a flat dict of its
own; a later task could add a "transactions": [...] field to an individual
record without redesigning the overall structure.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from bank_account import BankAccount


# ----------------------------------------------------------------------
# Storage-specific errors (distinct from business errors in bank_account.py)
# ----------------------------------------------------------------------

class StorageError(Exception):
    """Base class for all storage-layer problems (I/O or data problems)."""


class StorageReadError(StorageError):
    """Raised when the storage file exists but cannot be read as valid JSON."""


class InvalidStorageDataError(StorageError):
    """Raised when the JSON is syntactically valid but its content doesn't
    match the expected account structure (missing/wrong-type fields,
    invalid values, duplicate account numbers, etc.)."""


class StorageWriteError(StorageError):
    """Raised when writing the storage file fails."""


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------

def load_accounts(path: str | os.PathLike) -> list[BankAccount]:
    """
    Load accounts from the JSON file at `path`.

    Behavior:
        - Missing file            -> returns [] (treated as a fresh install,
                                      not an error).
        - Empty/invalid JSON text -> raises StorageReadError. We do NOT
                                      silently treat unreadable data as "no
                                      accounts", since that could look like
                                      we quietly threw away existing data.
        - Valid JSON, but the account records don't match the expected
          shape (missing fields, wrong types, invalid values, duplicate
          account numbers) -> raises InvalidStorageDataError.

    On success, returns a list of BankAccount objects reconstructed via
    BankAccount.from_dict, with the Core's class-level account-number
    bookkeeping already brought up to date (see from_dict's docstring).
    """
    file_path = Path(path)

    if not file_path.exists():
        return []

    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StorageReadError(f"Could not read storage file '{path}': {exc}") from exc

    if raw_text.strip() == "":
        # Treat a truly empty file the same as "no accounts yet" rather
        # than a JSON parse error - an empty file is a plausible artifact
        # of a previous run, not corruption.
        return []

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise StorageReadError(f"Storage file '{path}' is not valid JSON: {exc}") from exc

    records = _extract_account_records(data)
    _validate_no_duplicate_account_numbers(records)

    accounts: list[BankAccount] = []
    for record in records:
        _validate_account_record(record)
        accounts.append(BankAccount.from_dict(record))

    return accounts


def _extract_account_records(data: object) -> list[dict]:
    if not isinstance(data, dict):
        raise InvalidStorageDataError(
            f"Top-level JSON must be an object with an 'accounts' key, got {type(data).__name__}"
        )
    if "accounts" not in data:
        raise InvalidStorageDataError("Storage file is missing the required 'accounts' key")

    records = data["accounts"]
    if not isinstance(records, list):
        raise InvalidStorageDataError(
            f"'accounts' must be a list, got {type(records).__name__}"
        )
    return records


def _validate_account_record(record: object) -> None:
    if not isinstance(record, dict):
        raise InvalidStorageDataError(f"Each account record must be an object, got {type(record).__name__!r}")

    required_fields = {"account_number", "name", "balance"}
    missing = required_fields - record.keys()
    if missing:
        raise InvalidStorageDataError(f"Account record is missing required field(s): {sorted(missing)}")

    account_number = record["account_number"]
    if not isinstance(account_number, int) or isinstance(account_number, bool) or account_number <= 0:
        raise InvalidStorageDataError(f"Invalid account_number: {account_number!r}")

    name = record["name"]
    if not isinstance(name, str) or name.strip() == "":
        raise InvalidStorageDataError(f"Invalid name: {name!r}")

    balance = record["balance"]
    if not isinstance(balance, (int, float)) or isinstance(balance, bool) or balance < 0:
        raise InvalidStorageDataError(f"Invalid balance: {balance!r}")


def _validate_no_duplicate_account_numbers(records: list) -> None:
    seen: set = set()
    for record in records:
        if not isinstance(record, dict) or "account_number" not in record:
            continue  # will be caught by _validate_account_record
        number = record["account_number"]
        if number in seen:
            raise InvalidStorageDataError(f"Duplicate account_number found in storage: {number!r}")
        seen.add(number)


# ----------------------------------------------------------------------
# Saving
# ----------------------------------------------------------------------

def save_accounts(path: str | os.PathLike, accounts: list[BankAccount]) -> None:
    """
    Persist the given accounts to the JSON file at `path`.

    Writes are atomic: data is written to a temporary file in the same
    directory and then moved into place with os.replace(). This ensures
    that if the write is interrupted (e.g. the process crashes, disk is
    full), the original file is left untouched rather than ending up
    half-written/corrupted.
    """
    file_path = Path(path)
    payload = {"accounts": [account.to_dict() for account in accounts]}

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=file_path.parent, prefix=f".{file_path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(payload, tmp_file, indent=2)
            os.replace(tmp_path, file_path)
        except BaseException:
            # Clean up the temp file if anything went wrong before the
            # replace happened; the original file (if any) is untouched.
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
    except OSError as exc:
        raise StorageWriteError(f"Could not write storage file '{path}': {exc}") from exc
