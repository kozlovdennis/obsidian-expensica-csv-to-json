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
- Extracts a cleaner description from the bank's transaction text.
- Assigns categories with simple keyword-based rules.

## Files

- `convert.py`: command-line tool
- `rules.py`: description cleanup, type detection, amount parsing, and category rules

## Usage

```powershell
python convert.py "C:\Path\cibc_chequing.csv" "C:\Path\Obsidian\VaultName\expensica-data\transactions.json" --pretty
```

Or omit the output path to write to the tool's local `output/` folder:

```powershell
python convert.py "C:\Path\cibc_chequing.csv" --pretty
```

## Options

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

The tool removes common CIBC prefixes and numeric reference tokens, then keeps the remaining merchant or payee text.

Example:

```text
Point of Sale - Interac RETAIL PURCHASE 306001001089 CADENCE COFFEE
```

becomes:

```text
CADENCE COFFEE
```

## Categories

The tool uses simple keyword rules first, then falls back to:

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

After editing rules, regenerate the output:

```powershell
python convert.py "C:\Path\cibc_chequing.csv" --pretty
```

## Appending or merging

The converter does not append into an existing `transactions.json` automatically. This is intentional because repeated bank imports can easily create duplicate transactions.

Recommended workflow:

1. Generate a new file in the local `output/` folder by omitting the output path.
2. Review the generated JSON.
3. Import or copy the reviewed transactions into your Expensica data file manually.

If you explicitly pass your Obsidian `transactions.json` path, the tool asks before overwriting it:

```powershell
python convert.py "C:\Path\cibc_chequing.csv" "C:\Path\Obsidian\VaultName\expensica-data\transactions.json" --pretty
```

If append support is needed later, it should be implemented as a separate script with duplicate detection.
