# obsidian-expensica-csv-to-json

Convert CIBC CSV exports into the `transactions.json` format used by the Obsidian [Expensica](https://github.com/dhruvir-zala/obsidian-expensica) plugin.

## What the tool does

- Uses the CSV date as the single source of truth for the transaction date.
- Uses the CSV date and conversion time for the generated ID.
- Writes transactions from oldest to newest (as per [Expensica](https://github.com/dhruvir-zala/obsidian-expensica) logic) by sorting on the CSV date (which is sorted from newest to oldest).
- Creates an ignored local `output/` folder when no output path is provided.
- Prompts before writing if an explicitly provided target JSON file already exists.
- Detects transaction type from the amount columns:
  - column 3 -> `expense`
  - column 4 -> `income`
- Preserves the original bank description during conversion and merging.
- Cleans descriptions and assigns keyword-based categories with a separate final command.

## Files

- `convert.py`: convert CSV to JSON with original descriptions and default categories
- `combinejson.py`: merge two or more account JSON files and collapse matched transfers
- `cleanup.py`: clean descriptions and assign categories in place, after confirmation
- `rules.py`: description cleanup, type detection, amount parsing, and category rules

## Workflow

Convert each account, combine the results, review unresolved transfers, then clean
the combined file:

```powershell
python convert.py debit.csv output/debit.json saving.csv output/saving.json credit.csv output/credit.json --pretty
python combinejson.py -a debit output/debit.json -a saving output/saving.json -a credit output/credit.json
```

Use the combined output path printed by `combinejson.py` in the cleanup command:

```powershell
python cleanup.py "output/transactions-combined-YYYYMMDD-HHMMSS.json"
```

Run cleanup last so transfer matching has the original bank descriptions.

## Convert usage

```powershell
python convert.py "C:\Path\cibc_chequing.csv" "C:\Path\Obsidian\VaultName\expensica-data\transactions.json" --pretty
```

Or omit the output path to write to the tool's local `output/` folder:

```powershell
python convert.py "C:\Path\cibc_chequing.csv" --pretty
```

For multiple files, provide an input/output pair for each account:

```powershell
python convert.py debit.csv debit.json credit.csv credit.json saving.csv saving.json --pretty
```

Pairs are processed one by one, from left to right. Each file is written before
the next is read, with an overwrite prompt for each existing output. An error
stops processing; files already written remain. Incomplete pairs are rejected
before any conversion. Omitting the output path is supported only for a single CSV.

`--pretty` and `--dry-run` apply to every pair. A batch dry run prints one JSON
object per input, in order, without writing files or prompting for overwrites.

## Combine usage

```powershell
python combinejson.py --account "debit" "C:\Path\debit.json" --account "savings" "C:\Path\savings.json" --account "credit" "C:\Path\credit.json"
```

Repeat `--account NAME FILE` for each account (at least two, with unique names).
Aliases: `--acc` and `-a`; these can be mixed in the same command.
This replaces the old positional two-account command. Use your Expensica account names.

Matching transfer entries across different accounts collapse into one `internal`
transaction, with `fromAccount` set to the expense account and `toAccount` to the
income account. This supports debit ↔ savings and payments or cash advances between
bank and credit accounts.

Both entries must belong to different accounts, have equal amounts, opposite
income/expense types, compatible transfer descriptions, and dates no more than
**five calendar days apart** (inclusive).

Description helpers are case-insensitive and work inside full bank descriptions:

| Outgoing expense | Incoming income | Transfer |
| --- | --- | --- |
| `To account ...` | `From account ...` | Between savings and debit, in either direction |
| `To card ...` | `Payment thank you / PAIEMENT MERCI` | Debit to credit |
| `Cash advance ...` | Generic bank transfer | Credit to bank account |

The French spellings `PAINMENT MERCI` and `PAIEMEN T MERCI` are also recognized.
Existing `BANK TRANSFER` and `INTERNET TRANSFER` descriptions remain supported as
generic transfer candidates. Specific helpers take priority: `To account` cannot
match a card payment just because its raw description also says `INTERNET TRANSFER`.
An `Electronic Funds Transfer` prefix or an e-transfer alone is not enough.
Account names are labels; they do not determine account types. Bank/credit roles
are inferred from explicit transfer helpers across each account. Conflicting
role evidence and incompatible transfer routes are rejected. If currency fields
are present, they must agree.

Matching uses these rules, in order:

1. **Bank references:** numbers following `INTERNET TRANSFER`, `BANK TRANSFER`,
   `REFERENCE`, or `REF` are compared without leading zeros. Card/account numbers
   are not transfer references. Two different references reject a pair. Identical
   references take priority over weaker candidates, while still requiring all
   amount, direction, account-type, currency, and five-day checks.
2. **Forced graph pairs:** compatible expenses and incomes form a bipartite graph.
   A pair is forced only if removing its edge reduces the maximum possible number
   of matches. This resolves overlapping date windows without guessing by nearest
   date. Being part of one possible maximum matching is not sufficient.
3. **Equivalent repeats:** a remaining connected group can merge deterministically
   only if it has equally many outgoing and incoming entries, a complete pairing,
   and identical financial details on each side. Account, date, time, amount,
   currency, and description must agree within each side; IDs and transfer reference
   numbers may differ. Original IDs determine stable pairings. Different account/card
   identifiers or dates do not qualify as identical repeats.

Genuinely ambiguous entries remain unchanged. Entries without a compatible
counterpart also remain. The command reports counts by matching method
(`bank_reference`, `forced_graph`, `equivalent_repeats`), then ends with
`Unmerged transfer transactions: N` and separate counts for ambiguity and missing
compatible counterparts. Each unresolved entry lists its description, date, ID,
account, amount, and reason. Ordinary purchases/income and already-internal
transactions are excluded from this report.

Review the unresolved entries before cleanup. The matcher checks references when
available; it does not verify account ownership with the bank.

This writes a new combined file to:

```text
output/transactions-combined-YYYYMMDD-HHMMSS.json
```

The combined file uses the same `transactions.json` format as the converter.

Each run also writes a separate audit beside the combined file:

```text
output/transactions-combined-YYYYMMDD-HHMMSS-audit.json
```

The audit's `matchedPairs` list records the original outgoing and incoming entries
(including both IDs and account labels), internal transaction ID, matching method,
reason, shared bank reference when available, and date difference. Its `unresolved`
list records the remaining entries, reasons, and candidate IDs. Keep this audit
when cleaning the combined file; it preserves the original descriptions.

## Cleanup usage

```powershell
python cleanup.py "C:\Path\transactions.json"
```

Cleanup changes the supplied file **in place** and asks first:

```text
Clean N transactions in ... and overwrite this file? [y/n]:
```

- `y`: clean descriptions, recalculate expense/income categories, and overwrite.
- `n`: cancel without changing the file.
- Other answers prompt again; missing input cancels.

Cleanup reuses the rules in `rules.py`. IDs, dates, amounts, account fields, other
metadata, and internal transactions are preserved. Keep the original CSVs if you
need to regenerate the raw descriptions for another merge.

## Convert options

- `--pretty`: write indented JSON
- `--dry-run`: print the converted JSON instead of writing a file

## Default output

When the output path is omitted, the tool writes to:

```text
output/transactions-YYYYMMDD-HHMMSS.json
```

The timestamp comes from the conversion time, and `output/` is ignored by Git.

## Existing output files

If an explicitly provided output path already exists, the tool asks whether to overwrite it or write to a new suffixed file.

```text
transactions.json already exists. Overwrite it or write to a new suffixed file? [o/n]:
```

Choose `o` to overwrite the existing file, or `n` to write to the next available name such as `transactions_1.json`.

## ID format

Generated IDs look like this:

```text
YYYYMMDD-HHMMSS-xxxxxxxx
```

Example:

```text
20260410-154233-8f3c1e7a
```

- `YYYYMMDD` comes from the CSV transaction date
- `HHMMSS` comes from the conversion time, because CIBC CSV does not provide timestamps
- `xxxxxxxx` is 8 hexadecimal characters from `secrets.token_hex(4)`

For example, a CSV row dated `2024-03-22` converted at `20:45:00` can produce an ID like:

```text
20240322-204500-55043779
```

## Description extraction

`cleanup.py` removes common CIBC prefixes and numeric reference tokens, then keeps
the remaining merchant or payee text in uppercase. `convert.py` preserves the
original description, including its case and reference numbers.

Example:

```text
Point of Sale - Interac RETAIL PURCHASE 306001001089 CADENCE COFFEE
```

becomes:

```text
CADENCE COFFEE
```

## Categories

Conversion uses these default categories. Cleanup applies the keyword rules,
falling back to:

- `other_expense`
- `other_income`

You can tune the mappings in `rules.py` as you discover more merchants in your exports.

## Default Expensica categories

Use the category ID on the left in generated JSON and in `rules.py`.

Expense categories:

- `food` -> Food & Dining
- `groceries` -> Groceries
- `transportation` -> Transportation
- `rent` -> Rent/Mortgage
- `utilities` -> Utilities
- `internet` -> Internet & Phone
- `entertainment` -> Entertainment
- `shopping` -> Shopping
- `health` -> Healthcare
- `education` -> Education
- `travel` -> Travel
- `fitness` -> Fitness
- `pets` -> Pets
- `gifts` -> Gifts & Donations
- `personal` -> Personal Care
- `childcare` -> Childcare
- `subscriptions` -> Subscriptions
- `insurance` -> Insurance
- `taxes` -> Taxes
- `other_expense` -> Other Expenses

Income categories:

- `salary` -> Salary
- `freelance` -> Freelance
- `business` -> Business
- `investments` -> Investments
- `dividends` -> Dividends
- `rental` -> Rental Income
- `gifts_received` -> Gifts Received
- `tax_returns` -> Tax Returns
- `other_income` -> Other Income

## Editing category rules

Category rules live in `rules.py` in `_EXPENSE_CATEGORY_RULES` and `_INCOME_CATEGORY_RULES`.
Each rule has this shape:

```python
(
    "category_id",
    (
        "KEYWORD",
        "ANOTHER KEYWORD",
    ),
),
```

For example:

```python
_EXPENSE_CATEGORY_RULES = [
    (
        "food",
        (
            "COFFEE",
            "TIM HORTONS",
            "MCDONALD",
        ),
    ),
    (
        "rent",
        (
            "LANDLORD",
            "RENT",
            re.compile(r"\bADA\b", re.IGNORECASE),
        ),
    ),
]

_INCOME_CATEGORY_RULES = [
    (
        "salary",
        (
            "PAYROLL",
            "WAGE",
            "SALARY",
        ),
    ),
    (
        "other_income",
        (
            "REFUND",
            "REVERSAL",
            "E-TRANSFER",
            "ETRANSFER",
            "TRANSFER",
        ),
    ),
]
```

Plain string keywords are case-insensitive. For example, `"AMZN Mktp"`, `"AMZN MKTP"`, and `"amzn mktp"` match the same way.

Plain strings are substring matches. This is useful for broad merchant patterns like `"COFFEE"` or `"AMZN"`, but it can be too broad for short names. For exact word matching, use a regex keyword:

```python
re.compile(r"\bADA\b", re.IGNORECASE),
```

The `re` module is already imported at the top of `rules.py`.

That matches `Ada`, but not `PRADA`.

For a single keyword, remember the trailing comma:

```python
(
    "gifts_received",
    (
        "GIFT",
    ),
),
```

Without the comma, Python treats `("GIFT")` as a string and the matcher checks each letter separately.

Rules are checked from top to bottom. Put more specific rules before broader rules if a transaction could match multiple categories.

After editing category rules, run cleanup on the final JSON:

```powershell
python cleanup.py "C:\Path\transactions.json"
```

## Appending or merging

The converter does not append into an existing `transactions.json` automatically. This is intentional because repeated bank imports can easily create duplicate transactions.

Recommended workflow:

1. Convert each account into a separate JSON file.
2. Combine the account files and review the unresolved transfer report.
3. Run cleanup on the combined file and review the result.
4. Import or copy the reviewed transactions into your Expensica data file manually.

If you explicitly pass your Obsidian `transactions.json` path, the tool asks before overwriting it:

```powershell
python convert.py "C:\Path\cibc_chequing.csv" "C:\Path\Obsidian\VaultName\expensica-data\transactions.json" --pretty
```

If append support is needed later, it should be implemented as a separate script with duplicate detection.
