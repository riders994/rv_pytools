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
columns) is stored once and gets the same token. A label may also name an index
level, including one level of a MultiIndex. Neither function mutates the input
DataFrame, and `NaN`/`None` cells are left untouched. The `file_location`
argument defaults to `anonymization_map.json`.

#### ID columns

A numeric column — an integer, bigint or float ID — gets numeric tokens and
keeps its dtype, so the anonymized frame is still writable to the typed column
it came from:

```python
df = pd.DataFrame({"user_id": pd.array([1234567890123456789, None], dtype="Int64")})

anonymize(df, {"user_id": "user"}, "map.json")
#    user_id
# 0    1000000000000     <- Int64, as it went in
# 1             <NA>
```

Numeric tokens count up from `NUMERIC_TOKEN_BASE` (10^12) rather than from
zero, so a token is never mistakable for a genuine low-numbered ID and never
collides with a real one in the same column. The base sits inside float64's
exact-integer range, so a float ID column holds tokens without rounding them.
Text columns keep `label_0` string tokens, and so does any label already
issuing them — a map written by an earlier version keeps working.

#### The reversal map

Tokens are stable across calls. An existing map is loaded and extended rather
than replaced, so a value keeps the token it was first given and only genuinely
new values mint new ones. This matters whenever tokens outlive the call — rows
written to a database, say — since renumbering would leave stored rows labelled
with someone else's identity. Labels the map holds but the call does not
mention are carried through untouched.

The map is the only way back to the real values, so it is written atomically: an
interrupted write leaves the previous map intact, and a map that cannot be read
or is the wrong shape is refused rather than overwritten. Maps created by
`anonymize` are readable only by their owner.
