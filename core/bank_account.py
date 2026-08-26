"""
Core business logic for the BankAccount web application.

This module intentionally has no knowledge of:
    - the terminal (no input()/print())
    - HTTP/the backend
    - JSON storage
    - the frontend

It only models an account and the banking rules that apply to it.
Callers (e.g. the backend, or a test script) are responsible for
getting input from wherever it comes from, calling into this module,
and presenting the result however is appropriate for that layer.
"""

from __future__ import annotations


class InvalidAmountError(ValueError):
    """Raised when a deposit/withdrawal amount is not a valid positive number."""


class InsufficientBalanceError(ValueError):
    """Raised when a withdrawal is attempted for more than the current balance."""


class SelfTransferError(ValueError):
    """Raised when a transfer's source and destination account are the same account."""


class BankAccount:
    """
    Represents a single bank account and the operations allowed on it.

    Design notes
    ------------
    - `balance` and transaction `amount`s use `float`. For an educational
      project this keeps the model simple; it is not appropriate for a real
      financial system (float rounding errors), where a `Decimal` or an
      integer "cents" representation would be used instead.
    - `account_number` is a plain `int`, assigned sequentially in-memory.

    Account-number continuity across restarts
    ------------------------------------------
    `last_account_number` and `all_account_numbers` are class-level state.
    On their own they'd assume the process always starts with no existing
    accounts (numbering restarting at 1000 every run). That gap is closed
    by `from_dict()` below, which the storage layer uses to reconstruct
    previously-existing accounts on startup: it advances `last_account_number`
    past any loaded account, so accounts created afterward never collide
    with accounts that already existed. See `from_dict()` for details.
    """

    all_account_numbers: list[int] = []
    last_account_number: int = 999

    def __init__(self, name: str) -> None:
        BankAccount.last_account_number += 1
        account_number = BankAccount.last_account_number

        self.account_number: int = account_number
        BankAccount.all_account_numbers.append(account_number)

        self.name: str = name
        self.balance: float = 0.0

    # ------------------------------------------------------------------
    # Reconstruction (used by the storage layer, NOT the same as creation)
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "BankAccount":
        """
        Rebuild a BankAccount that already existed (e.g. loaded from storage).

        This intentionally does NOT go through __init__: it must not
        generate a brand-new account number, since that would silently
        change the identity of a previously-existing account every time
        the application restarts.

        Instead it takes the account number as given, and keeps the
        class-level bookkeeping (`all_account_numbers`, `last_account_number`)
        in sync so that any account created *after* this one (via
        `BankAccount(name)`) is guaranteed not to collide with it.

        This method assumes `data` has already been structurally validated
        (correct keys/types) by the caller - the storage layer, not the
        Core, owns validating raw stored data. This keeps the "convert
        untrusted data into a usable object" responsibility in one place
        instead of duplicating field checks in both layers.
        """
        account = cls.__new__(cls)
        account.account_number = data["account_number"]
        account.name = data["name"]
        account.balance = data["balance"]

        if account.account_number not in cls.all_account_numbers:
            cls.all_account_numbers.append(account.account_number)
        if account.account_number > cls.last_account_number:
            cls.last_account_number = account.account_number

        return account

    # ------------------------------------------------------------------
    # Business operations
    # ------------------------------------------------------------------

    def deposit(self, amount: float) -> float:
        """
        Deposit `amount` into the account.

        Returns the new balance on success.
        Raises InvalidAmountError if the amount is not a positive number.
        """
        self._validate_amount(amount)
        self.balance += amount
        return self.balance

    def withdraw(self, amount: float) -> float:
        """
        Withdraw `amount` from the account.

        Returns the new balance on success.
        Raises InvalidAmountError if the amount is not a positive number.
        Raises InsufficientBalanceError if the account doesn't have enough funds.
        """
        self._validate_amount(amount)
        self._check_sufficient_balance(amount)
        self.balance -= amount
        return self.balance

    def transfer_to(self, destination: "BankAccount", amount: float) -> None:
        """
        Transfer `amount` from this account to `destination`.

        All validation happens BEFORE either account's balance is touched,
        so a failed transfer never partially applies: either both balances
        update, or neither does.

        Raises SelfTransferError if `destination` is this same account.
        Raises InvalidAmountError if the amount is not a positive number.
        Raises InsufficientBalanceError if this account doesn't have enough funds.
        """
        if destination.account_number == self.account_number:
            raise SelfTransferError(
                f"Cannot transfer to the same account (account {self.account_number})"
            )
        self._validate_amount(amount)
        self._check_sufficient_balance(amount)

        # Both validated - now safe to mutate both sides.
        self.balance -= amount
        destination.balance += amount

    # ------------------------------------------------------------------
    # State representation (no printing/formatting for a terminal)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain-data representation of the account's current state."""
        return {
            "account_number": self.account_number,
            "name": self.name,
            "balance": self.balance,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_amount(amount: float) -> None:
        if not isinstance(amount, (int, float)) or isinstance(amount, bool):
            raise InvalidAmountError(f"Amount must be a number, got {amount!r}")
        if amount <= 0:
            raise InvalidAmountError(f"Amount must be positive, got {amount!r}")

    def _check_sufficient_balance(self, amount: float) -> None:
        if amount > self.balance:
            raise InsufficientBalanceError(
                f"Insufficient balance: balance is {self.balance}, attempted to use {amount}"
            )
