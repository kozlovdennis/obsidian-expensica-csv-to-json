# Obsidian Expensica CSV to JSON

Convert CIBC CSV exports into the `transactions.json` format used by the Obsidian
[Expensica](https://github.com/dhruvir-zala/obsidian-expensica) plugin. Combine
account exports into internal transfers, review unresolved entries, then clean
merchant descriptions and assign categories.

| File | Purpose |
| --- | --- |
| [convert.py](convert.py) | Convert CSV to JSON, preserving bank descriptions and references. |
| [combinejson.py](combinejson.py) | Merge accounts, match transfers, and write an ID-based text log. |
| [cleanup.py](cleanup.py) | Clean descriptions and recalculate categories after confirmation. |
| [rules.py](rules.py) | Shared amount, description, and category rules. |

## Installation

Use **Python 3.10 or later**. All scripts use the standard library; no packages need
to be installed. Clone or download this repository and run commands from its root:

```sh
git clone https://github.com/kozlovdennis/obsidian-expensica-csv-to-json.git
cd obsidian-expensica-csv-to-json
python --version
```

The examples use `python`; substitute your Python 3 command if needed. `Path/` is a
placeholder for your data directory. Quote paths or account names containing spaces.

## Usage

**Convert -> combine -> review -> clean -> import into Expensica.** Run cleanup
last so matching can use the original bank descriptions and reference numbers.

Convert account files in order, then combine them using your Expensica account names:

```sh
python convert.py --pretty Path/debit.csv Path/debit.json Path/credit.csv Path/credit.json Path/saving.csv Path/saving.json
python combinejson.py -a debit Path/debit.json -a credit Path/credit.json -a saving Path/saving.json
```

The merger prints the combined JSON and `.txt` log paths, matching-method counts,
and unresolved transfers. Review these before cleanup. In the next command, replace
`Path/transactions-combined-YYYYMMDD-HHMMSS.json` with the **actual printed JSON path**
(the default directory is `output/`):

```sh
python cleanup.py Path/transactions-combined-YYYYMMDD-HHMMSS.json
```

Answer `y` to update that file in place or `n` to cancel. Review the result before
importing or copying it into your vault's `transactions.json`.

## CLI reference

Uppercase names are operands to replace. Brackets indicate optional arguments;
`...` indicates repetition. All commands support `-h`, `--help` to display help
and exit.

### convert.py

```text
python convert.py [--pretty] [--dry-run] INPUT_CSV [OUTPUT_JSON]
python convert.py [--pretty] [--dry-run] INPUT_CSV OUTPUT_JSON [INPUT_CSV OUTPUT_JSON ...]
```

| Operand or option | Description and default |
| --- | --- |
| `INPUT_CSV` | Required CIBC CSV path. See [CSV format](#csv-format). |
| `OUTPUT_JSON` | Output path. Optional for a single CSV; defaults to a timestamped file in the repository's `output/` directory. Required for each input in a batch. |
| `--pretty` | Use two-space JSON indentation. Default: unindented JSON. |
| `--dry-run` | Print JSON instead of writing files. Default: write files. Does not prompt for overwrites. |

Batch pairs run from left to right; each output is written before the next input
is read. Incomplete pairs are rejected before conversion. A processing error stops
the batch; previously written files remain. Both flags apply to every pair. A batch
dry run prints a separate JSON object for each input, rather than one JSON array
or document.

For an existing explicit output path, the prompt accepts `o`/`overwrite` to replace
it or `n`/`new` to use the next available suffix, such as `Path/debit_1.json`.
Other answers prompt again.

### combinejson.py

```text
python combinejson.py --account NAME FILE --account NAME FILE [--account NAME FILE ...]
```

| Option | Description and expected values |
| --- | --- |
| `-a NAME FILE`, `--acc NAME FILE`, `--account NAME FILE` | Repeat for each account. Requires at least two pairs and unique account names. `NAME` is the account label; `FILE` is its JSON path. Aliases can be mixed. |

Each input must be an object containing a `transactions` list. Matching pairs
become one `internal` entry; other entries retain their account labels. See
[Transfer matching](#transfer-matching) for compatibility and ambiguity rules.
Combined JSON always uses two-space indentation.

### cleanup.py

```text
python cleanup.py FILE
```

`FILE` is a required JSON path containing a `transactions` list. Cleanup updates
expense/income descriptions and categories using `rules.py`, then asks before
writing:

```text
Clean N transactions in Path/transactions.json and overwrite this file? [y/n]:
```

`y` confirms; `n` cancels without modifying the file. Answers are case-insensitive;
other answers prompt again, and end-of-input cancels. The saved JSON uses two-space
indentation. IDs, dates, amounts, account fields, other metadata, transaction order,
and internal entries are preserved. Existing expense/income categories are recalculated.

### Output files

Default paths are relative to the **repository directory**, not the working directory.
Parent directories are created when conversion or combination writes a file.

| Operation | Output |
| --- | --- |
| Conversion without an output path | `output/transactions-YYYYMMDD-HHMMSS.json`; adds a numeric suffix if needed. |
| Combination | `output/transactions-combined-YYYYMMDD-HHMMSS.json` |
| Combination log | Same basename as the combined JSON, with a `.txt` extension. |
| Cleanup | The supplied file, overwritten only after `y`. |

Filename timestamps use the local conversion/run time. Combination overwrites
existing paths with the same timestamp without prompting. The repository's
`input/`, `output/`, and files named `transactions.json` are ignored by Git.

## Examples

Convert one account to the default output directory, or choose an explicit path:

```sh
python convert.py Path/debit.csv --pretty
python convert.py Path/debit.csv Path/debit.json
```

Preview conversion without writing files:

```sh
python convert.py Path/debit.csv --dry-run --pretty
```

Merge two accounts, using either alias, then clean the printed output path:

```sh
python combinejson.py --acc debit Path/debit.json --account credit Path/credit.json
python cleanup.py Path/transactions-combined-YYYYMMDD-HHMMSS.json
```

## Technical details

### CSV format

Use UTF-8 CSV, with or without a byte-order mark, **without a header row**:

| Column | Value |
| --- | --- |
| 1 | Transaction date in `YYYY-MM-DD` format. |
| 2 | Original bank description. |
| 3 | Debit amount: creates an `expense`. |
| 4 | Credit amount: creates an `income`. |
| 5 | Optional; ignored. |

Exactly one amount column must be populated. Dollar signs and thousands separators
are accepted; quote CSV cells containing commas. Blank rows are skipped. Rows with
other column counts or invalid/missing amounts stop conversion and report the row
number. Conversion keeps the CSV date and sorts by it from oldest to newest.

### JSON format and IDs

Transaction files use this container:

```json
{"transactions": []}
```

| Entry | Fields and behavior |
| --- | --- |
| Converted transaction | `id`, `date`, `time`, `type`, `amount`, `description`, `category`. The original description is preserved; categories start as `other_expense` or `other_income`. |
| Unmatched expense/income after merging | Adds `account` using the supplied account name. |
| Matched internal transfer | Uses `type` and `category` of `internal`, plus `fromAccount` and `toAccount`. Retains the outgoing entry's ID, date, time, and amount; description becomes `TRANSFER TO {destination account}` in uppercase. Missing outgoing time falls back to the merger's run time. |

IDs have the form `YYYYMMDD-HHMMSS-xxxxxxxx`: CSV transaction date, local conversion
time, and eight random hexadecimal characters. The `time` field is also conversion
time because the export supplies no transaction time. Combined entries are sorted
by date, time, then ID. Existing internal entries retain their fields.

### Transfer matching

Every candidate pair must have different accounts, equal amounts, opposite
expense/income flows, compatible descriptions and account types, and dates at most
**five calendar days apart**, inclusive. Currency values must also agree; a missing
field is treated as null. Conversion does not add a currency field.

Description helpers are case-insensitive and can appear inside full bank text:

| Outgoing expense | Incoming income | Route |
| --- | --- | --- |
| `To account ...` | `From account ...` | Between bank accounts, including debit and savings. |
| `To card ...` | `Payment thank you` or its French equivalent | Bank account to credit card. |
| `Cash advance ...` | Generic bank transfer | Credit card to bank account. |

French variants include `PAIEMENT MERCI`, `PAINMENT MERCI`, and `PAIEMEN T MERCI`.
`BANK TRANSFER` and `INTERNET TRANSFER` are generic candidates. Specific helpers
take priority; `To account` does not become a card payment merely because its prefix
says `INTERNET TRANSFER`. An e-transfer or `Electronic Funds Transfer` prefix alone
is insufficient. Account labels do not determine types: explicit descriptions
supply bank/credit roles. Conflicting role evidence rejects affected pairs.

| Method | When a pair can merge |
| --- | --- |
| `bank_reference` | Identical references take priority over weaker edges; the pair must then be forced by the graph. Recognizes numbers of at least six digits after `INTERNET TRANSFER`, `BANK TRANSFER`, `REFERENCE`, or `REF`, with optional `#`, `NO.`, or `NUMBER`. Leading zeros are ignored. Card/account numbers are not references; conflicting references reject a pair. All other compatibility checks still apply. |
| `forced_graph` | The pair appears in every maximum matching of compatible transfers: removing its edge reduces the maximum number of pairs. Closest dates or input order do not decide ambiguous matches. |
| `equivalent_repeats` | A remaining connected group has equal outgoing/incoming counts and a complete pairing. Each side has identical account, date, time, flow, amount, currency, and normalized description, except IDs and reference values. Stable ordering resolves financially equivalent repeats. |

Ambiguous entries and entries missing a compatible counterpart remain unchanged.
The report lists their descriptions, dates, IDs, accounts, amounts, and reasons;
ordinary transactions and existing internal entries are excluded. References and
inferred account types support matching but do not verify ownership with the bank.

### Run log

Each combination writes a `.txt` log containing the console report, brief matching
reasons, and ID-based pair references. It also lists candidate IDs for unresolved
ambiguities. Full matched transaction records are not duplicated in the log.

```text
Transaction details: Path/transactions-combined-YYYYMMDD-HHMMSS.json
- id=20261001-120000-a1b2c3d4 <- incoming_id=20261002-120000-e5f6a7b8 | forced_graph
```

Look up `id` in the combined JSON. It is the original outgoing ID; `incoming_id`
refers to the source account JSON because that entry was collapsed. Keep the source
files for that lookup. No JSON audit file is created by new runs.

### Description cleanup and category rules

Cleanup removes common CIBC prefixes and reference tokens, normalizes whitespace,
and uppercases the resulting merchant/payee description. For example:

```text
Point of Sale - Interac RETAIL PURCHASE 306001001089 CADENCE COFFEE
-> CADENCE COFFEE
```

If extraction leaves no description, internet transfers receive an incoming/outgoing
bank-transfer label, with the last six reference digits when available. Other empty
results become `UNKNOWN TRANSACTION`. Cleanup overwrites descriptions; keep original
CSVs to regenerate raw JSON before another merge.

Edit `_EXPENSE_CATEGORY_RULES` and `_INCOME_CATEGORY_RULES` in [rules.py](rules.py).
Rules use `(category_id, keywords)` tuples and run from top to bottom; the first
match wins. Category matching uses the extracted description. For example:

```python
# Expense rules; re is already imported in rules.py.
("food", ("COFFEE", "TIM HORTONS")),
("rent", (re.compile(r"\bADA\b", re.IGNORECASE),)),
# Income rule.
("salary", ("PAYROLL",)),
```

String keywords are case-insensitive substring matches. A regex such as `\bADA\b`
matches `Ada` without matching `PRADA`. Keep the trailing comma in a one-item
keyword tuple. Unmatched categories fall back to `other_expense` or `other_income`.
Category IDs are written as configured, without validation against your vault.

<details>
<summary>Category ID reference</summary>

| Type | ID | Display name |
| --- | --- | --- |
| Expense | `food` | Food & Dining |
| Expense | `groceries` | Groceries |
| Expense | `transportation` | Transportation |
| Expense | `rent` | Rent/Mortgage |
| Expense | `utilities` | Utilities |
| Expense | `internet` | Internet & Phone |
| Expense | `entertainment` | Entertainment |
| Expense | `shopping` | Shopping |
| Expense | `health` | Healthcare |
| Expense | `education` | Education |
| Expense | `travel` | Travel |
| Expense | `fitness` | Fitness |
| Expense | `pets` | Pets |
| Expense | `gifts` | Gifts & Donations |
| Expense | `personal` | Personal Care |
| Expense | `childcare` | Childcare |
| Expense | `subscriptions` | Subscriptions |
| Expense | `insurance` | Insurance |
| Expense | `taxes` | Taxes |
| Expense | `other_expense` | Other Expenses |
| Income | `salary` | Salary |
| Income | `freelance` | Freelance |
| Income | `business` | Business |
| Income | `investments` | Investments |
| Income | `dividends` | Dividends |
| Income | `rental` | Rental Income |
| Income | `gifts_received` | Gifts Received |
| Income | `tax_returns` | Tax Returns |
| Income | `other_income` | Other Income |

</details>

### Repeated imports and tests

Conversion and combination do not append to an existing transaction file or remove
duplicate imports. Review each result before copying or importing it into Expensica.

Run the test suite from the repository root:

```sh
python -m unittest discover -s tests -v
```

The local-input regression runs when `input/debit.json`, `input/saving.json`, and
`input/credit.json` are available; otherwise that test is skipped.

Licensed under [MIT](LICENSE).
