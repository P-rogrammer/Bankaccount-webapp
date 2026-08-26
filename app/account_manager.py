"""
Integration layer: connects the Core (BankAccount) to the Storage layer
(account_storage.py) and manages the in-memory collection of accounts
that the rest of the application (eventually the backend) works with.

This module intentionally stays thin. It does not:
    - implement banking rules (that's bank_account.py)
    - implement JSON reading/writing (that's account_storage.py)
    - know about HTTP/the API/the frontend

Its only job is: keep an in-memory account collection in sync with the
JSON file, following the rule "persist only after a successful business
operation" throughout.
"""

from __future__ import annotations

import os

from bank_account import BankAccount
from account_storage import load_accounts, save_accounts


class AccountNotFoundError(Exception):
    """Raised when an operation refers to an account number that doesn't exist."""


class AccountManager:
    """
    Owns the runtime collection of BankAccount objects for one JSON storage
    file, and keeps that file up to date as accounts are created and
    modified.

    Loading happens once, at construction time (i.e. "application startup").
    Storage errors during loading (invalid/corrupted JSON) are NOT caught
    here - they propagate to the caller, so a corrupted file can never be
    silently treated as "no accounts". A missing file is not an error
    (see account_storage.load_accounts): it simply starts with an empty
    collection.
    """

    def __init__(self, storage_path: str | os.PathLike) -> None:
        self._storage_path = storage_path
        accounts = load_accounts(storage_path)  # propagates StorageReadError / InvalidStorageDataError
        self._accounts: dict[int, BankAccount] = {acc.account_number: acc for acc in accounts}

    # ------------------------------------------------------------------
    # Read access
    # ------------------------------------------------------------------

    def get_account(self, account_number: int) -> BankAccount:
        try:
            return self._accounts[account_number]
        except KeyError:
            raise AccountNotFoundError(f"No account with number {account_number}") from None

    def all_accounts(self) -> list[BankAccount]:
        return list(self._accounts.values())

    # ------------------------------------------------------------------
    # Operations that change state - each follows the same shape:
    # perform the business operation first; only persist if it succeeded.
    # ------------------------------------------------------------------

    def create_account(self, name: str) -> BankAccount:
        """
        Create a new account, add it to the collection, and persist the
        full collection.

        BankAccount's own constructor already guarantees the new account
        number does not collide with any previously loaded account (see
        BankAccount.from_dict in the Core, used during loading), so no
        extra collision handling is needed here.
        """
        account = BankAccount(name)
        self._accounts[account.account_number] = account
        self._save()
        return account

    def deposit(self, account_number: int, amount: float) -> BankAccount:
        """
        Deposit into an existing account and persist on success.

        If `account.deposit()` raises (invalid amount), it does so before
        changing `balance` (see bank_account.py), and this method does not
        call `_save()` in that case - so a failed deposit never touches
        the stored file or the in-memory balance.
        """
        account = self.get_account(account_number)
        account.deposit(amount)  # raises InvalidAmountError on failure - propagates, no save happens
        self._save()
        return account

    def withdraw(self, account_number: int, amount: float) -> BankAccount:
        """Withdraw from an existing account and persist on success (see deposit() above)."""
        account = self.get_account(account_number)
        account.withdraw(amount)  # raises InvalidAmountError / InsufficientBalanceError on failure
        self._save()
        return account

    def transfer(
        self, source_account_number: int, destination_account_number: int, amount: float
    ) -> tuple[BankAccount, BankAccount]:
        """
        Transfer `amount` from one account to another and persist on success.

        Both accounts are looked up first, so a nonexistent source OR
        destination raises AccountNotFoundError before anything is touched.
        The actual transfer rules (self-transfer, invalid amount,
        insufficient balance) live in BankAccount.transfer_to, which
        validates everything before mutating either balance - see its
        docstring. This method only adds "both accounts must exist" and
        "persist the result", it does not duplicate those business rules.

        Atomicity note: `_save()` below writes the ENTIRE current account
        collection (all accounts, not just these two) to the JSON file in
        one atomic operation (see account_storage.save_accounts - temp
        file + os.replace). That means the persisted file always reflects
        either both updated balances or neither - there is no scenario
        where only the source's or only the destination's new balance
        makes it to disk. This "single atomic write of the whole
        collection" is what account_storage already provides for every
        operation; transfer doesn't need anything extra on top of it.
        """
        source = self.get_account(source_account_number)
        destination = self.get_account(destination_account_number)

        source.transfer_to(destination, amount)  # raises on any business-rule failure, before mutating
        self._save()
        return source, destination

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _save(self) -> None:
        """
        Persist the full current collection.

        Known limitation (accepted for this task - see Task 2.2 report):
        if the business operation above already changed in-memory state
        and THIS save fails (e.g. StorageWriteError - disk full,
        permissions), the in-memory state will be ahead of what's on disk
        until the next successful save. This module does not roll back
        the in-memory change, since building a full transaction/rollback
        system is explicitly out of scope for this stage. A caller (the
        future backend) should treat a StorageWriteError here as "the
        operation succeeded in memory but was NOT safely persisted" and
        surface that clearly rather than reporting plain success.
        """
        save_accounts(self._storage_path, list(self._accounts.values()))
