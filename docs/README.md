# RV_PyTools
Some general use tools that are largely homebrewed with some Claude help.

## SQLTools
A suite of tools that let you work with databases. You can setup connections, create databases, run ddls, or have stored queries that take parameters.

## Functions

### Anonymize / Deanonymize
Reversibly anonymize columns of a DataFrame and persist a reversal map to disk.

```python
from rv_pytools import anonymize, deanonymize

columns = {"contact_email": "email", "billing_email": "email", "first_name": "name"}

anon = anonymize(df, columns, "map.json")          # tokenizes, saves reversal map
original = deanonymize(anon, columns, "map.json")  # restores from the map
```

`columns` maps each column name to a label. Values are grouped by label, so the
same value appearing in differently named columns (e.g. an email used in two
columns) is stored once and gets the same token. Neither function mutates the
input DataFrame, and `NaN`/`None` cells are left untouched. The `file_location`
argument defaults to `anonymization_map.json`.
