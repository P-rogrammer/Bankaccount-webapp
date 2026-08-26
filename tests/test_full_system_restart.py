"""
Task 5.1 - full-system functional test with an ACTUAL process restart
(not just resetting class attributes within one Python process, like the
per-layer manual test runners do). This launches backend/app.py as a real
subprocess, drives it over real HTTP, kills it, starts a fresh subprocess
against the SAME storage file, and confirms data + account numbering
survived a genuine restart.
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import requests

PROJECT_ROOT = "/home/claude/bankaccount-webapp"
PORT = 5099
BASE = f"http://127.0.0.1:{PORT}"

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


def start_server(storage_path):
    code = (
        "import sys; "
        f"sys.path.insert(0, {PROJECT_ROOT + '/backend'!r}); "
        "from app import create_app; "
        f"app = create_app({storage_path!r}); "
        f"app.run(port={PORT}, use_reloader=False)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Wait for the server to come up.
    for _ in range(50):
        try:
            requests.get(f"{BASE}/accounts", timeout=0.5)
            return proc
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
    stdout, stderr = proc.communicate(timeout=1)
    raise RuntimeError(f"Server did not start.\nstdout={stdout}\nstderr={stderr}")


def stop_server(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


tmpdir = tempfile.mkdtemp(prefix="fullsystem_restart_test_")
storage_path = os.path.join(tmpdir, "accounts.json")

# ---- First run: create accounts, deposit, transfer ----
proc = start_server(storage_path)
try:
    alice = requests.post(f"{BASE}/accounts", json={"name": "Alice"}).json()["data"]
    bob = requests.post(f"{BASE}/accounts", json={"name": "Bob"}).json()["data"]
    check("create account (real HTTP) - Alice", alice["balance"] == 0 and alice["name"] == "Alice")
    check("create account (real HTTP) - Bob", bob["balance"] == 0 and bob["name"] == "Bob")

    r = requests.post(f"{BASE}/accounts/{alice['account_number']}/deposit", json={"amount": 300})
    check("deposit (real HTTP)", r.status_code == 200 and r.json()["data"]["balance"] == 300)

    r = requests.post(f"{BASE}/accounts/{alice['account_number']}/withdraw", json={"amount": 50})
    check("withdraw (real HTTP)", r.status_code == 200 and r.json()["data"]["balance"] == 250)

    r = requests.post(
        f"{BASE}/accounts/{alice['account_number']}/transfer",
        json={"destination_account_number": bob["account_number"], "amount": 100},
    )
    body = r.json()["data"]
    check(
        "transfer (real HTTP) updates both balances",
        r.status_code == 200 and body["source"]["balance"] == 150 and body["destination"]["balance"] == 100,
    )

    # Confirm the file on disk actually has this (not just the HTTP response).
    with open(storage_path) as f:
        on_disk = json.load(f)
    records = {rec["account_number"]: rec["balance"] for rec in on_disk["accounts"]}
    check(
        "on-disk file matches HTTP responses before restart",
        records[alice["account_number"]] == 150 and records[bob["account_number"]] == 100,
    )
finally:
    stop_server(proc)

# ---- "Restart": brand new subprocess (fresh Python process, fresh class
# state), pointed at the exact same storage file. ----
proc = start_server(storage_path)
try:
    r = requests.get(f"{BASE}/accounts")
    accounts_after_restart = {a["account_number"]: a for a in r.json()["data"]}
    check(
        "data survives a real process restart",
        accounts_after_restart[alice["account_number"]]["balance"] == 150
        and accounts_after_restart[bob["account_number"]]["balance"] == 100
        and accounts_after_restart[alice["account_number"]]["name"] == "Alice"
        and accounts_after_restart[bob["account_number"]]["name"] == "Bob",
    )

    carol = requests.post(f"{BASE}/accounts", json={"name": "Carol"}).json()["data"]
    check(
        "new account after restart does not collide with restored numbers",
        carol["account_number"] not in (alice["account_number"], bob["account_number"])
        and carol["account_number"] > max(alice["account_number"], bob["account_number"]),
    )
finally:
    stop_server(proc)

# ---- Missing storage file: a path that has never existed should start empty ----
missing_path = os.path.join(tmpdir, "never_existed.json")
proc = start_server(missing_path)
try:
    r = requests.get(f"{BASE}/accounts")
    check("missing storage file starts with empty account list (real server)", r.json()["data"] == [])
finally:
    stop_server(proc)

# ---- Corrupted storage file: server process should fail to start at all ----
corrupt_path = os.path.join(tmpdir, "corrupt.json")
with open(corrupt_path, "w") as f:
    f.write("{ not valid json")

code = (
    "import sys; "
    f"sys.path.insert(0, {(PROJECT_ROOT + '/backend')!r}); "
    "from app import create_app; "
    f"create_app({corrupt_path!r})"
)
result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=10)
check(
    "corrupted storage prevents server startup (nonzero exit, storage error in output)",
    result.returncode != 0 and "StorageReadError" in result.stderr,
)

print(f"\n{passed} passed, {failed} failed")
