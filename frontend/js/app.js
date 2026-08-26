/*
 * Frontend logic for the BankAccount SPA.
 *
 * This file is the ONLY thing that talks to the backend. It never touches
 * JSON storage, never recalculates a balance itself, and never re-implements
 * a banking rule (e.g. it doesn't check "is this amount positive?" beyond a
 * basic HTML5 hint - that check for real still happens on the server).
 *
 * After every operation that changes state (create/deposit/withdraw/transfer)
 * we re-fetch the account list from the backend rather than guessing the new
 * balance locally - the backend is the source of truth.
 */

const API_BASE = ""; // same origin as the page - Flask serves both, so no CORS needed

// ------------------------------------------------------------------
// Small API helper
// ------------------------------------------------------------------

/**
 * Perform a fetch() against the API and return the parsed `data` on
 * success. On any API error response ({"error": {code, message}}),
 * throws an Error whose message is the backend's human-readable message
 * (falls back to a generic message if the body can't be parsed at all -
 * e.g. a network failure or the server being unreachable).
 *
 * Note: this only ever reads `error.message` from the response body - it
 * never depends on a specific Python exception's wording. The `{code,
 * message}` shape is the API contract (see API_CONTRACT.md); this is the
 * only thing the frontend relies on.
 */
async function apiRequest(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "Content-Type": "application/json" },
      ...options,
    });
  } catch (networkError) {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }

  let body = null;
  try {
    body = await response.json();
  } catch (parseError) {
    // Not JSON at all - shouldn't normally happen against this API.
    body = null;
  }

  if (!response.ok) {
    const message =
      body && body.error && body.error.message
        ? body.error.message
        : `Request failed (HTTP ${response.status}).`;
    throw new Error(message);
  }

  return body ? body.data : null;
}

// ------------------------------------------------------------------
// UI helpers: messages + loading state
// ------------------------------------------------------------------

const MESSAGE_PREFIX = { success: "\u2713 ", error: "\u26a0 ", info: "" };

/**
 * Shows a status/error/info message in the given element.
 *
 * The element's `role` is switched between "alert" (errors - announced
 * immediately by screen readers) and "status" (success/info - announced
 * politely, without interrupting). Combined with the `aria-live="polite"`
 * already set in the HTML, this keeps feedback accessible without any
 * extra markup per message.
 */
function showMessage(elementId, text, kind) {
  const el = document.getElementById(elementId);
  const prefix = MESSAGE_PREFIX[kind] || "";
  el.textContent = text ? `${prefix}${text}` : "";
  el.className = "message" + (kind ? ` ${kind}` : "");
  el.setAttribute("role", kind === "error" ? "alert" : "status");
}

function clearMessage(elementId) {
  showMessage(elementId, "", "");
}

/**
 * Disables the form's submit button and shows a temporary label while an
 * async action runs, then restores it - success or failure - in a finally
 * block, so the button never gets stuck disabled and the UI always
 * recovers, even if the request throws.
 */
async function withLoadingState(button, loadingLabel, action) {
  const originalLabel = button.textContent;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.textContent = loadingLabel;
  try {
    return await action();
  } finally {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = originalLabel;
  }
}

function formatBalance(balance) {
  return Number(balance).toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Runs the browser's built-in constraint validation (required/min/step,
 * etc.) and, if anything is invalid, shows the browser's native validation
 * bubble on the offending field and focuses it. This is a UX convenience
 * only - it prevents obviously invalid input (empty fields, amounts below
 * the minimum) from ever reaching the network, but it is never a
 * substitute for the backend's own validation, since the API can always
 * be called directly without going through this form at all.
 */
function formIsValid(form) {
  if (form.checkValidity()) {
    return true;
  }
  form.reportValidity();
  return false;
}

// ------------------------------------------------------------------
// Accounts list
// ------------------------------------------------------------------

async function loadAccounts() {
  try {
    const accounts = await apiRequest("/accounts");
    renderAccounts(accounts);
    clearMessage("accounts-message");
  } catch (err) {
    showMessage("accounts-message", `Could not load accounts: ${err.message}`, "error");
  }
}

function renderAccounts(accounts) {
  const tbody = document.getElementById("accounts-table-body");
  const emptyHint = document.getElementById("accounts-empty");

  tbody.innerHTML = "";

  if (!accounts || accounts.length === 0) {
    emptyHint.hidden = false;
    return;
  }
  emptyHint.hidden = true;

  // Sort by account number so the list is easy to scan and stays in a
  // predictable order regardless of backend iteration order.
  const sorted = [...accounts].sort((a, b) => a.account_number - b.account_number);

  for (const account of sorted) {
    const row = document.createElement("tr");

    const numberCell = document.createElement("td");
    numberCell.textContent = account.account_number;

    const nameCell = document.createElement("td");
    nameCell.textContent = account.name;

    const balanceCell = document.createElement("td");
    balanceCell.textContent = formatBalance(account.balance);

    row.append(numberCell, nameCell, balanceCell);
    tbody.appendChild(row);
  }
}

// ------------------------------------------------------------------
// Create account
// ------------------------------------------------------------------

function setupCreateAccountForm() {
  const form = document.getElementById("create-account-form");
  const button = form.querySelector("button[type=submit]");
  const nameInput = document.getElementById("create-name");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return; // ignore accidental double-submits

    clearMessage("create-account-message");
    if (!formIsValid(form)) return;

    const name = nameInput.value.trim();

    await withLoadingState(button, "Creating...", async () => {
      try {
        const account = await apiRequest("/accounts", {
          method: "POST",
          body: JSON.stringify({ name }),
        });
        // Refresh the account list BEFORE announcing success, so the table
        // is already showing the latest state by the time the user sees
        // (and screen readers announce) the success message.
        await loadAccounts();
        showMessage(
          "create-account-message",
          `Account ${account.account_number} created for ${account.name}.`,
          "success"
        );
        form.reset();
        nameInput.focus();
      } catch (err) {
        // Input is left as-is on failure so the user doesn't have to retype it.
        showMessage("create-account-message", `Could not create account: ${err.message}`, "error");
      }
    });
  });
}

// ------------------------------------------------------------------
// Deposit
// ------------------------------------------------------------------

function setupDepositForm() {
  const form = document.getElementById("deposit-form");
  const button = form.querySelector("button[type=submit]");
  const accountNumberInput = document.getElementById("deposit-account-number");
  const amountInput = document.getElementById("deposit-amount");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;

    clearMessage("deposit-message");
    if (!formIsValid(form)) return;

    const accountNumber = accountNumberInput.value;
    const amount = amountInput.value;

    await withLoadingState(button, "Depositing...", async () => {
      try {
        const account = await apiRequest(`/accounts/${accountNumber}/deposit`, {
          method: "POST",
          body: JSON.stringify({ amount: Number(amount) }),
        });
        await loadAccounts();
        showMessage(
          "deposit-message",
          `Deposited. Account ${account.account_number} balance is now ${formatBalance(account.balance)}.`,
          "success"
        );
        form.reset();
        accountNumberInput.focus();
      } catch (err) {
        showMessage("deposit-message", `Deposit failed: ${err.message}`, "error");
      }
    });
  });
}

// ------------------------------------------------------------------
// Withdraw
// ------------------------------------------------------------------

function setupWithdrawForm() {
  const form = document.getElementById("withdraw-form");
  const button = form.querySelector("button[type=submit]");
  const accountNumberInput = document.getElementById("withdraw-account-number");
  const amountInput = document.getElementById("withdraw-amount");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;

    clearMessage("withdraw-message");
    if (!formIsValid(form)) return;

    const accountNumber = accountNumberInput.value;
    const amount = amountInput.value;

    await withLoadingState(button, "Withdrawing...", async () => {
      try {
        const account = await apiRequest(`/accounts/${accountNumber}/withdraw`, {
          method: "POST",
          body: JSON.stringify({ amount: Number(amount) }),
        });
        await loadAccounts();
        showMessage(
          "withdraw-message",
          `Withdrew. Account ${account.account_number} balance is now ${formatBalance(account.balance)}.`,
          "success"
        );
        form.reset();
        accountNumberInput.focus();
      } catch (err) {
        showMessage("withdraw-message", `Withdrawal failed: ${err.message}`, "error");
      }
    });
  });
}

// ------------------------------------------------------------------
// Transfer
// ------------------------------------------------------------------

function setupTransferForm() {
  const form = document.getElementById("transfer-form");
  const button = form.querySelector("button[type=submit]");
  const sourceInput = document.getElementById("transfer-source");
  const destinationInput = document.getElementById("transfer-destination");
  const amountInput = document.getElementById("transfer-amount");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (button.disabled) return;

    clearMessage("transfer-message");
    if (!formIsValid(form)) return;

    const sourceAccountNumber = sourceInput.value;
    const destinationAccountNumber = destinationInput.value;
    const amount = amountInput.value;

    await withLoadingState(button, "Transferring...", async () => {
      try {
        const result = await apiRequest(`/accounts/${sourceAccountNumber}/transfer`, {
          method: "POST",
          body: JSON.stringify({
            destination_account_number: Number(destinationAccountNumber),
            amount: Number(amount),
          }),
        });
        await loadAccounts();
        showMessage(
          "transfer-message",
          `Transferred. Account ${result.source.account_number} is now ` +
            `${formatBalance(result.source.balance)}; account ${result.destination.account_number} ` +
            `is now ${formatBalance(result.destination.balance)}.`,
          "success"
        );
        form.reset();
        sourceInput.focus();
      } catch (err) {
        showMessage("transfer-message", `Transfer failed: ${err.message}`, "error");
      }
    });
  });
}

// ------------------------------------------------------------------
// Wire everything up once the page has loaded
// ------------------------------------------------------------------

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refresh-accounts-btn").addEventListener("click", loadAccounts);

  setupCreateAccountForm();
  setupDepositForm();
  setupWithdrawForm();
  setupTransferForm();

  loadAccounts(); // initial load

  // Convenience: put the cursor in the first, most commonly-used field.
  document.getElementById("create-name").focus();
});
