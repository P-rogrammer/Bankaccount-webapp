"""
Runs the same scenarios as test_bank_account.py using plain assertions,
since pytest isn't installable in this sandbox (no network access).
This is only to verify behavior now; test_bank_account.py (pytest-based)
is the actual test suite to keep in the project.
"""

from bank_account import BankAccount, InvalidAmountError, InsufficientBalanceError, SelfTransferError

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"PASS: {name}")
    else:
        failed += 1
        print(f"FAIL: {name}")


def expect_raises(name, exc_type, fn):
    global passed, failed
    try:
        fn()
        failed += 1
        print(f"FAIL: {name} (no exception raised)")
    except exc_type:
        passed += 1
        print(f"PASS: {name}")
    except Exception as e:
        failed += 1
        print(f"FAIL: {name} (wrong exception: {type(e).__name__})")


# Account creation
acc = BankAccount("Alice")
check("account can be created", acc is not None)
check("account number is generated", isinstance(acc.account_number, int))
check("initial balance is zero", acc.balance == 0)
check("account holder name is stored", acc.name == "Alice")

# Deposit
acc2 = BankAccount("Alice")
new_balance = acc2.deposit(100)
check("valid deposit increases balance", acc2.balance == 100 and new_balance == 100)
expect_raises("deposit zero is rejected", InvalidAmountError, lambda: acc2.deposit(0))
expect_raises("deposit negative is rejected", InvalidAmountError, lambda: acc2.deposit(-50))
expect_raises("deposit non-numeric is rejected", InvalidAmountError, lambda: acc2.deposit("100"))
try:
    acc2.deposit(-10)
except InvalidAmountError:
    pass
check("failed deposit does not change balance", acc2.balance == 100)

# Withdrawal
acc3 = BankAccount("Alice")
acc3.deposit(100)
new_balance = acc3.withdraw(40)
check("valid withdrawal decreases balance", acc3.balance == 60 and new_balance == 60)

acc4 = BankAccount("Alice")
acc4.deposit(50)
expect_raises("withdrawal exceeding balance is rejected", InsufficientBalanceError, lambda: acc4.withdraw(100))
check("balance unchanged after rejected withdrawal", acc4.balance == 50)
expect_raises("withdrawal of zero is rejected", InvalidAmountError, lambda: acc4.withdraw(0))
expect_raises("withdrawal of negative is rejected", InvalidAmountError, lambda: acc4.withdraw(-20))
expect_raises("withdrawal of non-numeric is rejected", InvalidAmountError, lambda: acc4.withdraw("20"))

acc5 = BankAccount("Alice")
expect_raises("withdrawal from zero balance is rejected", InsufficientBalanceError, lambda: acc5.withdraw(1))

# Multiple accounts
accA = BankAccount("Alice")
accB = BankAccount("Bob")
check("multiple accounts get different numbers", accA.account_number != accB.account_number)
accA.deposit(100)
check("operations on one account don't affect another", accA.balance == 100 and accB.balance == 0)

# to_dict
accC = BankAccount("Alice")
accC.deposit(75)
check("to_dict reflects current state", accC.to_dict() == {
    "account_number": accC.account_number,
    "name": "Alice",
    "balance": 75,
})
data = accC.to_dict()
check(
    "to_dict does not expose internal details",
    set(data.keys()) == {"account_number", "name", "balance"}
    and all(not callable(v) for v in data.values()),
)

# Transfer
src = BankAccount("Alice")
src.deposit(100)
dst = BankAccount("Bob")
src.transfer_to(dst, 40)
check("valid transfer updates both balances", src.balance == 60 and dst.balance == 40)

selfacc = BankAccount("Alice")
selfacc.deposit(100)
expect_raises("self-transfer is rejected", SelfTransferError, lambda: selfacc.transfer_to(selfacc, 10))
check("self-transfer leaves balance unchanged", selfacc.balance == 100)

src2 = BankAccount("Alice")
src2.deposit(100)
dst2 = BankAccount("Bob")
expect_raises("transfer of zero is rejected", InvalidAmountError, lambda: src2.transfer_to(dst2, 0))
check("transfer zero leaves both balances unchanged", src2.balance == 100 and dst2.balance == 0)

expect_raises("transfer of negative is rejected", InvalidAmountError, lambda: src2.transfer_to(dst2, -10))
check("transfer negative leaves both balances unchanged", src2.balance == 100 and dst2.balance == 0)

src3 = BankAccount("Alice")
src3.deposit(30)
dst3 = BankAccount("Bob")
expect_raises("transfer insufficient balance is rejected", InsufficientBalanceError, lambda: src3.transfer_to(dst3, 100))
check("transfer insufficient balance leaves both balances unchanged", src3.balance == 30 and dst3.balance == 0)

print(f"\n{passed} passed, {failed} failed")
