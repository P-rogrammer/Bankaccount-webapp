"""
Tests for the JSON storage layer (Task 2.1).

Run with: python -m pytest test_account_storage.py -v

All tests use pytest's `tmp_path` fixture, so no real application data
file is ever read or written by these tests.
"""

import json

import pytest

from bank_account import BankAccount, InvalidAmountError
from account_storage import (
    load_accounts,
    save_accounts,
    StorageReadError,
    InvalidStorageDataError,
)


@pytest.fixture(autouse=True)
def reset_account_numbering():
    """
    BankAccount uses class-level counters for account numbers. Reset them
    before each test so tests don't leak numbering state into each other.
    """
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    yield


# ----------------------------------------------------------------------
# Saving
# ----------------------------------------------------------------------

def test_save_one_account(tmp_path):
    path = tmp_path / "accounts.json"
    acc = BankAccount("Alice")
    acc.deposit(100)

    save_accounts(path, [acc])

    data = json.loads(path.read_text())
    assert data == {"accounts": [{"account_number": acc.account_number, "name": "Alice", "balance": 100}]}


def test_save_multiple_accounts(tmp_path):
    path = tmp_path / "accounts.json"
    acc1 = BankAccount("Alice")
    acc2 = BankAccount("Bob")

    save_accounts(path, [acc1, acc2])

    data = json.loads(path.read_text())
    assert len(data["accounts"]) == 2


def test_updated_balance_is_persisted(tmp_path):
    path = tmp_path / "accounts.json"
    acc = BankAccount("Alice")
    acc.deposit(100)
    save_accounts(path, [acc])

    acc.withdraw(30)
    save_accounts(path, [acc])

    data = json.loads(path.read_text())
    assert data["accounts"][0]["balance"] == 70


# ----------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------

def test_load_existing_accounts(tmp_path):
    path = tmp_path / "accounts.json"
    original = BankAccount("Alice")
    original.deposit(50)
    save_accounts(path, [original])

    loaded = load_accounts(path)

    assert len(loaded) == 1
    assert loaded[0].account_number == original.account_number
    assert loaded[0].name == "Alice"
    assert loaded[0].balance == 50


def test_load_multiple_accounts(tmp_path):
    path = tmp_path / "accounts.json"
    acc1 = BankAccount("Alice")
    acc2 = BankAccount("Bob")
    save_accounts(path, [acc1, acc2])

    loaded = load_accounts(path)

    assert {a.name for a in loaded} == {"Alice", "Bob"}


def test_load_empty_storage(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"accounts": []}))

    loaded = load_accounts(path)

    assert loaded == []


def test_load_missing_storage_file(tmp_path):
    path = tmp_path / "does_not_exist.json"

    loaded = load_accounts(path)

    assert loaded == []


# ----------------------------------------------------------------------
# Account numbers
# ----------------------------------------------------------------------

def test_existing_account_numbers_survive_reload(tmp_path):
    path = tmp_path / "accounts.json"
    original = BankAccount("Alice")
    save_accounts(path, [original])

    loaded = load_accounts(path)

    assert loaded[0].account_number == original.account_number


def test_new_accounts_do_not_collide_with_loaded_numbers(tmp_path):
    path = tmp_path / "accounts.json"
    original = BankAccount("Alice")  # e.g. account_number 1000
    save_accounts(path, [original])

    # Simulate an application restart: reset in-memory bookkeeping,
    # then load from storage exactly like a fresh process would.
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    loaded = load_accounts(path)

    new_account = BankAccount("Bob")  # created AFTER loading

    assert new_account.account_number != loaded[0].account_number
    assert new_account.account_number > loaded[0].account_number


def test_multiple_newly_created_accounts_remain_unique_after_load(tmp_path):
    path = tmp_path / "accounts.json"
    original = BankAccount("Alice")
    save_accounts(path, [original])

    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    load_accounts(path)

    new1 = BankAccount("Bob")
    new2 = BankAccount("Carol")

    assert len({original.account_number, new1.account_number, new2.account_number}) == 3


# ----------------------------------------------------------------------
# Invalid data
# ----------------------------------------------------------------------

def test_invalid_json_raises_storage_read_error(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("{ this is not valid json")

    with pytest.raises(StorageReadError):
        load_accounts(path)


def test_missing_required_field_raises_invalid_storage_data_error(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"accounts": [{"account_number": 1000, "name": "Alice"}]}))

    with pytest.raises(InvalidStorageDataError):
        load_accounts(path)


def test_invalid_field_type_raises_invalid_storage_data_error(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"accounts": [{"account_number": "not-a-number", "name": "Alice", "balance": 10}]}))

    with pytest.raises(InvalidStorageDataError):
        load_accounts(path)


def test_duplicate_account_numbers_raises_invalid_storage_data_error(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({
        "accounts": [
            {"account_number": 1000, "name": "Alice", "balance": 10},
            {"account_number": 1000, "name": "Bob", "balance": 20},
        ]
    }))

    with pytest.raises(InvalidStorageDataError):
        load_accounts(path)


# ----------------------------------------------------------------------
# Error handling / separation from business errors
# ----------------------------------------------------------------------

def test_storage_errors_are_distinguishable_from_business_errors(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("not json at all")

    with pytest.raises(StorageReadError):
        load_accounts(path)

    # A storage error must never be confused with (or subclass) a business
    # error raised by the Core.
    acc = BankAccount("Alice")
    with pytest.raises(InvalidAmountError):
        acc.deposit(-5)


def test_failed_save_does_not_corrupt_existing_file(tmp_path, monkeypatch):
    path = tmp_path / "accounts.json"
    original = BankAccount("Alice")
    save_accounts(path, [original])
    original_contents = path.read_text()

    # Force the atomic replace step to fail partway through.
    import account_storage as storage_module

    def boom(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(storage_module.os, "replace", boom)

    with pytest.raises(Exception):
        save_accounts(path, [BankAccount("Bob")])

    # The original file must be untouched - no partial/corrupted write.
    assert path.read_text() == original_contents
