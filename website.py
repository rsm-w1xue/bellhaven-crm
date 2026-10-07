import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# Bellhaven website
BASE_URL = "https://analyst-assessment-production.up.railway.app"
COMMUNITIES_URL = f"{BASE_URL}/communities"

# -----------------------------------
# STEP 1: Collect all community links
# -----------------------------------

community_links = []

for page in range(1, 4):
    response = requests.get(COMMUNITIES_URL, params={"page": page})

    print(f"Page {page} status:", response.status_code)

    soup = BeautifulSoup(response.text, "html.parser")

    for link in soup.find_all("a", href=True):
        href = link["href"]

        if href.startswith("/communities/"):
            full_url = urljoin(BASE_URL, href)

            if full_url not in community_links:
                community_links.append(full_url)

print()
print("Total community links:", len(community_links))


# -----------------------------------
# STEP 2: Visit each community page
# and collect its information
# -----------------------------------

communities = []

print("\n--- COMMUNITY DETAILS ---\n")

for link in community_links:
    response = requests.get(link)
    soup = BeautifulSoup(response.text, "html.parser")

    text = soup.get_text(" ", strip=True)

    # Community name
    heading = soup.find("h1")
    name = heading.get_text(" ", strip=True) if heading else "Unknown"

    # Address
    address = text.split("Address", 1)[1].split("Care Offerings", 1)[0].strip()

    # Care offering
    care = text.split("Care Offerings", 1)[1].split("Administrator", 1)[0].strip()

    # Administrator
    administrator = text.split("Administrator", 1)[1].split("Phone", 1)[0].strip()

    # Phone
    phone = text.split("Phone", 1)[1].split("©", 1)[0].strip()

    # Save this community
    communities.append(
        {
            "name": name,
            "address": address,
            "care": care,
            "administrator": administrator,
            "phone": phone,
            "url": link,
        }
    )

    # Show result
    print("Name:", name)
    print("Address:", address)
    print("Care:", care)
    print("Administrator:", administrator)
    print("Phone:", phone)
    print("-" * 60)


# -----------------------------------
# STEP 3: Final check
# -----------------------------------

print()
print("Total communities collected:", len(communities))
