# Real labels from TTB's public COLA registry

These 16 approved labels (6 spirits, 6 wines, 4 beers; 6 imported) are public records from
[TTB's Public COLA Registry](https://ttbonline.gov/colasonline/publicSearchColasBasic.do).
Each folder holds:

- the label images exactly as the registry serves them (`1-front.png`, `2-back.jpg`, ...);
- `registry.json`: the registry's own fields, saved by `python -m scripts.fetch_cola <TTB ID>`;
- `truth.json`: the ground truth used by the tests and the evaluation.

## How the ground truth was made

The registry stores the brand, product type, source (domestic or imported) and origin, but not
the alcohol content, net contents, class/type wording or bottler statement. Those come from the
approved label itself.

- **Application values.** Brand, beverage type, imported and country come from `registry.json`.
  Class/type, alcohol content, net contents and the name-and-address statement are taken from
  the label, written the way an agent would type them.
- **Printed values.** These are transcribed by hand, as printed, with line breaks joined by
  spaces. For imports, the bottler field is the US importer's statement, which is the mandatory
  one. The warning is transcribed exactly, including stray punctuation and hyphenation at line
  breaks.
- **Bold.** A header that is visibly heavier than the body counts as bold. If the image can't
  settle it, both flags are left unknown.

## What the real labels showed

With perfect readings, the first version of the checking engine got 8 of 16 right. Each miss
led to a fix, listed with the label that prompted it:

| Label | What it does | Fix |
|---|---|---|
| Belle Isle | `53.5 ALC/VOL` with no % sign; "(1)" drawn like "(I)" | ABV without %; numbering I/l read as 1 |
| Old Boy, Royal Stag | `PROOF 108`, `85.6° US PROOF` | proof after the word, or with ° and "US" |
| ADK Fox, Tox | `1 PINT`, `1 Pint/16 fl oz` | pints and quarts |
| Worth Cellars | `12%ALC. VOL.750ML` | a number right after a word and a period |
| Ohanyan, Savannah, Aniche | `GOVERNMENTWARNING:`, `CONSUMPT ION` | warning spacing ignored entirely |
| Terrepasseri | `BE- CAUSE`, `CON- SUMPTION` | line-break hyphens ignored |
| Terrepasseri | `TERRE PASSERI` vs `TERREPASSERI` | names differing only in spacing pass |
| Switchback, Tox, Aniche | `Brewed in Burlington, Vermont by ...` | bottler words compared in any order |
| Ohanyan | country only as `Republic of Armenia` | long-form country names |

Four approved labels deviate from the 27 CFR 16.21 text, so their right result is not "Matches":

- **FLOS** (TTB ID 26245001000184): the warning omits "because" and "a". The right result is
  **Does not match**.
- **NUMA**, **Ohanyan** and **Forever Alone**: punctuation only (stray periods, a missing
  comma, a stray quotation mark). The right result is **Needs review**.
- **Switchback** isn't a deviation, but its warning is set in one heavy condensed typeface, so
  whether the header is bold can't be settled from the image. The right result is **Needs
  review**.

The label-reading prompt still has to handle one more case. At **Aniche Cellars**, the big
name "Beatrix" is the fanciful name, and the brand appears only in the bottler statement.
