"""
Tests for the backend foundation (Task 3.1).

Run with: python -m pytest test_backend.py -v

All tests use pytest's tmp_path fixture for storage, and Flask's built-in
test client (no real server/socket needed) - real application data is
never touched.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from bank_account import BankAccount
from account_storage import StorageError
from app import create_app


@pytest.fixture(autouse=True)
def reset_account_numbering():
    BankAccount.all_account_numbers = []
    BankAccount.last_account_number = 999
    yield


@pytest.fixture
def client(tmp_path):
    storage_path = tmp_path / "accounts.json"
    flask_app = create_app(storage_path)
    flask_app.testing = True
    return flask_app.test_client()


# ----------------------------------------------------------------------
# Server / application startup
# ----------------------------------------------------------------------

def test_app_initializes_with_empty_storage(tmp_path):
    storage_path = tmp_path / "does_not_exist.json"
    flask_app = create_app(storage_path)
    assert flask_app.account_manager.all_accounts() == []


def test_app_loads_existing_data(tmp_path):
    storage_path = tmp_path / "accounts.json"
    storage_path.write_text(json.dumps({"accounts": [
        {"account_number": 1000, "name": "Alice", "balance": 100},
    ]}))

    flask_app = create_app(storage_path)

    account = flask_app.account_manager.get_account(1000)
    assert account.name == "Alice"
    assert account.balance == 100


def test_app_fails_to_start_on_corrupted_storage(tmp_path):
    storage_path = tmp_path / "accounts.json"
    storage_path.write_text("not valid json")

    with pytest.raises(StorageError):
        create_app(storage_path)


# ----------------------------------------------------------------------
# Frontend serving (Task 4.1)
# ----------------------------------------------------------------------

def test_index_page_is_served(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "/static/js/app.js" in html
    assert "/static/css/style.css" in html


def test_frontend_static_assets_are_served(client):
    resp = client.get("/static/js/app.js")
    assert resp.status_code == 200

    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200


def test_api_routes_still_work_alongside_frontend_routes(client):
    resp = client.post("/accounts", json={"name": "Alice"})
    assert resp.status_code == 201


# ----------------------------------------------------------------------
# Framework-level errors (unmatched routes, wrong method) still use the
# API's consistent JSON envelope rather than Werkzeug's default HTML page.
# ----------------------------------------------------------------------

def test_unmatched_route_returns_json_404(client):
    resp = client.get("/this-route-does-not-exist")
    assert resp.status_code == 404
    body = resp.get_json()
    assert "error" in body and "code" in body["error"] and "message" in body["error"]


def test_wrong_http_method_returns_json_405(client):
    resp = client.put("/accounts")
    assert resp.status_code == 405
    body = resp.get_json()
    assert "error" in body


def test_non_integer_account_number_in_url_returns_json_404(client):
    resp = client.get("/accounts/not-an-int")
    assert resp.status_code == 404
    body = resp.get_json()
    assert "error" in body


# ----------------------------------------------------------------------
# Routing edge cases (Task 5.1 regression - unmatched routes/methods must
# return the correct status code and our JSON envelope, not a generic 500)
# ----------------------------------------------------------------------

def test_non_integer_account_number_in_url_is_404_not_500(client):
    resp = client.get("/accounts/not-a-number")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_negative_account_number_in_url_is_404_not_500(client):
    resp = client.get("/accounts/-5")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_unmatched_route_is_404_with_json_envelope(client):
    resp = client.get("/this/route/does/not/exist")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "not_found"


def test_wrong_http_method_is_405_with_json_envelope(client):
    resp = client.delete("/accounts")
    assert resp.status_code == 405
    assert resp.get_json()["error"]["code"] == "method_not_allowed"


def test_valid_integer_but_unknown_account_is_still_account_not_found(client):
    # Distinguishes "the URL itself doesn't exist" (not_found) from
    # "the URL is well-formed but that account doesn't exist" (account_not_found).
    resp = client.get("/accounts/9999")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "account_not_found"


# ----------------------------------------------------------------------
# Create account
# ----------------------------------------------------------------------

def test_create_account_success(client):
    resp = client.post("/accounts", json={"name": "Alice"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["data"]["name"] == "Alice"
    assert body["data"]["balance"] == 0
    assert isinstance(body["data"]["account_number"], int)


def test_create_account_missing_name(client):
    resp = client.post("/accounts", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_create_account_non_string_name(client):
    resp = client.post("/accounts", json={"name": 123})
    assert resp.status_code == 400


def test_create_account_no_body(client):
    resp = client.post("/accounts")
    assert resp.status_code == 400


# ----------------------------------------------------------------------
# List / get accounts
# ----------------------------------------------------------------------

def test_list_accounts(client):
    client.post("/accounts", json={"name": "Alice"})
    client.post("/accounts", json={"name": "Bob"})

    resp = client.get("/accounts")

    assert resp.status_code == 200
    names = {a["name"] for a in resp.get_json()["data"]}
    assert names == {"Alice", "Bob"}


def test_get_existing_account(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.get(f"/accounts/{created['account_number']}")

    assert resp.status_code == 200
    assert resp.get_json()["data"]["name"] == "Alice"


def test_get_nonexistent_account(client):
    resp = client.get("/accounts/9999")
    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "account_not_found"


# ----------------------------------------------------------------------
# Deposit
# ----------------------------------------------------------------------

def test_deposit_success(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 100})

    assert resp.status_code == 200
    assert resp.get_json()["data"]["balance"] == 100


def test_deposit_invalid_amount_is_business_error(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": -10})

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_amount"


def test_deposit_missing_amount_is_bad_request(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={})

    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_deposit_zero_is_business_error(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 0})

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_amount"


@pytest.mark.parametrize("bad_amount", ["100", True, False, None, [], {}])
def test_deposit_invalid_amount_type_is_bad_request(client, bad_amount):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": bad_amount})

    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_deposit_resulting_balance_is_correct(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 30})
    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 20.5})

    assert resp.get_json()["data"]["balance"] == 50.5


def test_deposit_on_nonexistent_account(client):
    resp = client.post("/accounts/9999/deposit", json={"amount": 100})
    assert resp.status_code == 404


# ----------------------------------------------------------------------
# Withdraw
# ----------------------------------------------------------------------

def test_withdraw_success(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 100})

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 40})

    assert resp.status_code == 200
    assert resp.get_json()["data"]["balance"] == 60


def test_withdraw_insufficient_balance_is_business_error(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 50})

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "insufficient_balance"


def test_withdraw_missing_amount_is_bad_request(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={})

    assert resp.status_code == 400


def test_withdraw_zero_is_business_error(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 50})

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 0})

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_amount"


def test_withdraw_negative_is_business_error(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 50})

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": -5})

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_amount"


@pytest.mark.parametrize("bad_amount", ["50", True, None])
def test_withdraw_invalid_amount_type_is_bad_request(client, bad_amount):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 50})

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": bad_amount})

    assert resp.status_code == 400


def test_withdraw_resulting_balance_is_correct(client):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 100})

    resp = client.post(f"/accounts/{created['account_number']}/withdraw", json={"amount": 35})

    assert resp.get_json()["data"]["balance"] == 65


def test_withdraw_on_nonexistent_account(client):
    resp = client.post("/accounts/9999/withdraw", json={"amount": 10})
    assert resp.status_code == 404


# ----------------------------------------------------------------------
# Transfer
# ----------------------------------------------------------------------

def test_transfer_success(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 40},
    )

    assert resp.status_code == 200
    body = resp.get_json()["data"]
    assert body["source"]["balance"] == 60
    assert body["destination"]["balance"] == 40


def test_transfer_correct_source_and_destination_balance(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})
    client.post(f"/accounts/{bob['account_number']}/deposit", json={"amount": 10})

    client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 25},
    )

    source = client.get(f"/accounts/{alice['account_number']}").get_json()["data"]
    destination = client.get(f"/accounts/{bob['account_number']}").get_json()["data"]
    assert source["balance"] == 75
    assert destination["balance"] == 35


def test_transfer_is_persisted(client, tmp_path):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 40},
    )

    # Read the underlying storage file directly to confirm persistence,
    # not just the in-memory response.
    storage_files = list(tmp_path.glob("accounts.json"))
    data = json.loads(storage_files[0].read_text())
    records = {r["account_number"]: r["balance"] for r in data["accounts"]}
    assert records[alice["account_number"]] == 60
    assert records[bob["account_number"]] == 40


def test_transfer_source_not_found(client):
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]

    resp = client.post(
        "/accounts/9999/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 10},
    )

    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "account_not_found"


def test_transfer_destination_not_found(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": 9999, "amount": 10},
    )

    assert resp.status_code == 404
    assert resp.get_json()["error"]["code"] == "account_not_found"


def test_transfer_missing_destination_is_bad_request(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(f"/accounts/{alice['account_number']}/transfer", json={"amount": 10})

    assert resp.status_code == 400
    assert resp.get_json()["error"]["code"] == "bad_request"


def test_transfer_missing_amount_is_bad_request(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"]},
    )

    assert resp.status_code == 400


@pytest.mark.parametrize("bad_amount", ["40", True, None])
def test_transfer_invalid_amount_type_is_bad_request(client, bad_amount):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": bad_amount},
    )

    assert resp.status_code == 400


def test_transfer_zero_amount_is_business_error(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 0},
    )

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_amount"


def test_transfer_negative_amount_is_business_error(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": -5},
    )

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "invalid_amount"


def test_transfer_insufficient_balance_is_business_error(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 20})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 100},
    )

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "insufficient_balance"


def test_self_transfer_is_business_error(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 100})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": alice["account_number"], "amount": 10},
    )

    assert resp.status_code == 422
    assert resp.get_json()["error"]["code"] == "self_transfer"


def test_failed_transfer_leaves_both_balances_unchanged(client):
    alice = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]
    bob = client.post("/accounts", json={"name": "Bob"}).get_json()["data"]
    client.post(f"/accounts/{alice['account_number']}/deposit", json={"amount": 20})
    client.post(f"/accounts/{bob['account_number']}/deposit", json={"amount": 5})

    resp = client.post(
        f"/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 1000},
    )
    assert resp.status_code == 422

    alice_after = client.get(f"/accounts/{alice['account_number']}").get_json()["data"]
    bob_after = client.get(f"/accounts/{bob['account_number']}").get_json()["data"]
    assert alice_after["balance"] == 20
    assert bob_after["balance"] == 5


# ----------------------------------------------------------------------
# Storage error mapping (simulated - "where practical" per the task)
# ----------------------------------------------------------------------

def test_storage_failure_during_request_maps_to_503(client, monkeypatch):
    created = client.post("/accounts", json={"name": "Alice"}).get_json()["data"]

    import account_manager as account_manager_module

    def boom(self):
        raise StorageError("simulated storage failure")

    monkeypatch.setattr(account_manager_module.AccountManager, "_save", boom)

    resp = client.post(f"/accounts/{created['account_number']}/deposit", json={"amount": 10})

    assert resp.status_code == 503
    assert resp.get_json()["error"]["code"] == "storage_error"
