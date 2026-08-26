"""
Tests for the refactored BankAccount core (Task 1.1).

Run with: python -m pytest test_bank_account.py -v
(or just: python test_bank_account.py)
"""

import pytest

from bank_account import (
    BankAccount,
    InvalidAmountError,
    InsufficientBalanceError,
    SelfTransferError,
)


# ----------------------------------------------------------------------
# Account creation
# ----------------------------------------------------------------------

def test_account_can_be_created():
    acc = BankAccount("Alice")
    assert acc is not None


def test_account_number_is_generated():
    acc = BankAccount("Alice")
    assert isinstance(acc.account_number, int)


def test_initial_balance_is_zero():
    acc = BankAccount("Alice")
    assert acc.balance == 0


def test_account_holder_name_is_stored():
    acc = BankAccount("Alice")
    assert acc.name == "Alice"


# ----------------------------------------------------------------------
# Deposit
# ----------------------------------------------------------------------

def test_valid_deposit_increases_balance():
    acc = BankAccount("Alice")
    new_balance = acc.deposit(100)
    assert acc.balance == 100
    assert new_balance == 100


def test_deposit_zero_is_rejected():
    acc = BankAccount("Alice")
    with pytest.raises(InvalidAmountError):
        acc.deposit(0)


def test_deposit_negative_is_rejected():
    acc = BankAccount("Alice")
    with pytest.raises(InvalidAmountError):
        acc.deposit(-50)


def test_deposit_non_numeric_is_rejected():
    acc = BankAccount("Alice")
    with pytest.raises(InvalidAmountError):
        acc.deposit("100")  # type: ignore[arg-type]


def test_failed_deposit_does_not_change_balance():
    acc = BankAccount("Alice")
    try:
        acc.deposit(-10)
    except InvalidAmountError:
        pass
    assert acc.balance == 0


# ----------------------------------------------------------------------
# Withdrawal
# ----------------------------------------------------------------------

def test_valid_withdrawal_decreases_balance():
    acc = BankAccount("Alice")
    acc.deposit(100)
    new_balance = acc.withdraw(40)
    assert acc.balance == 60
    assert new_balance == 60


def test_withdrawal_exceeding_balance_is_rejected():
    acc = BankAccount("Alice")
    acc.deposit(50)
    with pytest.raises(InsufficientBalanceError):
        acc.withdraw(100)
    assert acc.balance == 50  # unchanged


def test_withdrawal_zero_is_rejected():
    acc = BankAccount("Alice")
    acc.deposit(50)
    with pytest.raises(InvalidAmountError):
        acc.withdraw(0)


def test_withdrawal_negative_is_rejected():
    acc = BankAccount("Alice")
    acc.deposit(50)
    with pytest.raises(InvalidAmountError):
        acc.withdraw(-20)


def test_withdrawal_non_numeric_is_rejected():
    acc = BankAccount("Alice")
    acc.deposit(50)
    with pytest.raises(InvalidAmountError):
        acc.withdraw("20")  # type: ignore[arg-type]


def test_withdrawal_from_zero_balance_is_rejected():
    acc = BankAccount("Alice")
    with pytest.raises(InsufficientBalanceError):
        acc.withdraw(1)


# ----------------------------------------------------------------------
# Multiple accounts
# ----------------------------------------------------------------------

def test_multiple_accounts_get_different_numbers():
    acc1 = BankAccount("Alice")
    acc2 = BankAccount("Bob")
    assert acc1.account_number != acc2.account_number


def test_operations_on_one_account_do_not_affect_another():
    acc1 = BankAccount("Alice")
    acc2 = BankAccount("Bob")
    acc1.deposit(100)
    assert acc1.balance == 100
    assert acc2.balance == 0


# ----------------------------------------------------------------------
# State representation
# ----------------------------------------------------------------------

def test_to_dict_reflects_current_state():
    acc = BankAccount("Alice")
    acc.deposit(75)
    data = acc.to_dict()
    assert data == {
        "account_number": acc.account_number,
        "name": "Alice",
        "balance": 75,
    }


def test_to_dict_does_not_expose_internal_details():
    acc = BankAccount("Alice")
    data = acc.to_dict()
    # Only the three domain fields should be present - nothing about
    # class-level bookkeeping, methods, or other implementation details.
    assert set(data.keys()) == {"account_number", "name", "balance"}
    assert all(not callable(value) for value in data.values())


# ----------------------------------------------------------------------
# Transfer
# ----------------------------------------------------------------------

def test_valid_transfer_updates_both_balances():
    source = BankAccount("Alice")
    source.deposit(100)
    destination = BankAccount("Bob")

    source.transfer_to(destination, 40)

    assert source.balance == 60
    assert destination.balance == 40


def test_self_transfer_is_rejected():
    acc = BankAccount("Alice")
    acc.deposit(100)
    with pytest.raises(SelfTransferError):
        acc.transfer_to(acc, 10)
    assert acc.balance == 100  # unchanged


def test_transfer_zero_is_rejected():
    source = BankAccount("Alice")
    source.deposit(100)
    destination = BankAccount("Bob")
    with pytest.raises(InvalidAmountError):
        source.transfer_to(destination, 0)
    assert source.balance == 100
    assert destination.balance == 0


def test_transfer_negative_is_rejected():
    source = BankAccount("Alice")
    source.deposit(100)
    destination = BankAccount("Bob")
    with pytest.raises(InvalidAmountError):
        source.transfer_to(destination, -10)
    assert source.balance == 100
    assert destination.balance == 0


def test_transfer_insufficient_balance_is_rejected():
    source = BankAccount("Alice")
    source.deposit(30)
    destination = BankAccount("Bob")
    with pytest.raises(InsufficientBalanceError):
        source.transfer_to(destination, 100)
    assert source.balance == 30
    assert destination.balance == 0


def test_failed_transfer_leaves_both_accounts_unchanged():
    source = BankAccount("Alice")
    source.deposit(50)
    destination = BankAccount("Bob")
    destination.deposit(20)

    try:
        source.transfer_to(destination, -5)
    except InvalidAmountError:
        pass

    assert source.balance == 50
    assert destination.balance == 20


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
