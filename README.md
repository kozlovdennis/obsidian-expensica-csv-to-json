# obsidian-expensica-csv-to-json

Convert CIBC CSV exports into the `transactions.json` format used by the Obsidian Expensica plugin.

## What the tool does

- Uses the CSV date as the single source of truth for the transaction date.
- Uses the conversion time for the `HHMMSS` portion of the generated ID.
- Writes transactions from oldest to newest by sorting on the CSV date.
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

- `YYYYMMDD-HHMMSS` comes from the conversion time
- `xxxxxxxx` is 8 hexadecimal characters from `secrets.token_hex(4)`

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
