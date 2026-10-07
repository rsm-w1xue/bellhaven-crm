import os
import csv
import re
import requests
from datetime import datetime

# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://analyst-assessment-production.up.railway.app/api/v1"

TOKEN = os.getenv("BELLHAVEN_API_TOKEN")

if not TOKEN:
    raise RuntimeError("BELLHAVEN_API_TOKEN is not set.")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}

# SAFETY SWITCH
# These updates have ALREADY been completed.
# Keep this True.
DRY_RUN = True

AUDIT_FILE = "crm_update_audit.csv"


# ============================================================
# ORIGINAL TWO APPROVED UPDATES
# ============================================================

APPROVED_UPDATES = [
    {
        "label": "Chesterton",
        "search": "Chesterton",
        "expected_current_name": "Chesterton Senior Commons",
        "expected_street": "1250 Northwest Franklin St",
        "expected_city": "Chesterton",
        "expected_state": "IN",
        "expected_zip": "46304",
        "new_values": {
            "name": "Bellhaven of Chesterton",
        },
    },
    {
        "label": "Zanesville",
        "search": "Zanesville",
        "expected_current_name": "Cedar Trail of Zanesville",
        "expected_street": "2680 Maple Avenue",
        "expected_city": "Zanesville",
        "expected_state": "OH",
        "expected_zip": "43701",
        "new_values": {
            "name": "Bellhaven of Zanesville",
            "phone": "(814) 599-2533",
        },
    },
]


# ============================================================
# HELPERS
# ============================================================


def normalize(value):
    if value is None:
        return ""

    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def address_matches(account, item):
    return (
        normalize(account.get("billing_street")) == normalize(item["expected_street"])
        and normalize(account.get("billing_city")) == normalize(item["expected_city"])
        and normalize(account.get("billing_state")) == normalize(item["expected_state"])
        and normalize(account.get("billing_zip")) == normalize(item["expected_zip"])
    )


def search_accounts(query):
    response = requests.get(
        f"{BASE_URL}/accounts",
        headers=HEADERS,
        params={
            "q": query,
            "page": 1,
            "page_size": 50,
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise RuntimeError(f"Search failed: {response.status_code} {response.text}")

    return response.json().get("data", [])


def get_account(account_id):
    response = requests.get(
        f"{BASE_URL}/accounts/{account_id}",
        headers=HEADERS,
        timeout=30,
    )

    return response


# ============================================================
# START
# ============================================================

print("=" * 80)
print("CRM UPDATE SCRIPT")
print("=" * 80)

if DRY_RUN:
    print("MODE: DRY RUN")
else:
    print("MODE: LIVE")

print()

audit_rows = []

found_count = 0
verified_count = 0
updated_count = 0
blocked_count = 0
failed_count = 0


# ============================================================
# PROCESS
# ============================================================

for item in APPROVED_UPDATES:
    print()
    print("=" * 80)
    print(item["label"].upper())
    print("=" * 80)

    print("\nSTEP 1: Searching CRM...")

    try:
        accounts = search_accounts(item["search"])

    except requests.RequestException as e:
        print("FAILED:", e)
        failed_count += 1
        continue

    except RuntimeError as e:
        print("FAILED:", e)
        failed_count += 1
        continue

    print("CRM SEARCH RESULTS:")

    for number, account in enumerate(accounts, start=1):
        print()
        print(f"Result #{number}")
        print("Name:", account.get("name"))
        print("Account ID:", account.get("account_id"))
        print(
            "Address:",
            account.get("billing_street"),
            account.get("billing_city"),
            account.get("billing_state"),
            account.get("billing_zip"),
        )
        print("Phone:", account.get("phone"))

    # ========================================================
    # FIND EXACT RECORD
    # ========================================================

    print("\nSTEP 2: Finding exact CRM record...")

    exact_matches = [
        account
        for account in accounts
        if (
            normalize(account.get("name")) == normalize(item["expected_current_name"])
            and address_matches(account, item)
        )
    ]

    if len(exact_matches) != 1:
        print("BLOCKED: Expected exactly one exact CRM record.")
        print("Exact matches:", len(exact_matches))

        blocked_count += 1

        audit_rows.append(
            {
                "timestamp": datetime.now().isoformat(),
                "label": item["label"],
                "account_id": "",
                "action": "BLOCKED",
                "details": (f"Expected 1 exact record, found {len(exact_matches)}"),
            }
        )

        continue

    target = exact_matches[0]
    account_id = target["account_id"]

    found_count += 1

    print("\nEXACT TARGET FOUND")
    print("Name:", target.get("name"))
    print("Account ID:", account_id)
    print(
        "Address:",
        target.get("billing_street"),
        target.get("billing_city"),
        target.get("billing_state"),
        target.get("billing_zip"),
    )
    print("Phone:", target.get("phone"))

    # ========================================================
    # GET BY ACCOUNT ID
    # ========================================================

    print("\nSTEP 3: Verifying Account ID with GET...")

    try:
        response = get_account(account_id)

    except requests.RequestException as e:
        print("FAILED:", e)
        failed_count += 1
        continue

    print("GET status:", response.status_code)

    if response.status_code != 200:
        print("BLOCKED:", response.text)
        blocked_count += 1
        continue

    current = response.json()

    # ========================================================
    # FINAL PRE-PATCH VERIFICATION
    # ========================================================

    print("\nSTEP 4: Final safety verification...")

    print("\nCurrent CRM:")
    print("Name:", current.get("name"))
    print(
        "Address:",
        current.get("billing_street"),
        current.get("billing_city"),
        current.get("billing_state"),
        current.get("billing_zip"),
    )
    print("Phone:", current.get("phone"))

    name_matches = normalize(current.get("name")) == normalize(
        item["expected_current_name"]
    )

    address_ok = address_matches(current, item)

    if not name_matches or not address_ok:
        print("\nBLOCKED")
        print("Current CRM no longer matches expected record.")

        blocked_count += 1
        continue

    verified_count += 1

    print("\nVERIFIED")
    print("Name matches.")
    print("Address matches.")
    print("Account ID works.")

    # ========================================================
    # BUILD PATCH PAYLOAD
    # ========================================================

    payload = {}

    for field, new_value in item["new_values"].items():
        if normalize(current.get(field)) != normalize(new_value):
            payload[field] = new_value

    print("\nSTEP 5: Proposed update")

    print("\nBEFORE:")
    print("Name:", current.get("name"))
    print("Phone:", current.get("phone"))

    print("\nAFTER:")
    print("Name:", item["new_values"].get("name", current.get("name")))
    print("Phone:", item["new_values"].get("phone", current.get("phone")))

    print("\nPATCH payload:")
    print(payload)

    # ========================================================
    # NOTHING TO UPDATE
    # ========================================================

    if not payload:
        print("\nNO CHANGE NEEDED.")
        print("CRM already contains the desired values.")

        audit_rows.append(
            {
                "timestamp": datetime.now().isoformat(),
                "label": item["label"],
                "account_id": account_id,
                "action": "NO_CHANGE",
                "details": "Already matches desired values",
            }
        )

        continue

    # ========================================================
    # DRY RUN
    # ========================================================

    if DRY_RUN:
        print("\nDRY RUN APPROVED")
        print("PATCH NOT SENT.")
        print("NO CRM DATA MODIFIED.")

        audit_rows.append(
            {
                "timestamp": datetime.now().isoformat(),
                "label": item["label"],
                "account_id": account_id,
                "action": "DRY_RUN",
                "details": str(payload),
            }
        )

        continue

    # ========================================================
    # LIVE PATCH
    # ========================================================

    print("\nSTEP 6: LIVE PATCH...")

    try:
        response = requests.patch(
            f"{BASE_URL}/accounts/{account_id}",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )

    except requests.RequestException as e:
        print("FAILED:", e)
        failed_count += 1
        continue

    print("PATCH status:", response.status_code)
    print("PATCH response:", response.text)

    if response.status_code != 200:
        print("FAILED.")
        failed_count += 1
        continue

    # ========================================================
    # VERIFY AFTER PATCH
    # ========================================================

    print("\nSTEP 7: Reading CRM again...")

    try:
        response = get_account(account_id)

    except requests.RequestException as e:
        print("FAILED:", e)
        failed_count += 1
        continue

    print("Verification GET status:", response.status_code)

    if response.status_code != 200:
        print("FAILED TO VERIFY.")
        failed_count += 1
        continue

    after = response.json()

    print("\nCRM AFTER PATCH:")
    print("Name:", after.get("name"))
    print("Phone:", after.get("phone"))

    verification_ok = True

    for field, expected_value in item["new_values"].items():
        if normalize(after.get(field)) != normalize(expected_value):
            verification_ok = False

    if verification_ok:
        print("\nSUCCESS - UPDATE VERIFIED")

        updated_count += 1

        audit_rows.append(
            {
                "timestamp": datetime.now().isoformat(),
                "label": item["label"],
                "account_id": account_id,
                "action": "UPDATED_AND_VERIFIED",
                "details": str(payload),
            }
        )

    else:
        print("\nFAILED - POST-PATCH VALUES DO NOT MATCH.")

        failed_count += 1

        audit_rows.append(
            {
                "timestamp": datetime.now().isoformat(),
                "label": item["label"],
                "account_id": account_id,
                "action": "VERIFY_FAILED",
                "details": str(payload),
            }
        )


# ============================================================
# WRITE AUDIT
# ============================================================

with open(AUDIT_FILE, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "timestamp",
            "label",
            "account_id",
            "action",
            "details",
        ],
    )

    writer.writeheader()
    writer.writerows(audit_rows)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 80)
print("FINAL SUMMARY")
print("=" * 80)

print("Approved updates:", len(APPROVED_UPDATES))
print("Exact CRM records found:", found_count)
print("Fully verified:", verified_count)
print("Real updates performed:", updated_count)
print("Blocked:", blocked_count)
print("Failed:", failed_count)

print()
print("Audit log:", AUDIT_FILE)

if DRY_RUN:
    print()
    print("SAFETY MODE.")
    print("Chesterton and Zanesville were already updated previously.")
    print("NO CRM DATA WAS MODIFIED.")
