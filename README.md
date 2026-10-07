
# Bellhaven CRM Data Reconciliation

## Overview

This project reconciles Bellhaven Senior Living community information from the public Bellhaven website with the existing CRM account data.

The workflow included:

1. Extracting community information from the Bellhaven website.
2. Retrieving existing account records from the CRM API.
3. Matching website communities to CRM accounts using names and location information.
4. Investigating ambiguous or missing matches.
5. Updating CRM records when the website and CRM records could be confidently identified as the same community.
6. Creating CRM accounts when a website community was confirmed to be missing from the CRM.
7. Performing a final read-only verification of the reconciled data.

## Safety Approach

CRM changes were intentionally conservative.

Before updating an existing account, the script verified identifying information such as the account name and physical location.

Before creating an account, the CRM was searched using multiple identifying fields to reduce the risk of creating duplicate records.

Ambiguous records were not automatically modified.

API authentication is handled through the `BELLHAVEN_API_TOKEN` environment variable. No API credentials are stored in the source code.

## Final Reconciliation

34 Bellhaven website communities were reviewed.

Final results:

- 32 verified records
- 1 verified record with a duplicate CRM entry
- 1 record requiring manual review

### Manual Review: Bellhaven of Kettering

The CRM contains three active accounts associated with the same physical address at 3313 Wilmington Pike, Kettering, OH 45429.

The available information was not sufficient to safely determine which existing account should represent the Bellhaven website community. No automatic CRM modification was made for this record.

### Duplicate: Bellhaven of Owosso

The correct CRM record matching the Bellhaven website community was identified at 1120 W Main St, Owosso, MI 48867.

A second same-name CRM record also exists for the location. The valid website-to-CRM match was verified, but the additional record was not automatically deleted or modified because duplicate cleanup requires additional business context.

## Output

The final reconciliation results are available in:

`bellhaven_final_reconciliation.csv`

The file documents the final status of all 34 website communities, including records requiring additional review.
