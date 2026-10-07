import os
import re
import csv
import requests
from difflib import SequenceMatcher

# ============================================================
# CONFIG
# ============================================================

BASE_URL = "https://analyst-assessment-production.up.railway.app/api/v1"

TOKEN = os.getenv("BELLHAVEN_API_TOKEN")

if not TOKEN:
    raise ValueError(
        "BELLHAVEN_API_TOKEN is not set. "
        "Set the environment variable before running this script."
    )

HEADERS = {"Authorization": f"Bearer {TOKEN}"}

INPUT_FILE = "match_results_v2.csv"
OUTPUT_FILE = "reconciliation_final.csv"


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize(value):
    value = clean(value).lower()

    replacements = {
        "&": " and ",
        "rehabilitation": "rehab",
        "centre": "center",
        "saint": "st",
        "street": "st",
        "road": "rd",
        "avenue": "ave",
        "boulevard": "blvd",
        "drive": "dr",
        "lane": "ln",
        "highway": "hwy",
        "north": "n",
        "south": "s",
        "east": "e",
        "west": "w",
    }

    for old, new in replacements.items():
        value = value.replace(old, new)

    value = re.sub(r"[^a-z0-9 ]", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def normalize_phone(phone):
    return re.sub(r"\D", "", clean(phone))


def similarity(a, b):
    a = normalize(a)
    b = normalize(b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


def extract_zip(address):
    match = re.search(r"\b(\d{5})(?:-\d{4})?\b", clean(address))
    return match.group(1) if match else ""


def extract_city(address):
    address = clean(address)

    # Example:
    # 2600 Maple Ave Zanesville, OH 43701
    match = re.search(r",?\s*([A-Za-z .'-]+),?\s+[A-Z]{2}\s+\d{5}", address)

    if match:
        return normalize(match.group(1))

    return ""


def street_number(address):
    match = re.match(r"\s*(\d+)", clean(address))
    return match.group(1) if match else ""


# ============================================================
# GET ALL CRM ACCOUNTS
# ============================================================


def get_all_crm_accounts():

    accounts = []

    page = 1

    while True:
        response = requests.get(
            f"{BASE_URL}/accounts",
            headers=HEADERS,
            params={"page": page, "page_size": 50},
            timeout=30,
        )

        response.raise_for_status()

        data = response.json()

        page_accounts = data.get("data", [])

        accounts.extend(page_accounts)

        total = data.get("total", len(accounts))

        print(
            f"CRM page {page}: "
            f"{len(page_accounts)} records "
            f"(total collected: {len(accounts)}/{total})"
        )

        if len(accounts) >= total:
            break

        if not page_accounts:
            break

        page += 1

    return accounts


# ============================================================
# BUILD CRM ADDRESS
# ============================================================


def crm_address(account):

    parts = [
        account.get("billing_street"),
        account.get("billing_city"),
        account.get("billing_state"),
        account.get("billing_zip"),
    ]

    return " ".join(clean(x) for x in parts if clean(x))


# ============================================================
# SCORE ONE WEBSITE / CRM PAIR
# ============================================================


def calculate_match(website, crm):

    website_name = clean(website.get("website_name"))
    website_address = clean(website.get("website_address"))
    website_phone = clean(website.get("website_phone"))

    crm_name = clean(crm.get("name"))
    crm_addr = crm_address(crm)
    crm_phone = clean(crm.get("phone"))

    # --------------------------------------------------------
    # NAME
    # --------------------------------------------------------

    name_score = similarity(website_name, crm_name)

    # --------------------------------------------------------
    # ADDRESS
    # --------------------------------------------------------

    address_similarity = similarity(website_address, crm_addr)

    website_zip = extract_zip(website_address)
    crm_zip = clean(crm.get("billing_zip"))

    zip_match = bool(website_zip) and bool(crm_zip) and website_zip == crm_zip

    website_number = street_number(website_address)
    crm_number = street_number(clean(crm.get("billing_street")))

    street_number_match = (
        bool(website_number) and bool(crm_number) and website_number == crm_number
    )

    website_city = extract_city(website_address)
    crm_city = normalize(crm.get("billing_city"))

    city_match = bool(website_city) and bool(crm_city) and website_city == crm_city

    # --------------------------------------------------------
    # PHONE
    # --------------------------------------------------------

    wp = normalize_phone(website_phone)
    cp = normalize_phone(crm_phone)

    phone_match = bool(wp) and bool(cp) and wp[-10:] == cp[-10:]

    # --------------------------------------------------------
    # ADDRESS SCORE
    # --------------------------------------------------------

    address_score = address_similarity

    if street_number_match:
        address_score += 0.25

    if city_match:
        address_score += 0.15

    if zip_match:
        address_score += 0.20

    address_score = min(address_score, 1.0)

    # --------------------------------------------------------
    # OVERALL SCORE
    #
    # Address is intentionally strongest.
    # --------------------------------------------------------

    overall_score = (
        name_score * 0.30 + address_score * 0.55 + (1.0 if phone_match else 0.0) * 0.15
    )

    # --------------------------------------------------------
    # STRONG EXACT-EVIDENCE BOOST
    # --------------------------------------------------------

    exact_location = street_number_match and zip_match

    if exact_location:
        overall_score = max(overall_score, 0.90)

    if exact_location and phone_match:
        overall_score = max(overall_score, 0.97)

    if name_score >= 0.90 and address_score >= 0.85:
        overall_score = max(overall_score, 0.95)

    return {
        "crm": crm,
        "name_score": round(name_score, 3),
        "address_score": round(address_score, 3),
        "phone_match": int(phone_match),
        "zip_match": int(zip_match),
        "city_match": int(city_match),
        "street_number_match": int(street_number_match),
        "exact_location": int(exact_location),
        "overall_score": round(overall_score, 3),
    }


# ============================================================
# CLASSIFICATION
# ============================================================


def classify(best, second):

    if best is None:
        return "POSSIBLY_MISSING"

    score = best["overall_score"]
    name_score = best["name_score"]

    exact_location = best["exact_location"]
    phone_match = best["phone_match"]

    second_score = second["overall_score"] if second else 0

    gap = score - second_score

    # --------------------------------------------------------
    # Exact location but different name
    # Example:
    # Bellhaven of Zanesville
    # Cedar Trail of Zanesville
    # --------------------------------------------------------

    if exact_location and name_score < 0.75:
        return "RENAMED_OR_DIFFERENT_NAME"

    # --------------------------------------------------------
    # Very strong evidence
    # --------------------------------------------------------

    if score >= 0.90 and gap >= 0.08:
        return "MATCH"

    if phone_match and score >= 0.85:
        return "MATCH"

    # --------------------------------------------------------
    # Ambiguous
    # --------------------------------------------------------

    if score >= 0.60:
        return "REVIEW"

    # --------------------------------------------------------
    # Weak / likely absent
    # --------------------------------------------------------

    return "POSSIBLY_MISSING"


# ============================================================
# EXPLANATION
# ============================================================


def build_reason(best):

    if not best:
        return "No CRM candidate"

    reasons = []

    if best["name_score"] >= 0.90:
        reasons.append("strong name match")

    elif best["name_score"] >= 0.70:
        reasons.append("partial name match")

    else:
        reasons.append("different name")

    if best["street_number_match"]:
        reasons.append("same street number")

    if best["city_match"]:
        reasons.append("same city")

    if best["zip_match"]:
        reasons.append("same ZIP")

    if best["phone_match"]:
        reasons.append("same phone")

    if best["address_score"] >= 0.90:
        reasons.append("strong address match")

    return "; ".join(reasons)


# ============================================================
# LOAD WEBSITE DATA
# ============================================================


def load_website_data():

    with open(INPUT_FILE, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)

        rows = list(reader)

    return rows


# ============================================================
# MAIN
# ============================================================

print("=" * 80)
print("BELLHAVEN CRM RECONCILIATION")
print("=" * 80)

print()
print("Loading website communities...")

website_rows = load_website_data()

print("Website communities:", len(website_rows))

print()
print("Downloading CRM accounts...")

crm_accounts = get_all_crm_accounts()

print()
print("CRM accounts:", len(crm_accounts))

print()
print("=" * 80)
print("MATCHING")
print("=" * 80)

results = []


for website in website_rows:
    website_name = clean(website.get("website_name"))

    scores = []

    for crm in crm_accounts:
        result = calculate_match(website, crm)

        scores.append(result)

    scores.sort(key=lambda x: x["overall_score"], reverse=True)

    best = scores[0] if scores else None
    second = scores[1] if len(scores) > 1 else None

    decision = classify(best, second)

    best_crm = best["crm"] if best else {}

    second_crm = second["crm"] if second else {}

    best_address = crm_address(best_crm)

    second_address = crm_address(second_crm)

    reason = build_reason(best)

    row = {
        # WEBSITE
        "website_name": website_name,
        "website_address": clean(website.get("website_address")),
        "website_phone": clean(website.get("website_phone")),
        "care_offerings": clean(website.get("care_offerings")),
        "administrator": clean(website.get("administrator")),
        "website_url": clean(website.get("website_url")),
        # FINAL DECISION
        "decision": decision,
        "reason": reason,
        # BEST CRM
        "crm_account_id": clean(best_crm.get("id")),
        "crm_name": clean(best_crm.get("name")),
        "crm_address": best_address,
        "crm_phone": clean(best_crm.get("phone")),
        "crm_parent": clean(best_crm.get("parent_name")),
        "crm_status": clean(best_crm.get("status")),
        "crm_revenue": clean(best_crm.get("lifetime_revenue")),
        "crm_outstanding_ar": clean(best_crm.get("outstanding_ar")),
        # SCORES
        "name_score": best["name_score"] if best else 0,
        "address_score": best["address_score"] if best else 0,
        "phone_match": best["phone_match"] if best else 0,
        "street_number_match": best["street_number_match"] if best else 0,
        "city_match": best["city_match"] if best else 0,
        "zip_match": best["zip_match"] if best else 0,
        "overall_score": best["overall_score"] if best else 0,
        # SECOND BEST
        "second_best_name": clean(second_crm.get("name")),
        "second_best_address": second_address,
        "second_best_score": (second["overall_score"] if second else 0),
    }

    results.append(row)

    print()
    print("-" * 70)

    print("Website:", website_name)

    print("Decision:", decision)

    print("Best CRM:", row["crm_name"])

    print("CRM Address:", row["crm_address"])

    print("Score:", row["overall_score"])

    print("Reason:", reason)

    if second:
        print("Second best:", row["second_best_name"])

        print("Second score:", row["second_best_score"])


# ============================================================
# SAVE CSV
# ============================================================

fieldnames = [
    "website_name",
    "website_address",
    "website_phone",
    "care_offerings",
    "administrator",
    "website_url",
    "decision",
    "reason",
    "crm_account_id",
    "crm_name",
    "crm_address",
    "crm_phone",
    "crm_parent",
    "crm_status",
    "crm_revenue",
    "crm_outstanding_ar",
    "name_score",
    "address_score",
    "phone_match",
    "street_number_match",
    "city_match",
    "zip_match",
    "overall_score",
    "second_best_name",
    "second_best_address",
    "second_best_score",
]


with open(OUTPUT_FILE, "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)

    writer.writeheader()

    writer.writerows(results)


# ============================================================
# SUMMARY
# ============================================================

match_count = sum(r["decision"] == "MATCH" for r in results)

renamed_count = sum(r["decision"] == "RENAMED_OR_DIFFERENT_NAME" for r in results)

review_count = sum(r["decision"] == "REVIEW" for r in results)

missing_count = sum(r["decision"] == "POSSIBLY_MISSING" for r in results)


print()
print("=" * 80)
print("RECONCILIATION COMPLETE")
print("=" * 80)

print("Total website communities:", len(results))

print("MATCH:", match_count)

print("RENAMED / DIFFERENT NAME:", renamed_count)

print("REVIEW:", review_count)

print("POSSIBLY MISSING:", missing_count)

print()
print("Results saved to:", OUTPUT_FILE)

print("=" * 80)
