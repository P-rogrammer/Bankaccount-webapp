"""
Integration tests for AccountManager (Task 2.2): Core + Storage working
together through the startup/create/deposit/withdraw workflow.

Run with: python -m pytest test_account_manager.py -v
"""

import json

import pytest

from bank_account import BankAccount, InvalidAmountError, InsufficientBalanceError, SelfTransferError
from account_storage import InvalidStorageDataError, StorageReadError
from account_manager import AccountManager, AccountNotFoundError


@pytest.fixture(autouse=True)
def reset_account_numbering():
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    yield


# ----------------------------------------------------------------------
# Startup
# ----------------------------------------------------------------------

def test_existing_accounts_are_loaded_at_startup(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"accounts": [
        {"account_number": 1000, "name": "Alice", "balance": 100},
    ]}))

    manager = AccountManager(path)

    account = manager.get_account(1000)
    assert account.name == "Alice"
    assert account.balance == 100


def test_missing_storage_starts_with_no_accounts(tmp_path):
    path = tmp_path / "does_not_exist.json"

    manager = AccountManager(path)

    assert manager.all_accounts() == []


def test_invalid_storage_does_not_silently_produce_empty_list(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text("not valid json")

    with pytest.raises(StorageReadError):
        AccountManager(path)


def test_invalid_account_records_at_startup_raise(tmp_path):
    path = tmp_path / "accounts.json"
    path.write_text(json.dumps({"accounts": [{"account_number": 1000, "name": "Alice"}]}))

    with pytest.raises(InvalidStorageDataError):
        AccountManager(path)


# ----------------------------------------------------------------------
# Creation
# ----------------------------------------------------------------------

def test_newly_created_account_can_be_persisted(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)

    account = manager.create_account("Alice")

    data = json.loads(path.read_text())
    assert any(rec["account_number"] == account.account_number for rec in data["accounts"])


def test_persisted_account_can_be_loaded_again(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    created = manager.create_account("Alice")

    reloaded_manager = AccountManager(path)

    account = reloaded_manager.get_account(created.account_number)
    assert account.name == "Alice"
    assert account.balance == 0


# ----------------------------------------------------------------------
# Deposit
# ----------------------------------------------------------------------

def test_successful_deposit_can_be_persisted(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = manager.create_account("Alice")

    manager.deposit(account.account_number, 100)

    data = json.loads(path.read_text())
    record = next(r for r in data["accounts"] if r["account_number"] == account.account_number)
    assert record["balance"] == 100


def test_reload_restores_deposit(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)

    reloaded_manager = AccountManager(path)

    assert reloaded_manager.get_account(account.account_number).balance == 100


def test_failed_deposit_does_not_modify_persisted_state(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 50)
    before = path.read_text()

    with pytest.raises(InvalidAmountError):
        manager.deposit(account.account_number, -10)

    assert path.read_text() == before
    assert manager.get_account(account.account_number).balance == 50


# ----------------------------------------------------------------------
# Withdrawal
# ----------------------------------------------------------------------

def test_successful_withdrawal_can_be_persisted(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)

    manager.withdraw(account.account_number, 40)

    data = json.loads(path.read_text())
    record = next(r for r in data["accounts"] if r["account_number"] == account.account_number)
    assert record["balance"] == 60


def test_reload_restores_withdrawal(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 100)
    manager.withdraw(account.account_number, 40)

    reloaded_manager = AccountManager(path)

    assert reloaded_manager.get_account(account.account_number).balance == 60


def test_failed_withdrawal_does_not_modify_persisted_state(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    account = manager.create_account("Alice")
    manager.deposit(account.account_number, 50)
    before = path.read_text()

    with pytest.raises(InsufficientBalanceError):
        manager.withdraw(account.account_number, 1000)

    assert path.read_text() == before
    assert manager.get_account(account.account_number).balance == 50


def test_operation_on_nonexistent_account_raises_and_does_not_touch_storage(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    manager.create_account("Alice")
    before = path.read_text()

    with pytest.raises(AccountNotFoundError):
        manager.deposit(9999, 10)

    assert path.read_text() == before


# ----------------------------------------------------------------------
# Restart simulation
# ----------------------------------------------------------------------

def test_full_restart_cycle(tmp_path):
    path = tmp_path / "accounts.json"

    # Start
    manager = AccountManager(path)
    # Modify
    alice = manager.create_account("Alice")
    manager.deposit(alice.account_number, 200)
    manager.withdraw(alice.account_number, 50)
    # Save happens automatically after each successful op above.

    # "Restart": reset class-level numbering exactly as a fresh process
    # would start, then load again.
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    restarted_manager = AccountManager(path)

    reloaded_alice = restarted_manager.get_account(alice.account_number)
    assert reloaded_alice.balance == 150
    assert reloaded_alice.name == "Alice"

    # New account created after restart must not collide.
    bob = restarted_manager.create_account("Bob")
    assert bob.account_number != alice.account_number
    assert bob.account_number > alice.account_number


# ----------------------------------------------------------------------
# Account number continuity through the manager
# ----------------------------------------------------------------------

def test_account_number_continuity_across_manager_restart(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    manager.create_account("Alice")
    manager.create_account("Bob")
    manager.create_account("Carol")

    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    restarted = AccountManager(path)
    new_account = restarted.create_account("Dave")

    existing_numbers = {a.account_number for a in restarted.all_accounts() if a.name != "Dave"}
    assert new_account.account_number not in existing_numbers
    assert new_account.account_number > max(existing_numbers)


# ----------------------------------------------------------------------
# Transfer
# ----------------------------------------------------------------------

def test_successful_transfer_can_be_persisted(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    bob = manager.create_account("Bob")
    manager.deposit(alice.account_number, 100)

    manager.transfer(alice.account_number, bob.account_number, 40)

    data = json.loads(path.read_text())
    records = {r["account_number"]: r["balance"] for r in data["accounts"]}
    assert records[alice.account_number] == 60
    assert records[bob.account_number] == 40


def test_reload_restores_transfer(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    bob = manager.create_account("Bob")
    manager.deposit(alice.account_number, 100)
    manager.transfer(alice.account_number, bob.account_number, 40)

    reloaded = AccountManager(path)

    assert reloaded.get_account(alice.account_number).balance == 60
    assert reloaded.get_account(bob.account_number).balance == 40


def test_transfer_source_not_found(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    bob = manager.create_account("Bob")

    with pytest.raises(AccountNotFoundError):
        manager.transfer(9999, bob.account_number, 10)


def test_transfer_destination_not_found(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    manager.deposit(alice.account_number, 100)

    with pytest.raises(AccountNotFoundError):
        manager.transfer(alice.account_number, 9999, 10)


def test_failed_transfer_does_not_modify_persisted_state(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    bob = manager.create_account("Bob")
    manager.deposit(alice.account_number, 50)
    before = path.read_text()

    with pytest.raises(InsufficientBalanceError):
        manager.transfer(alice.account_number, bob.account_number, 1000)

    assert path.read_text() == before
    assert manager.get_account(alice.account_number).balance == 50
    assert manager.get_account(bob.account_number).balance == 0


def test_self_transfer_via_manager_is_rejected_and_does_not_persist(tmp_path):
    path = tmp_path / "accounts.json"
    manager = AccountManager(path)
    alice = manager.create_account("Alice")
    manager.deposit(alice.account_number, 50)
    before = path.read_text()

    with pytest.raises(SelfTransferError):
        manager.transfer(alice.account_number, alice.account_number, 10)

    assert path.read_text() == before
    assert manager.get_account(alice.account_number).balance == 50
