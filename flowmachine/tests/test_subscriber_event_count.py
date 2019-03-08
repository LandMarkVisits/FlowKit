# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from flowmachine.features.subscriber.event_count import *

import pytest


def test_event_count(get_dataframe):
    """
    Test some hand picked periods and tables
    """
    query = EventCount("2016-01-01", "2016-01-08")
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc["DzpZJ2EaVQo2X5vM"].value == 46

    query = EventCount(
        "2016-01-01",
        "2016-01-08",
        direction="both",
        tables=["events.calls", "events.sms", "events.mds", "events.topups"],
    )
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc["DzpZJ2EaVQo2X5vM"].value == 69

    query = EventCount(
        "2016-01-01", "2016-01-08", direction="both", tables=["events.mds"]
    )
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc["E0LZAa7AyNd34Djq"].value == 8

    query = EventCount(
        "2016-01-01", "2016-01-08", direction="both", tables="events.mds"
    )
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc["E0LZAa7AyNd34Djq"].value == 8

    query = EventCount("2016-01-01", "2016-01-08", direction="out")
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc["E0LZAa7AyNd34Djq"].value == 24

    query = EventCount("2016-01-01", "2016-01-08", direction="in")
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc["4dqenN2oQZExwEK2"].value == 12


@pytest.mark.parametrize("kwarg", ["direction"])
def test_event_count_errors(kwarg):
    """ Test ValueError is raised for non-compliant kwarg in EventCount. """

    with pytest.raises(ValueError):
        query = EventCount("2016-01-03", "2016-01-05", **{kwarg: "error"})


@pytest.mark.parametrize(
    "statistic,msisdn,want,level",
    [
        ("count", "Rzx9WE1QRqdEX2Gp", 16, {}),
        ("sum", "LBlWd64rqnMGv7kY", 22, {}),
        ("avg", "JZoaw2jzvK2QMKYX", 1.333_333, {}),
        ("avg", "JZoaw2jzvK2QMKYX", 1.647_059, {"level": "admin3"}),
        ("max", "DELmRj9Vvl346G50", 4, {}),
        ("min", "9vXy462Ej8V1kpWl", 1, {}),
        ("stddev", "EkpjZe5z37W70QKA", 0.594_089, {}),
        ("variance", "JNK7mk5G1Dy6M2Ya", 0.395_833, {}),
    ],
)
def test_per_location_event_count(get_dataframe, statistic, msisdn, want, level):
    """ Test hand-picked PerLocationEventCount. """
    query = PerLocationEventCount(
        "2016-01-01", "2016-01-06", statistic=statistic, **level
    )
    df = get_dataframe(query).set_index("subscriber")
    assert df.value[msisdn] == pytest.approx(want)


@pytest.mark.parametrize("kwarg", ["direction", "statistic"])
def test_per_location_event_count_errors(kwarg):
    """ Test ValueError is raised for non-compliant kwarg in PerLocationEventCount. """

    with pytest.raises(ValueError):
        query = PerLocationEventCount("2016-01-03", "2016-01-05", **{kwarg: "error"})


@pytest.mark.parametrize(
    "statistic,msisdn,want",
    [
        ("count", "Rzx9WE1QRqdEX2Gp", 2),
        ("sum", "LBlWd64rqnMGv7kY", 16),
        ("avg", "JZoaw2jzvK2QMKYX", 12.5),
        ("max", "DELmRj9Vvl346G50", 14),
        ("min", "9vXy462Ej8V1kpWl", 4),
        ("median", "KXVqP6JyVDGzQa3b", 8),
        ("stddev", "EkpjZe5z37W70QKA", 0),
        ("variance", "JNK7mk5G1Dy6M2Ya", 2),
    ],
)
def test_per_contact_event_count(get_dataframe, statistic, msisdn, want):
    """ Test hand-picked PerContactEventCount. """
    query = PerContactEventCount(
        "2016-01-02",
        "2016-01-06",
        ContactBalance("2016-01-02", "2016-01-06"),
        statistic,
    )
    df = get_dataframe(query).set_index("subscriber")
    assert df.value[msisdn] == pytest.approx(want)


@pytest.mark.parametrize("kwarg", ["statistic"])
def test_per_contact_event_count_errors(kwarg):
    """ Test ValueError is raised for non-compliant kwarg in PerContactEventCount. """

    with pytest.raises(ValueError):
        query = PerContactEventCount(
            "2016-01-03",
            "2016-01-05",
            ContactBalance("2016-01-02", "2016-01-06"),
            **{kwarg: "error"},
        )


def test_directed_count_consistent(get_dataframe):
    """
    Test that directed count is consistent.
    """
    out_query = EventCount("2016-01-01", "2016-01-08", direction="out")
    out_df = get_dataframe(out_query).set_index("subscriber")

    in_query = EventCount("2016-01-01", "2016-01-08", direction="in")
    in_df = get_dataframe(in_query).set_index("subscriber")

    joined = out_df.join(in_df, lsuffix="_out", rsuffix="_in", how="outer")
    joined.loc[~joined.index.isin(out_df.index), "value_out"] = 0
    joined.loc[~joined.index.isin(in_df.index), "value_in"] = 0

    joined["value"] = joined.sum(axis=1)

    both_query = EventCount("2016-01-01", "2016-01-08", direction="both")
    both_df = get_dataframe(both_query).set_index("subscriber")

    assert joined["value"].to_dict() == both_df["value"].to_dict()


def test_directed_count_undirected_tables_raises():
    """
    Test that requesting directed counts of undirected tables raises warning and errors.
    """
    with pytest.raises(ValueError):
        query = EventCount(
            "2016-01-01", "2016-01-08", direction="out", tables=["events.mds"]
        )
