# Add default/utility functions here

import itertools
import json
import os
import stat
import tempfile

import numpy as np
import pandas as pd

__all__ = ["ordinal", "anonymize", "deanonymize", "NUMERIC_TOKEN_BASE"]

DEFAULT_ANON_FILE = "anonymization_map.json"

# Numeric tokens start here rather than at 0, so a token is never mistakable
# for a real low-numbered ID and never collides with one in a column holding
# both. Comfortably inside float64's exact-integer range, so a float ID column
# can hold a token without rounding it.
NUMERIC_TOKEN_BASE = 10 ** 12


def ordinal(n):
    return "%d%s" % (n, "tsnrhtdd"[(n//10 % 10 != 1)*(n % 10 < 4)*n % 10::4])


def _dtype_of(df, col):
    """The dtype of a column or named index level, for deciding token shape."""
    if col in df.columns:
        return df[col].dtype
    if col in df.index.names:
        return df.index.get_level_values(df.index.names.index(col)).dtype
    raise KeyError(f"{col!r} not found in DataFrame columns or index")


def _apply_to_column_or_index(df, col, func, dtype_for=None):
    """Apply ``func`` element-wise to a column or named index level in place.

    ``col`` may name a regular column or a (possibly MultiIndex) index level.
    Columns take precedence if a name appears in both. Raises KeyError if the
    name is found in neither.

    Values are read off the underlying array rather than through ``Series.map``,
    which casts a nullable integer column to float before the callback ever
    sees it -- enough to round two distinct bigint IDs onto the same value and
    hand them one token between them.

    ``dtype_for(old_dtype, new_values)`` chooses the dtype to rebuild with, or
    returns None to let pandas infer as it did before.
    """
    def rebuild(values, old_dtype):
        dtype = dtype_for(old_dtype, values) if dtype_for else None
        return values if dtype is None else pd.array(values, dtype=dtype)

    if col in df.columns:
        old = df[col]
        new_values = rebuild([func(v) for v in old.array], old.dtype)
        df[col] = pd.Series(new_values, index=df.index, name=col)
        return

    if col in df.index.names:
        pos = df.index.names.index(col)
        level = df.index.get_level_values(pos)
        new_values = rebuild([func(v) for v in level.array], level.dtype)
        if df.index.nlevels == 1:
            df.index = pd.Index(new_values, name=df.index.names[0])
        else:
            arrays = [df.index.get_level_values(i) for i in range(df.index.nlevels)]
            arrays[pos] = new_values
            df.index = pd.MultiIndex.from_arrays(arrays, names=df.index.names)
        return

    raise KeyError(f"{col!r} not found in DataFrame columns or index")


def _load_mapping(file_location):
    """The reversal map already on disk, or an empty one if there is none.

    A map that exists but cannot be read is an error rather than a fresh start:
    overwriting it would strand every token ever issued from it, and whatever
    stores those tokens has no other way back to the real values.
    """
    if not os.path.exists(file_location):
        return {}
    try:
        with open(file_location) as f:
            mapping = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"Could not read the anonymization map at {file_location!r}: {exc}. "
            "Refusing to overwrite it, because the tokens already issued from it "
            "would no longer reverse."
        ) from exc
    if not isinstance(mapping, dict):
        raise ValueError(
            f"The anonymization map at {file_location!r} is not a JSON object."
        )
    for label, token_to_value in mapping.items():
        if not isinstance(token_to_value, dict):
            raise ValueError(
                f"The anonymization map at {file_location!r} holds a "
                f"{type(token_to_value).__name__} for label {label!r}, not a "
                "JSON object of token -> value."
            )
    return mapping


def _write_mapping(mapping, file_location):
    """Replace the map at ``file_location``, or leave the old one untouched.

    Written to a sibling temp file and moved into place. Writing in place would
    truncate first, so a crash or a full disk between the truncate and the
    flush would leave behind exactly the half-written map that
    :func:`_load_mapping` refuses to read -- and refuses for good reason, since
    nothing else holds the token -> value pairs. Guarding the read while the
    write itself can create the damage would only report the loss, not avoid it.
    """
    path = os.fspath(file_location)
    fd, temp_path = tempfile.mkstemp(
        dir=os.path.dirname(path) or ".",
        prefix=os.path.basename(path) + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(mapping, f, indent=2, default=str)
            f.flush()
            # The rename is atomic, but only orders against data the kernel
            # has: without this, a crash can leave the new name on an empty file.
            os.fsync(f.fileno())
        try:
            os.chmod(temp_path, stat.S_IMODE(os.stat(path).st_mode))
        except FileNotFoundError:
            # A map being written for the first time keeps mkstemp's
            # owner-only mode; it is the key to every token ever issued.
            pass
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _scalar(value):
    """A numpy scalar as the plain Python one it wraps, else ``value`` as-is.

    json cannot serialize numpy types, so without this they reach the file via
    ``default=str`` and come back as text -- which for an ID means the value
    restored is the string "123", not the number, and never compares equal to
    the row it came from. ``.item()`` on np.int64 is exact at any width, unlike
    a trip through float.
    """
    return value.item() if isinstance(value, np.generic) else value


def _is_numeric_dtype(dtype):
    return pd.api.types.is_numeric_dtype(dtype) and not pd.api.types.is_bool_dtype(dtype)


def _is_index(token):
    return str(token).isdigit()


def _token_kind(token_to_value, dtype):
    """Whether ``label`` issues numeric tokens or ``label_0`` strings.

    A label already in the map keeps whatever it has been issuing, so a map
    written by an older version keeps its string tokens and the values already
    stored against them stay reversible. Only a label with no history takes its
    shape from the column, and only a numeric column asks for numeric tokens.
    """
    if token_to_value:
        return "numeric" if all(_is_index(t) for t in token_to_value) else "string"
    return "numeric" if _is_numeric_dtype(dtype) else "string"


def _next_index(token_to_value, label, kind):
    """One past the highest token ``label`` has already issued.

    Read off the tokens themselves rather than counting them, so a map that has
    had entries removed cannot hand out an index that is still in use.
    """
    if kind == "numeric":
        issued = [int(t) for t in token_to_value if _is_index(t)]
        return max(issued, default=NUMERIC_TOKEN_BASE - 1) + 1

    prefix = f"{label}_"
    highest = -1
    for token in token_to_value:
        if isinstance(token, str) and token.startswith(prefix):
            suffix = token[len(prefix):]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return highest + 1


def _token_dtype(old_dtype, tokens):
    """The dtype to hand the tokenized column back in.

    The original is kept when it can hold the tokens, so an ID column stays
    writable to the typed column it came from. A narrow one that cannot is
    widened rather than overflowed.
    """
    try:
        pd.array(tokens, dtype=old_dtype)
    except (OverflowError, TypeError, ValueError):
        return "Int64" if any(pd.isna(t) for t in tokens) else "int64"
    return old_dtype


def _restored_dtype(old_dtype, values):
    """The dtype to hand a deanonymized column back in.

    A numeric token column already carries the dtype the IDs were tokenized
    out of -- :func:`_token_dtype` kept it -- so restoring into it returns the
    column in the shape it started, nullable flavour and all. Failing that,
    only missing values force the question: pandas infers a list of ints as
    int64 by itself, but one containing a gap falls back to object, which is
    not the nullable column the IDs were read out of.

    Anything the candidate cannot hold -- an int wider than 64 bits, say --
    keeps the inferred column rather than losing the value to a cast.
    """
    def holds(dtype):
        try:
            pd.array(values, dtype=dtype)
        except (OverflowError, TypeError, ValueError):
            return False
        return True

    if _is_numeric_dtype(old_dtype) and holds(old_dtype):
        return old_dtype

    present = [v for v in values if not pd.isna(v)]
    if len(present) == len(values) or not present:
        return None
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        candidate = "Int64"
    elif all(isinstance(v, float) for v in present):
        candidate = "Float64"
    else:
        return None
    return candidate if holds(candidate) else None


def anonymize(df, columns, file_location=DEFAULT_ANON_FILE):
    """Anonymize values in the given columns and persist the reversal map.

    Tokens are stable. Any map already at ``file_location`` is loaded and
    extended rather than replaced, so a value keeps the token it was first
    given and only genuinely new values mint new ones. This matters whenever
    the tokens outlive the call — rows written to a database, say: numbering
    them afresh each time would silently repoint every token issued earlier,
    leaving stored data labelled with someone else's identity.

    Labels the map holds but ``columns`` does not mention are carried through
    untouched, so anonymizing one column of a shared map cannot drop another's
    entries.

    A numeric column -- an integer, bigint or float ID -- is given numeric
    tokens and keeps its dtype, so the result is still writable to the typed
    column it came from. Those tokens count up from ``NUMERIC_TOKEN_BASE``
    rather than from zero, so one is never mistakable for a genuine low ID and
    never collides with a real one in the same column. Text columns keep
    ``label_0`` string tokens, as do labels already issuing them, so maps
    written before numeric tokens existed stay reversible.

    Args:
        df: DataFrame to anonymize. The original is not mutated.
        columns: dict mapping column name -> column label. Values sharing a
            label are grouped together, so the same value appearing under two
            differently named columns (e.g. an email) is stored once and gets
            the same token. A label spanning both a numeric and a text column
            takes its token shape from whichever column it meets first.
        file_location: where to write the token -> original-value map (JSON).

    Returns:
        A new DataFrame with the specified columns replaced by tokens.

    Raises:
        ValueError: if an existing map is present but unreadable.
    """
    df = df.copy()
    # mapping[label] = {token: original}; written to disk for reversal.
    mapping = _load_mapping(file_location)
    # reverse[label] = {original: token}; used to reuse tokens while building.
    reverse = {}
    counters = {}

    kinds = {}

    for col, label in columns.items():
        token_to_value = mapping.setdefault(label, {})
        if label not in reverse:
            kinds[label] = _token_kind(token_to_value, _dtype_of(df, col))
            if kinds[label] == "numeric":
                # json object keys are text, so numeric tokens come back as
                # "1000000000000". Restore them to ints here, or a value found
                # in an existing map would be handed a string token and land a
                # string in the numeric column it was meant to keep.
                token_to_value = {int(t): v for t, v in token_to_value.items()}
                mapping[label] = token_to_value
            # Seeded from what is already on file, so those tokens are reused.
            reverse[label] = {value: token for token, value in token_to_value.items()}
            counters[label] = itertools.count(
                _next_index(token_to_value, label, kinds[label])
            )
        kind = kinds[label]
        token_for_value = reverse[label]
        counter = counters[label]

        def _tokenize(value, token_for_value=token_for_value,
                      token_to_value=token_to_value, counter=counter,
                      label=label, kind=kind):
            if pd.isna(value):
                return value
            # Numpy scalars are unwrapped before they reach the map so wide
            # integers survive json intact; see _scalar.
            value = _scalar(value)
            if value in token_for_value:
                return token_for_value[value]
            # A value of a type json cannot hold at all still goes to file via
            # default=str and comes back as text. Match that form too, or every
            # such value would be issued a second token on the next call.
            text = str(value)
            if text in token_for_value:
                token_for_value[value] = token_for_value[text]
                return token_for_value[value]
            index = next(counter)
            token = index if kind == "numeric" else f"{label}_{index}"
            token_for_value[value] = token
            token_to_value[token] = value
            return token

        _apply_to_column_or_index(
            df, col, _tokenize,
            dtype_for=_token_dtype if kind == "numeric" else None,
        )

    _write_mapping(mapping, file_location)

    return df


def deanonymize(df, columns, file_location=DEFAULT_ANON_FILE):
    """Restore original values into the given columns from a saved map.

    Args:
        df: DataFrame containing anonymized tokens. The original is not mutated.
        columns: dict mapping column name -> column label, matching the dict
            used when anonymizing.
        file_location: path to the map written by :func:`anonymize`.

    Returns:
        A new DataFrame with tokens replaced by their original values.
    """
    df = df.copy()
    with open(file_location) as f:
        mapping = json.load(f)

    for col, label in columns.items():
        # json object keys are text, so a numeric token was written as
        # "1000000000000" but arrives here as the number. Accept both forms.
        lookup = {}
        for token, value in mapping.get(label, {}).items():
            lookup[token] = value
            if _is_index(token):
                lookup[int(token)] = value

        def _restore(token, lookup=lookup):
            if pd.isna(token):
                return token
            return lookup.get(_scalar(token), token)

        _apply_to_column_or_index(df, col, _restore, dtype_for=_restored_dtype)

    return df
