# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from flowmachine.features.subscriber.event_type_proportion import *

import pytest

@pytest.mark.parametrize("event_type, msisdn, want", [
    ("calls", "AgB6KR3Levd9Z1vJ", 0.351852),
    ("sms", "7ra3xZakjEqB1Al5", 0.362069),
    ("mds", "QrAlXqDbXDkNJe3E", 0.23636363),
    ("topups", "bKZLwjrMQG7z468y", 0.1830985),
])
def test_proportion_event_type(get_dataframe, event_type, msisdn, want):
    """
    Test some hand picked periods and tables
    """
    query = ProportionEventType("2016-01-01", "2016-01-08", event_type,
        tables=["events.calls", "events.sms", "events.mds", "events.topups", "events.forwards"])
    df = get_dataframe(query).set_index("subscriber")
    assert df.loc[msisdn].proportion == pytest.approx(want)

    query = ProportionEventType("2016-01-02", "2016-01-04", event_type,
        tables=[f"events.{event_type}"])
    df = get_dataframe(query).set_index("subscriber")
    assert df.proportion.unique() == [1]

