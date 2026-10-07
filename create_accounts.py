import os
import re
import csv
import requests

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

# ============================================================
# LIVE MODE
# ============================================================

DRY_RUN = False

AUDIT_FILE = "crm_create_audit.csv"

# ============================================================
# ONLY THESE FOUR ACCOUNTS MAY BE CREATED
# Chagrin Falls is NOT here because it was already updated.
# ============================================================

ACCOUNTS_TO_CREATE = [
    {
        "name": "Amberly Manor",
        "billing_street": "4390 Darrow Rd",
        "billing_city": "Hudson",
        "billing_state": "OH",
        "billing_zip": "44236",
        "phone": "(330) 228-4392",
    },
    {
        "name": "Bellhaven Willow Creek",
        "billing_street": "8068 Willow Creek Ln",
        "billing_city": "Portage",
        "billing_state": "MI",
        "billing_zip": "49024",
        "phone": "(419) 394-5494",
    },
    {
        "name": "Bellhaven of Batavia",
        "billing_street": "2000 Hospital Dr",
        "billing_city": "Batavia",
        "billing_state": "OH",
        "billing_zip": "45103",
        "phone": "(231) 698-3092",
    },
    {
        "name": "Bellhaven of Carlisle",
        "billing_street": "640 Walnut Bottom Rd",
        "billing_city": "Carlisle",
        "billing_state": "PA",
        "billing_zip": "17015",
        "phone": "(260) 386-7765",
    },
]

# ============================================================
# HELPERS
# ============================================================


def normalize(value):
    if value is None:
        return ""

    value = str(value).lower().strip()

    value = value.replace("street", "st")
    value = value.replace("avenue", "ave")
    value = value.replace("road", "rd")
    value = value.replace("drive", "dr")
    value = value.replace("lane", "ln")
    value = value.replace("boulevard", "blvd")
    value = value.replace("northwest", "nw")
    value = value.replace("northeast", "ne")
    value = value.replace("southwest", "sw")
    value = value.replace("southeast", "se")

    value = re.sub(r"[^a-z0-9]", "", value)

    return value


def normalize_phone(value):
    if not value:
        return ""

    digits = re.sub(r"\D", "", str(value))

    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    return digits


def exact_location_match(existing, target):
    """
    A duplicate requires the SAME physical location.

    We require:
    - street match
    - city match
    - state match
    - ZIP match

    Name alone is NOT enough.
    """

    street_match = normalize(existing.get("billing_street")) == normalize(
        target["billing_street"]
    )

    city_match = normalize(existing.get("billing_city")) == normalize(
        target["billing_city"]
    )

    state_match = normalize(existing.get("billing_state")) == normalize(
        target["billing_state"]
    )

    zip_match = normalize(existing.get("billing_zip")) == normalize(
        target["billing_zip"]
    )

    return street_match and city_match and state_match and zip_match


def search_accounts(params):
    response = requests.get(
        f"{BASE_URL}/accounts",
        headers=HEADERS,
        params=params,
        timeout=30,
    )

    print("Search:", params, "-> status", response.status_code)

    if response.status_code != 200:
        print("Search response:", response.text)
        raise RuntimeError("CRM search failed.")

    body = response.json()

    results = body.get("data", [])

    print("Results:", len(results))

    return results


def get_account(account_id):
    response = requests.get(
        f"{BASE_URL}/accounts/{account_id}",
        headers=HEADERS,
        timeout=30,
    )

    print("Verification GET status:", response.status_code)

    if response.status_code != 200:
        print("GET response:", response.text)
        return None

    return response.json()


def verify_created_account(account, target):
    if not account:
        return False

    name_ok = normalize(account.get("name")) == normalize(target["name"])

    street_ok = normalize(account.get("billing_street")) == normalize(
        target["billing_street"]
    )

    city_ok = normalize(account.get("billing_city")) == normalize(
        target["billing_city"]
    )

    state_ok = normalize(account.get("billing_state")) == normalize(
        target["billing_state"]
    )

    zip_ok = normalize(account.get("billing_zip")) == normalize(target["billing_zip"])

    phone_ok = normalize_phone(account.get("phone")) == normalize_phone(target["phone"])

    print("Name verified:", name_ok)
    print("Street verified:", street_ok)
    print("City verified:", city_ok)
    print("State verified:", state_ok)
    print("ZIP verified:", zip_ok)
    print("Phone verified:", phone_ok)

    return all(
        [
            name_ok,
            street_ok,
            city_ok,
            state_ok,
            zip_ok,
            phone_ok,
        ]
    )


# ============================================================
# FINAL DUPLICATE CHECK
# ============================================================


def find_physical_duplicate(target):
    """
    Search several ways.

    IMPORTANT:
    A search hit is NOT automatically a duplicate.

    Only a record at the same physical location blocks creation.
    """

    searches = [
        {
            "q": target["name"],
            "page": 1,
            "page_size": 100,
        },
        {
            "city": target["billing_city"],
            "state": target["billing_state"],
            "page": 1,
            "page_size": 100,
        },
        {
            "zip": target["billing_zip"],
            "page": 1,
            "page_size": 100,
        },
        {
            "street": target["billing_street"],
            "page": 1,
            "page_size": 100,
        },
    ]

    unique_records = {}

    for params in searches:
        results = search_accounts(params)

        for account in results:
            account_id = account.get("account_id")

            if account_id:
                unique_records[account_id] = account

    print()
    print("Unique CRM records returned:", len(unique_records))

    physical_matches = []

    for account in unique_records.values():
        print()
        print("Checking CRM candidate:")
        print("Account ID:", account.get("account_id"))
        print("Name:", account.get("name"))
        print(
            "Address:",
            account.get("billing_street"),
            account.get("billing_city"),
            account.get("billing_state"),
            account.get("billing_zip"),
        )
        print("Phone:", account.get("phone"))

        location_match = exact_location_match(account, target)

        print("Same physical location:", location_match)

        if location_match:
            physical_matches.append(account)

    return physical_matches


# ============================================================
# AUDIT
# ============================================================

audit_rows = []

created_count = 0
blocked_count = 0
failed_count = 0


def write_audit():
    fieldnames = [
        "name",
        "billing_street",
        "billing_city",
        "billing_state",
        "billing_zip",
        "phone",
        "result",
        "account_id",
        "details",
    ]

    with open(
        AUDIT_FILE,
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in audit_rows:
            writer.writerow(row)


# ============================================================
# MAIN
# ============================================================

print("=" * 80)
print("BELLHAVEN CRM — LIVE ACCOUNT CREATION")
print("=" * 80)

if DRY_RUN:
    print()
    print("MODE: DRY RUN")
    print("NO POST REQUESTS WILL BE SENT.")
else:
    print()
    print("LIVE MODE")
    print("Maximum records that can be created:", len(ACCOUNTS_TO_CREATE))
    print("Any failure will STOP the script immediately.")

print()


for index, target in enumerate(ACCOUNTS_TO_CREATE, start=1):
    print("=" * 80)
    print(f"ACCOUNT {index}/{len(ACCOUNTS_TO_CREATE)}")
    print("=" * 80)

    print("Name:", target["name"])

    print(
        "Address:",
        target["billing_street"],
        target["billing_city"],
        target["billing_state"],
        target["billing_zip"],
    )

    print("Phone:", target["phone"])

    print()
    print("STEP 1: FINAL PHYSICAL DUPLICATE CHECK")

    try:
        duplicates = find_physical_duplicate(target)

    except Exception as exc:
        failed_count += 1

        print()
        print("ERROR DURING DUPLICATE CHECK:")
        print(exc)

        audit_rows.append(
            {
                **target,
                "result": "FAILED_DUPLICATE_CHECK",
                "account_id": "",
                "details": str(exc),
            }
        )

        write_audit()

        print()
        print("STOPPING SCRIPT.")
        break

    # ========================================================
    # BLOCK ONLY SAME PHYSICAL LOCATION
    # ========================================================

    if duplicates:
        blocked_count += 1

        print()
        print("BLOCKED — SAME PHYSICAL LOCATION EXISTS")

        for existing in duplicates:
            print()
            print("Existing CRM:")
            print("Account ID:", existing.get("account_id"))
            print("Name:", existing.get("name"))

            print(
                "Address:",
                existing.get("billing_street"),
                existing.get("billing_city"),
                existing.get("billing_state"),
                existing.get("billing_zip"),
            )

            print("Phone:", existing.get("phone"))

        audit_rows.append(
            {
                **target,
                "result": "BLOCKED_PHYSICAL_DUPLICATE",
                "account_id": duplicates[0].get("account_id", ""),
                "details": "Same physical location already exists in CRM.",
            }
        )

        write_audit()

        print()
        print("STOPPING SCRIPT.")
        break

    # ========================================================
    # NO PHYSICAL DUPLICATE
    # ========================================================

    print()
    print("NO SAME-LOCATION CRM RECORD FOUND.")

    print()
    print("STEP 2: CREATE PAYLOAD")

    payload = {
        "name": target["name"],
        "billing_street": target["billing_street"],
        "billing_city": target["billing_city"],
        "billing_state": target["billing_state"],
        "billing_zip": target["billing_zip"],
        "phone": target["phone"],
    }

    print(payload)

    # ========================================================
    # DRY RUN
    # ========================================================

    if DRY_RUN:
        print()
        print("DRY RUN APPROVED.")
        print("POST NOT SENT.")

        audit_rows.append(
            {
                **target,
                "result": "DRY_RUN_APPROVED",
                "account_id": "",
                "details": "No physical duplicate found.",
            }
        )

        continue

    # ========================================================
    # LIVE CREATE
    # ========================================================

    print()
    print("STEP 3: LIVE POST")

    try:
        response = requests.post(
            f"{BASE_URL}/accounts",
            headers=HEADERS,
            json=payload,
            timeout=30,
        )

    except Exception as exc:
        failed_count += 1

        print("POST REQUEST FAILED:")
        print(exc)

        audit_rows.append(
            {
                **target,
                "result": "POST_EXCEPTION",
                "account_id": "",
                "details": str(exc),
            }
        )

        write_audit()

        print()
        print("STOPPING SCRIPT.")
        break

    print("POST status:", response.status_code)
    print("POST response:", response.text)

    if response.status_code not in (200, 201):
        failed_count += 1

        audit_rows.append(
            {
                **target,
                "result": "CREATE_FAILED",
                "account_id": "",
                "details": response.text,
            }
        )

        write_audit()

        print()
        print("CREATE FAILED.")
        print("STOPPING SCRIPT.")
        break

    # ========================================================
    # GET NEW ACCOUNT ID
    # ========================================================

    try:
        response_data = response.json()
    except Exception:
        response_data = {}

    account_id = response_data.get("account_id")

    if not account_id:
        failed_count += 1

        print()
        print("ERROR: CREATE succeeded but no account_id returned.")

        audit_rows.append(
            {
                **target,
                "result": "CREATED_NO_ACCOUNT_ID",
                "account_id": "",
                "details": response.text,
            }
        )

        write_audit()

        print()
        print("STOPPING SCRIPT.")
        break

    print()
    print("Created Account ID:", account_id)

    # ========================================================
    # VERIFY CREATED ACCOUNT
    # ========================================================

    print()
    print("STEP 4: READ ACCOUNT BACK")

    created_account = get_account(account_id)

    if not created_account:
        failed_count += 1

        audit_rows.append(
            {
                **target,
                "result": "CREATED_GET_FAILED",
                "account_id": account_id,
                "details": "Could not retrieve newly created account.",
            }
        )

        write_audit()

        print()
        print("STOPPING SCRIPT.")
        break

    print()
    print("CRM RECORD AFTER CREATE")

    print("Account ID:", created_account.get("account_id"))
    print("Name:", created_account.get("name"))

    print(
        "Address:",
        created_account.get("billing_street"),
        created_account.get("billing_city"),
        created_account.get("billing_state"),
        created_account.get("billing_zip"),
    )

    print("Phone:", created_account.get("phone"))

    # ========================================================
    # FINAL VERIFICATION
    # ========================================================

    print()
    print("STEP 5: VERIFY CREATED VALUES")

    verified = verify_created_account(
        created_account,
        target,
    )

    if not verified:
        failed_count += 1

        audit_rows.append(
            {
                **target,
                "result": "CREATED_VERIFICATION_FAILED",
                "account_id": account_id,
                "details": "Created record does not exactly match intended values.",
            }
        )

        write_audit()

        print()
        print("VERIFICATION FAILED.")
        print("STOPPING SCRIPT.")
        break

    # ========================================================
    # SUCCESS
    # ========================================================

    created_count += 1

    audit_rows.append(
        {
            **target,
            "result": "CREATED_AND_VERIFIED",
            "account_id": account_id,
            "details": "Created successfully and read-back verification passed.",
        }
    )

    write_audit()

    print()
    print("SUCCESS — CREATED AND VERIFIED")
    print()


# ============================================================
# FINAL AUDIT WRITE
# ============================================================

write_audit()

# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 80)
print("FINAL SUMMARY")
print("=" * 80)

print("Approved create candidates:", len(ACCOUNTS_TO_CREATE))
print("Created and verified:", created_count)
print("Blocked:", blocked_count)
print("Failed:", failed_count)

print()
print("Audit log:", AUDIT_FILE)

if (
    not DRY_RUN
    and created_count == len(ACCOUNTS_TO_CREATE)
    and blocked_count == 0
    and failed_count == 0
):
    print()
    print("SUCCESS.")
    print("ALL FOUR ACCOUNTS CREATED AND VERIFIED.")

elif DRY_RUN:
    print()
    print("DRY RUN COMPLETE.")
    print("NO CRM DATA WAS MODIFIED.")

else:
    print()
    print("SCRIPT DID NOT COMPLETE ALL FOUR ACCOUNTS.")
    print("DO NOT RERUN AUTOMATICALLY.")
    print("REVIEW THE OUTPUT FIRST.")
