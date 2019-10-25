# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import pytest
import pytz
from datetime import datetime

from flowmachine.features import SubscriberSightings
from flowmachine.core import CustomQuery
from flowmachine.core.subscriber_subsetter import SubscriberSubsetterForFlowmachineQuery


def test_columns_and_identifier_are_set():
    """Test that all the columns and identifier are set on the object."""
    identifier = "imei"
    ss = SubscriberSightings(
        "2016-01-01", "2016-01-02", subscriber_identifier=identifier
    )

    assert identifier == ss.subscriber_identifier
    assert "subscriber" in ss.column_names
    assert "datetime" in ss.column_names
    assert "location_id" in ss.column_names


def test_subscriber_identifier_can_be_uppercase():
    """Test that subscriber_identifier can be provided in uppercase."""
    identifier = "IMEI"
    ss = SubscriberSightings(
        "2016-01-01", "2016-01-02", subscriber_identifier=identifier
    )

    assert identifier.lower() == ss.subscriber_identifier


def test_msisdn_set_as_identifier():
    """Test that msisdn is set as the default identifier."""
    ss = SubscriberSightings("2016-01-01", "2016-01-02")

    assert "msisdn" == ss.subscriber_identifier


@pytest.mark.parametrize("identifier", ("msisdn", "imei", "imsi"))
def test_colums_are_set_in_sql(identifier):
    """Test that the identifier is set an the colums."""
    ss = SubscriberSightings(
        "2016-01-01", "2016-01-02", subscriber_identifier=identifier
    )

    assert f"{identifier} AS subscriber_identifier" in ss.columns


def test_singleday_property():
    """Test that dates correctly resolve the singleday property"""
    ss = SubscriberSightings("2016-01-01", "2016-01-01")
    assert ss.singleday == True

    ss = SubscriberSightings("2016-01-01", "2016-01-02")
    assert ss.singleday == False


def test_start_stop_integer_conversion():
    """Test that setting a start/stop will get date integers."""

    ss = SubscriberSightings("2016-01-01", "2016-01-02")
    assert ss.start == 1
    assert ss.stop == 2


def test_start_stop_non_exist_will_result_in_min_max():
    """Test that setting non existing dates will result in min/max."""

    ss = SubscriberSightings("2012-01-01", "2012-01-02")
    assert ss.start == 1
    assert ss.stop == 5


def test_set_date_none():
    """Test that setting a start/stop to None will use min/max dates."""
    ss = SubscriberSightings(None, "2016-01-04")
    df = ss.head()

    min = df["datetime"].min().to_pydatetime()
    min_comparison = pytz.timezone("Etc/UTC").localize(datetime(2016, 1, 1, 0, 0, 0))

    assert min.timestamp() > min_comparison.timestamp()

    ss = SubscriberSightings("2016-01-01", None)
    df = ss.head()

    max = df["datetime"].max().to_pydatetime()
    max_comparison = pytz.timezone("Etc/UTC").localize(datetime(2016, 1, 10, 0, 0, 0))

    assert max.timestamp() < max_comparison.timestamp()


def test_dates_select_correct_data():
    """Test that dates select the correct data."""
    ss = SubscriberSightings("2016-01-01", "2016-01-02")
    df = ss.head(50)

    min = df["datetime"].min().to_pydatetime()
    max = df["datetime"].max().to_pydatetime()
    min_comparison = pytz.timezone("Etc/UTC").localize(datetime(2016, 1, 1, 0, 0, 0))
    max_comparison = pytz.timezone("Etc/UTC").localize(datetime(2016, 1, 10, 0, 0, 0))

    assert min.timestamp() > min_comparison.timestamp()
    assert max.timestamp() < max_comparison.timestamp()


def test_that_subscriber_subset_is_added(get_dataframe):
    """Test that subscriber_subset is added to the output SQL."""
    subsetter = SubscriberSubsetterForFlowmachineQuery(
        CustomQuery(
            "SELECT subscriber_id AS subscriber FROM interactions.calls c WHERE call_duration < 400",
            ["subscriber"],
        )
    )
    start = "2016-01-01"
    end = "2016-01-02"
    ss = SubscriberSightings(start, end, subscriber_subset=subsetter)
    query = ss.get_query()

    assert "FROM interactions.calls" in query
    assert "WHERE call_duration < 400" in query
    assert "tbl.subscriber = subset_query.subscriber" in query

    df = get_dataframe(ss)

    min_date = df["datetime"].min().to_pydatetime().strftime("%Y-%m-%d")
    max_date = df["datetime"].max().to_pydatetime().strftime("%Y-%m-%d")

    assert min_date == start
    assert min_date == max_date
