import json

import pandas as pd
import pytest

from rv_pytools.functions import anonymize, deanonymize


@pytest.fixture
def df():
    return pd.DataFrame(
        {
            "first_name": ["Alice", "Bob", "Alice"],
            "contact_email": ["alice@x.com", "bob@x.com", "alice@x.com"],
            "billing_email": ["alice@x.com", "carol@x.com", "dave@x.com"],
        }
    )


def test_roundtrip(df, tmp_path):
    loc = tmp_path / "map.json"
    columns = {
        "first_name": "name",
        "contact_email": "email",
        "billing_email": "email",
    }
    anon = anonymize(df, columns, loc)

    # Original values no longer present in the anonymized frame.
    assert "Alice" not in anon["first_name"].tolist()
    assert "alice@x.com" not in anon["contact_email"].tolist()

    restored = deanonymize(anon, columns, loc)
    pd.testing.assert_frame_equal(restored, df)


def test_emails_grouped_across_columns(df, tmp_path):
    loc = tmp_path / "map.json"
    columns = {"contact_email": "email", "billing_email": "email"}
    anon = anonymize(df, columns, loc)

    # Same email in two differently named columns gets the same token.
    assert anon.loc[0, "contact_email"] == anon.loc[0, "billing_email"]

    mapping = json.loads(loc.read_text())
    # alice@x.com stored exactly once despite appearing in three cells.
    originals = list(mapping["email"].values())
    assert originals.count("alice@x.com") == 1


def test_consistent_tokens_within_label(df, tmp_path):
    loc = tmp_path / "map.json"
    columns = {"first_name": "name"}
    anon = anonymize(df, columns, loc)
    # Repeated name maps to the same token.
    assert anon.loc[0, "first_name"] == anon.loc[2, "first_name"]


def test_does_not_mutate_original(df, tmp_path):
    original = df.copy()
    anonymize(df, {"first_name": "name"}, tmp_path / "map.json")
    pd.testing.assert_frame_equal(df, original)


def test_missing_values_preserved(tmp_path):
    df = pd.DataFrame({"email": ["a@x.com", None]})
    loc = tmp_path / "map.json"
    anon = anonymize(df, {"email": "email"}, loc)
    assert pd.isna(anon.loc[1, "email"])
    restored = deanonymize(anon, {"email": "email"}, loc)
    pd.testing.assert_frame_equal(restored, df)


def test_unknown_column_raises(df, tmp_path):
    with pytest.raises(KeyError):
        anonymize(df, {"nope": "x"}, tmp_path / "map.json")


def test_roundtrip_named_index(df, tmp_path):
    df = df.set_index("first_name")
    loc = tmp_path / "map.json"
    columns = {"first_name": "name", "contact_email": "email"}
    anon = anonymize(df, columns, loc)

    assert "Alice" not in anon.index.tolist()
    restored = deanonymize(anon, columns, loc)
    pd.testing.assert_frame_equal(restored, df)


def test_roundtrip_unnamed_index(df, tmp_path):
    df = df.set_index("first_name")
    df.index.name = None  # unnamed single index
    loc = tmp_path / "map.json"
    columns = {None: "name", "contact_email": "email"}
    anon = anonymize(df, columns, loc)

    assert "Alice" not in anon.index.tolist()
    assert anon.index.name is None  # unnamed-ness preserved
    restored = deanonymize(anon, columns, loc)
    pd.testing.assert_frame_equal(restored, df)


def test_roundtrip_multiindex(df, tmp_path):
    df = df.set_index(["first_name", "contact_email"])
    loc = tmp_path / "map.json"
    columns = {"first_name": "name", "contact_email": "email", "billing_email": "email"}
    anon = anonymize(df, columns, loc)

    assert "Alice" not in anon.index.get_level_values("first_name").tolist()
    restored = deanonymize(anon, columns, loc)
    pd.testing.assert_frame_equal(restored, df)
