# BankAccount Web App — API Contract (Version 1)

Base URL (local development): `http://127.0.0.1:5000`

All requests and responses use JSON. Every response follows one of two envelope shapes:

**Success**
```json
{ "data": ... }
```

**Error**
```json
{ "error": { "code": "machine_readable_code", "message": "human readable message" } }
```

## Numeric amount rule (applies to every `amount` field below)

An `amount` must be a genuine JSON number (integer or float) — `100` or `100.5`. Anything else is rejected as a **structurally invalid request (400)**, not converted:

| Value | Accepted? |
|---|---|
| `100` | Yes |
| `100.5` | Yes |
| `"100"` (string) | No — 400 |
| `true` / `false` | No — 400 (booleans are never treated as 1/0) |
| `null` / missing | No — 400 |
| `NaN` / `Infinity` | No — 400 (not a valid financial amount) |

This rule is identical for deposit, withdraw, and transfer.

## Status code summary

| Situation | Status |
|---|---|
| Account created | 201 |
| Successful read/update | 200 |
| Malformed request (missing/wrong-type field, bad JSON) | 400 |
| Account not found | 404 |
| Business-rule failure (invalid amount, insufficient balance, self-transfer) | 422 |
| Storage failure | 503 |
| Unexpected server error | 500 |

---

## POST /accounts — Create an account

**Request body**
```json
{ "name": "Alice" }
```
- `name` (string, required, non-empty)

**Success — 201**
```json
{ "data": { "account_number": 1000, "name": "Alice", "balance": 0 } }
```

**Errors**
- 400 `bad_request` — body isn't a JSON object, or `name` is missing/not a non-empty string.

---

## GET /accounts — List all accounts

**Success — 200**
```json
{ "data": [
  { "account_number": 1000, "name": "Alice", "balance": 100 },
  { "account_number": 1001, "name": "Bob", "balance": 50 }
]}
```

No error cases beyond unexpected/storage failures.

---

## GET /accounts/\<account_number\> — Get one account

**Success — 200**
```json
{ "data": { "account_number": 1000, "name": "Alice", "balance": 100 } }
```

**Errors**
- 404 `account_not_found` — no account with that number exists.

---

## POST /accounts/\<account_number\>/deposit — Deposit

**Request body**
```json
{ "amount": 100 }
```
- `amount` (number, required) — see numeric rule above; must end up positive.

**Success — 200**
```json
{ "data": { "account_number": 1000, "name": "Alice", "balance": 200 } }
```

**Errors**
- 400 `bad_request` — missing/wrong-type `amount`, or malformed body.
- 404 `account_not_found` — account doesn't exist.
- 422 `invalid_amount` — amount is zero or negative.

---

## POST /accounts/\<account_number\>/withdraw — Withdraw

**Request body**
```json
{ "amount": 40 }
```
- `amount` (number, required) — see numeric rule above; must end up positive and not exceed the balance.

**Success — 200**
```json
{ "data": { "account_number": 1000, "name": "Alice", "balance": 60 } }
```

**Errors**
- 400 `bad_request` — missing/wrong-type `amount`, or malformed body.
- 404 `account_not_found` — account doesn't exist.
- 422 `invalid_amount` — amount is zero or negative.
- 422 `insufficient_balance` — amount exceeds the account's current balance.

---

## POST /accounts/\<source_account_number\>/transfer — Transfer

**Request body**
```json
{ "destination_account_number": 1001, "amount": 40 }
```
- `destination_account_number` (integer, required)
- `amount` (number, required) — see numeric rule above; must end up positive and not exceed the source balance.

**Success — 200**
```json
{ "data": {
  "source":      { "account_number": 1000, "name": "Alice", "balance": 60 },
  "destination": { "account_number": 1001, "name": "Bob",   "balance": 40 }
}}
```

**Errors**
- 400 `bad_request` — missing/wrong-type `destination_account_number` or `amount`, or malformed body.
- 404 `account_not_found` — the source account (from the URL) or the destination account doesn't exist. The message names which account number wasn't found.
- 422 `invalid_amount` — amount is zero or negative.
- 422 `insufficient_balance` — amount exceeds the source account's balance.
- 422 `self_transfer` — source and destination are the same account.

**Atomicity guarantee:** a transfer either updates both balances (in memory and on disk) or leaves both completely unchanged — see the implementation report for how this is achieved.

---

## Other error responses (any endpoint)

| Code | Status | Meaning |
|---|---|---|
| `storage_error` | 503 | The JSON storage file couldn't be read/written. Safe to retry. |
| `internal_error` | 500 | An unexpected server error. No internal details are exposed. |
| `not_found` | 404 | The URL itself doesn't match any route (e.g. a typo'd path, or a non-integer account number in the URL). Distinct from `account_not_found`, which means the route matched but that account number doesn't exist. |
| `method_not_allowed` | 405 | The HTTP method used isn't supported on that path (e.g. `DELETE /accounts`). |

These two come from Flask/Werkzeug itself rather than application code, but are still returned using the same `{"error": {"code", "message"}}` envelope as every other error on this API — never a raw HTML error page.
