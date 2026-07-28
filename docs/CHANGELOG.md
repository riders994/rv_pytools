# Changelog
### V1

* 2026-07-28 : v1.3.0
    * Added: `anonymize` gives numeric ID columns (integer, bigint, float) numeric tokens and keeps their dtype, so the result still fits the typed column it came from. Tokens count up from `NUMERIC_TOKEN_BASE` (10^12) so one is never mistakable for a real ID. Text columns keep `label_0` tokens, as do labels already issuing them, so existing maps stay reversible.
    * Fixed: A nullable integer column was cast to float before tokenizing, which rounded two bigint IDs onto one value and gave them a single token between them. IDs are now read exactly and stored as numbers, not text.
    * Fixed: `anonymize` extends an existing map instead of replacing it, so a value keeps the token it was first given and tokens already stored elsewhere keep reversing. Labels not mentioned in the call are left alone.
    * Fixed: The map is written atomically, so an interrupted write leaves the previous map intact rather than a truncated one. A map that cannot be read or is the wrong shape is refused rather than overwritten. Newly created maps are owner-only.
* 2026-06-17 : v1.2.1 - Fixed `anonymize`/`deanonymize` to handle named and unnamed index levels, including MultiIndex
* 2026-06-17 : v1.2.0 - Added `anonymize`/`deanonymize` functions for reversible, label-grouped column anonymization
* 2026-06-01 : v1.1.1 - Fixed log file maintenance to stop duplication
* 2026-06-01 : v1.1.0
    * Added: Ability to list files
    * Improved: Ability to run files on command and with specificity, rerun old files with status options
    * Bug Fixes: Broken pipe issues on failed queries
* 2026-05-28 : v1.0.1 - Proper updates and bug fixes for packaging.
* 2026-05-28 : v1.0.0 - SQLTools for use with DBs created alongside the orginal function from SO
