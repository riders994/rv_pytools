import json
import stat

import pandas as pd
import pytest

from rv_pytools.functions import NUMERIC_TOKEN_BASE, anonymize, deanonymize

NUMERIC_DTYPES = ["int64", "Int64", "uint64", "float64", "Float64"]


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


def test_tokens_survive_a_later_call(df, tmp_path):
    """A value keeps its token when the frame grows underneath it.

    The tokens outlive the call -- they are what gets stored -- so renumbering
    on a second pass would relabel rows written by the first.
    """
    loc = tmp_path / "map.json"
    columns = {"first_name": "name"}
    first = anonymize(df, columns, loc)
    alice, bob = first.loc[0, "first_name"], first.loc[1, "first_name"]

    # A new name ahead of both in row order, which used to shift every token
    # after it: the old code numbered by position within the frame.
    grown = pd.concat(
        [pd.DataFrame({"first_name": ["Aaron"]}), df[["first_name"]]], ignore_index=True
    )
    second = anonymize(grown, columns, loc)

    assert second.loc[1, "first_name"] == alice
    assert second.loc[2, "first_name"] == bob
    assert second.loc[0, "first_name"] not in {alice, bob}
    # And the earlier frame still reverses correctly against the grown map.
    restored = deanonymize(first, columns, loc)
    pd.testing.assert_series_equal(restored["first_name"], df["first_name"])


def test_dropped_values_stay_reversible(df, tmp_path):
    """Rows absent from a later call keep their entries: something still stores them."""
    loc = tmp_path / "map.json"
    columns = {"first_name": "name"}
    first = anonymize(df, columns, loc)
    anonymize(df[df["first_name"] == "Bob"], columns, loc)

    restored = deanonymize(first, columns, loc)
    assert restored["first_name"].tolist() == ["Alice", "Bob", "Alice"]


def test_other_labels_not_dropped(df, tmp_path):
    """Anonymizing one label leaves another's entries in the shared map alone."""
    loc = tmp_path / "map.json"
    anonymize(df, {"contact_email": "email"}, loc)
    anonymize(df, {"first_name": "name"}, loc)

    mapping = json.loads(loc.read_text())
    assert set(mapping) == {"email", "name"}
    assert "alice@x.com" in mapping["email"].values()


def test_new_tokens_do_not_reuse_indices(df, tmp_path):
    loc = tmp_path / "map.json"
    columns = {"first_name": "name"}
    anonymize(df, columns, loc)
    anonymize(pd.DataFrame({"first_name": ["Zed"]}), columns, loc)

    mapping = json.loads(loc.read_text())["name"]
    # One token each for Alice, Bob and Zed, and no value reachable by two.
    assert len(mapping) == len(set(mapping.values())) == 3
    assert mapping["name_2"] == "Zed"                      # numbered past the map


def test_new_tokens_skip_indices_freed_by_deletion(tmp_path):
    """Numbering follows the highest token issued, not the number of entries.

    Entries get pruned from the map -- by a retention job, or by hand -- while
    the tokens they issued are still stored elsewhere. Counting the survivors
    would hand the freed index to a different value, and every stored copy of
    that token would silently start reversing to the wrong person.
    """
    loc = tmp_path / "map.json"
    loc.write_text(json.dumps({"name": {"name_0": "Alice", "name_2": "Carol"}}))

    anonymize(pd.DataFrame({"first_name": ["Zed"]}), {"first_name": "name"}, loc)

    mapping = json.loads(loc.read_text())["name"]
    assert mapping["name_3"] == "Zed"       # not name_2, which Carol still holds
    assert mapping["name_2"] == "Carol"


def test_non_json_native_values_keep_one_token(tmp_path):
    """A value json had to str() must not be issued a second token on reload.

    Timestamps are the case that bites: json cannot hold one, so it is written
    as text and comes back as text, matching neither the original object nor
    its hash.
    """
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"seen": pd.to_datetime(["2024-01-01", "2024-01-02"])})
    first = anonymize(frame, {"seen": "seen"}, loc)
    second = anonymize(frame, {"seen": "seen"}, loc)

    # Stored as text, so the second call has to match on the text form.
    assert json.loads(loc.read_text())["seen"] == {
        "seen_0": "2024-01-01 00:00:00",
        "seen_1": "2024-01-02 00:00:00",
    }
    pd.testing.assert_frame_equal(first, second)


def test_unreadable_map_raises(df, tmp_path):
    loc = tmp_path / "map.json"
    loc.write_text("{not json")
    with pytest.raises(ValueError, match="Could not read"):
        anonymize(df, {"first_name": "name"}, loc)
    # The unreadable file is left as-is rather than overwritten.
    assert loc.read_text() == "{not json"


def test_interrupted_write_leaves_previous_map_intact(df, tmp_path, monkeypatch):
    """A write that dies partway must not cost us the map it was replacing.

    Truncating in place would leave a half-written map, which is unreadable --
    and nothing else holds the token -> value pairs, so every token ever issued
    would be stranded.
    """
    loc = tmp_path / "map.json"
    columns = {"first_name": "name"}
    anonymize(df, columns, loc)
    intact = loc.read_text()

    def die_partway(obj, fp, **kwargs):
        fp.write('{"name": {"name_0": "Ali')      # a plausible partial flush
        raise RuntimeError("disk full")

    monkeypatch.setattr(json, "dump", die_partway)
    with pytest.raises(RuntimeError, match="disk full"):
        anonymize(pd.DataFrame({"first_name": ["Zed"]}), columns, loc)

    monkeypatch.undo()
    assert loc.read_text() == intact
    assert deanonymize(anonymize(df, columns, loc), columns, loc)[
        "first_name"
    ].tolist() == ["Alice", "Bob", "Alice"]


@pytest.mark.parametrize("fails", [False, True], ids=["success", "failure"])
def test_write_leaves_no_temp_files(df, tmp_path, monkeypatch, fails):
    loc = tmp_path / "map.json"
    if fails:
        monkeypatch.setattr(json, "dump", lambda *a, **k: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            anonymize(df, {"first_name": "name"}, loc)
    else:
        anonymize(df, {"first_name": "name"}, loc)

    assert [p.name for p in tmp_path.iterdir()] == ([] if fails else ["map.json"])


def test_new_map_is_not_world_readable(df, tmp_path):
    """The map reverses every token issued, so it is not for other accounts."""
    loc = tmp_path / "map.json"
    anonymize(df, {"first_name": "name"}, loc)
    assert stat.S_IMODE(loc.stat().st_mode) & 0o077 == 0


def test_existing_map_keeps_its_permissions(df, tmp_path):
    """Rewriting an existing map must not silently retighten it."""
    loc = tmp_path / "map.json"
    anonymize(df, {"first_name": "name"}, loc)
    loc.chmod(0o644)
    anonymize(pd.DataFrame({"first_name": ["Zed"]}), {"first_name": "name"}, loc)

    assert stat.S_IMODE(loc.stat().st_mode) == 0o644


@pytest.mark.parametrize(
    "contents, match",
    [
        ("[1, 2]", "not a JSON object"),
        ('{"name": ["Alice"]}', "not a JSON object of token"),
    ],
    ids=["map-is-a-list", "label-is-a-list"],
)
def test_malformed_map_raises(df, tmp_path, contents, match):
    """Readable JSON of the wrong shape is refused, not overwritten."""
    loc = tmp_path / "map.json"
    loc.write_text(contents)
    with pytest.raises(ValueError, match=match):
        anonymize(df, {"first_name": "name"}, loc)
    assert loc.read_text() == contents


def test_roundtrip_multiindex(df, tmp_path):
    df = df.set_index(["first_name", "contact_email"])
    loc = tmp_path / "map.json"
    columns = {"first_name": "name", "contact_email": "email", "billing_email": "email"}
    anon = anonymize(df, columns, loc)

    assert "Alice" not in anon.index.get_level_values("first_name").tolist()
    restored = deanonymize(anon, columns, loc)
    pd.testing.assert_frame_equal(restored, df)


# --- numeric IDs -----------------------------------------------------------


@pytest.mark.parametrize("dtype", NUMERIC_DTYPES)
def test_numeric_ids_get_numeric_tokens(dtype, tmp_path):
    """An ID column comes back numeric, so it still fits the column it came from."""
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": pd.array([101, 202, 101], dtype=dtype)})

    anon = anonymize(frame, {"id": "id"}, loc)

    assert anon["id"].dtype == frame["id"].dtype
    assert pd.api.types.is_numeric_dtype(anon["id"])
    assert anon.loc[0, "id"] == anon.loc[2, "id"]      # same ID, same token
    assert anon.loc[0, "id"] != anon.loc[1, "id"]
    assert 101 not in anon["id"].tolist()


@pytest.mark.parametrize("dtype", NUMERIC_DTYPES)
def test_numeric_ids_roundtrip_with_dtype(dtype, tmp_path):
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": pd.array([101, 202], dtype=dtype)})

    restored = deanonymize(anonymize(frame, {"id": "id"}, loc), {"id": "id"}, loc)

    pd.testing.assert_frame_equal(restored, frame)


def test_bigint_ids_do_not_collapse(tmp_path):
    """Two IDs a float cannot tell apart must not share a token.

    A nullable integer column used to be cast to float before tokenizing, which
    rounded these two onto the same value: one token between them, and both
    rows restoring to a single wrong ID.
    """
    loc = tmp_path / "map.json"
    first, second = 1234567890123456789, 1234567890123456790
    assert float(first) == float(second)              # the rounding that did it
    frame = pd.DataFrame({"id": pd.array([first, None, second], dtype="Int64")})

    anon = anonymize(frame, {"id": "id"}, loc)
    assert anon.loc[0, "id"] != anon.loc[2, "id"]
    assert len(json.loads(loc.read_text())["id"]) == 2

    restored = deanonymize(anon, {"id": "id"}, loc)
    assert restored.loc[0, "id"] == first
    assert restored.loc[2, "id"] == second


def test_bigint_ids_stored_exactly(tmp_path):
    """The map holds the ID as a number, not a rounded float or a string."""
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": pd.array([1234567890123456789], dtype="Int64")})

    anonymize(frame, {"id": "id"}, loc)

    stored = list(json.loads(loc.read_text())["id"].values())
    assert stored == [1234567890123456789]
    assert isinstance(stored[0], int)


def test_numeric_tokens_start_past_real_ids(tmp_path):
    """Tokens are offset, so one is never mistakable for a genuine low ID.

    The floor is asserted against a literal rather than against the constant:
    read off the constant, this passes for any offset at all, including none.
    """
    loc = tmp_path / "map.json"
    real_ids = list(range(1, 2001))
    frame = pd.DataFrame({"id": real_ids})

    tokens = anonymize(frame, {"id": "id"}, loc)["id"].tolist()

    assert min(tokens) >= 10 ** 12
    # No token can be read as one of the real IDs sharing the column.
    assert not set(tokens) & set(real_ids)
    assert tokens == sorted(tokens)                     # sequential, in first-seen order


def test_numeric_tokens_are_exact_in_float_columns(tmp_path):
    """The offset stays inside float64's exact-integer range.

    A float ID column holds the token as a float; past 2**53 that rounds, and
    two tokens would land on one value.
    """
    assert NUMERIC_TOKEN_BASE + 10 ** 6 < 2 ** 53
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": pd.array([1.5, 2.5, 3.5], dtype="float64")})

    tokens = anonymize(frame, {"id": "id"}, loc)["id"].tolist()

    assert len(set(tokens)) == 3
    assert all(float(t).is_integer() for t in tokens)
    assert deanonymize(
        anonymize(frame, {"id": "id"}, loc), {"id": "id"}, loc
    )["id"].tolist() == [1.5, 2.5, 3.5]


def test_numeric_tokens_survive_a_later_call(tmp_path):
    """Reloading turns the map's text keys back into numbers, not strings."""
    loc = tmp_path / "map.json"
    first = anonymize(pd.DataFrame({"id": [101, 202]}), {"id": "id"}, loc)
    second = anonymize(pd.DataFrame({"id": [303, 101]}), {"id": "id"}, loc)

    assert second.loc[1, "id"] == first.loc[0, "id"]   # 101 kept its token
    assert pd.api.types.is_numeric_dtype(second["id"])
    assert second.loc[0, "id"] == NUMERIC_TOKEN_BASE + 2
    assert deanonymize(first, {"id": "id"}, loc)["id"].tolist() == [101, 202]


def test_numeric_missing_values_preserved(tmp_path):
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": pd.array([101, None], dtype="Int64")})

    anon = anonymize(frame, {"id": "id"}, loc)

    assert pd.isna(anon.loc[1, "id"])
    assert len(json.loads(loc.read_text())["id"]) == 1
    pd.testing.assert_frame_equal(deanonymize(anon, {"id": "id"}, loc), frame)


def test_narrow_dtype_widened_rather_than_overflowed(tmp_path):
    """int32 cannot hold an offset token, so the column widens instead."""
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": pd.array([101, 202], dtype="int32")})

    anon = anonymize(frame, {"id": "id"}, loc)

    assert anon["id"].tolist() == [NUMERIC_TOKEN_BASE, NUMERIC_TOKEN_BASE + 1]
    assert deanonymize(anon, {"id": "id"}, loc)["id"].tolist() == [101, 202]


def test_numeric_index_level_gets_numeric_tokens(tmp_path):
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"v": ["a", "b"]}, index=pd.Index([101, 202], name="id"))

    anon = anonymize(frame, {"id": "id"}, loc)

    assert pd.api.types.is_numeric_dtype(anon.index)
    assert anon.index.tolist() == [NUMERIC_TOKEN_BASE, NUMERIC_TOKEN_BASE + 1]
    pd.testing.assert_frame_equal(deanonymize(anon, {"id": "id"}, loc), frame)


def test_numeric_label_shared_across_columns(tmp_path):
    """The same ID in two columns under one label gets one token."""
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"buyer_id": [101, 202], "seller_id": [202, 303]})
    columns = {"buyer_id": "party", "seller_id": "party"}

    anon = anonymize(frame, columns, loc)

    assert anon.loc[1, "buyer_id"] == anon.loc[0, "seller_id"]   # both are 202
    assert len(json.loads(loc.read_text())["party"]) == 3
    pd.testing.assert_frame_equal(deanonymize(anon, columns, loc), frame)


def test_strings_still_get_string_tokens(df, tmp_path):
    """Only numeric columns changed shape; text columns are untouched."""
    loc = tmp_path / "map.json"
    anon = anonymize(df, {"first_name": "name"}, loc)
    assert anon["first_name"].tolist() == ["name_0", "name_1", "name_0"]


def test_booleans_are_not_numeric_ids(tmp_path):
    """A bool column is a flag, not an ID; it keeps string tokens."""
    loc = tmp_path / "map.json"
    anon = anonymize(pd.DataFrame({"flag": [True, False]}), {"flag": "flag"}, loc)
    assert anon["flag"].tolist() == ["flag_0", "flag_1"]


def test_existing_string_map_keeps_issuing_string_tokens(tmp_path):
    """A map from before numeric tokens keeps its scheme.

    Switching an established label to numbers would leave every token already
    stored against it unreachable, which is the whole thing the map exists to
    prevent.
    """
    loc = tmp_path / "map.json"
    loc.write_text(json.dumps({"id": {"id_0": 101}}))

    anon = anonymize(pd.DataFrame({"id": [101, 202]}), {"id": "id"}, loc)

    assert anon["id"].tolist() == ["id_0", "id_1"]     # 101 kept its old token
    assert deanonymize(anon, {"id": "id"}, loc)["id"].tolist() == [101, 202]


@pytest.mark.parametrize(
    "columns",
    [{"id": "ref", "code": "ref"}, {"code": "ref", "id": "ref"}],
    ids=["numeric-column-first", "text-column-first"],
)
def test_label_shared_between_numeric_and_text_columns(columns, tmp_path):
    """One label over both kinds of column takes its token shape from the
    first column it meets, and reverses either way round.

    Sharing a label across an ID column and a text column is unusual, but it
    must not cost either column its values.
    """
    loc = tmp_path / "map.json"
    frame = pd.DataFrame({"id": [101, 202], "code": ["A", "B"]})

    anon = anonymize(frame, columns, loc)

    # Four distinct values, four tokens, none of them a passthrough.
    assert len(json.loads(loc.read_text())["ref"]) == 4
    assert anon["id"].tolist() != frame["id"].tolist()
    assert anon["code"].tolist() != frame["code"].tolist()
    pd.testing.assert_frame_equal(deanonymize(anon, columns, loc), frame)
