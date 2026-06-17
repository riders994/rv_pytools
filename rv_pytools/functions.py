# Add default/utility functions here

import json

import pandas as pd

__all__ = ["ordinal", "anonymize", "deanonymize"]

DEFAULT_ANON_FILE = "anonymization_map.json"


def ordinal(n):
    return "%d%s" % (n, "tsnrhtdd"[(n//10 % 10 != 1)*(n % 10 < 4)*n % 10::4])


def anonymize(df, columns, file_location=DEFAULT_ANON_FILE):
    """Anonymize values in the given columns and persist the reversal map.

    Args:
        df: DataFrame to anonymize. The original is not mutated.
        columns: dict mapping column name -> column label. Values sharing a
            label are grouped together, so the same value appearing under two
            differently named columns (e.g. an email) is stored once and gets
            the same token.
        file_location: where to write the token -> original-value map (JSON).

    Returns:
        A new DataFrame with the specified columns replaced by tokens.
    """
    df = df.copy()
    # mapping[label] = {token: original}; written to disk for reversal.
    mapping = {}
    # reverse[label] = {original: token}; used to reuse tokens while building.
    reverse = {}

    for col, label in columns.items():
        if col not in df.columns:
            raise KeyError(f"Column {col!r} not found in DataFrame")
        token_for_value = reverse.setdefault(label, {})
        token_to_value = mapping.setdefault(label, {})

        def _tokenize(value):
            if pd.isna(value):
                return value
            if value not in token_for_value:
                token = f"{label}_{len(token_for_value)}"
                token_for_value[value] = token
                token_to_value[token] = value
            return token_for_value[value]

        df[col] = df[col].map(_tokenize)

    with open(file_location, "w") as f:
        json.dump(mapping, f, indent=2, default=str)

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
        if col not in df.columns:
            raise KeyError(f"Column {col!r} not found in DataFrame")
        token_to_value = mapping.get(label, {})
        df[col] = df[col].map(lambda token: token_to_value.get(token, token))

    return df
