import pytest

from flowmachine.core.server.utils import send_zmq_message_and_receive_reply
from .helpers import poll_until_done


# TODO: add test for code path that raises QueryProxyError with the 'get_params' action


@pytest.mark.parametrize(
    "params",
    [
        {
            "query_kind": "daily_location",
            "date": "2016-01-01",
            "method": "last",
            "aggregation_unit": "admin3",
            "subscriber_subset": None,
        },
        {
            "query_kind": "daily_location",
            "date": "2016-01-04",
            "method": "most-common",
            "aggregation_unit": "admin1",
            "subscriber_subset": None,
        },
    ],
)
@pytest.mark.asyncio
async def test_get_query_kind(params, zmq_port, zmq_host):
    """
    Running 'get_query_kind' against an existing query_id returns the expected query kind.
    """
    #
    # Run daily_location query.
    #
    msg = {"action": "run_query", "params": params, "request_id": "DUMMY_ID"}

    reply = send_zmq_message_and_receive_reply(msg, port=zmq_port, host=zmq_host)
    # assert reply["status"] in ("executing", "queued", "completed")
    assert reply["status"] in ("accepted")
    query_id = reply["data"]["query_id"]

    #
    # Wait until the query has finished.
    #
    poll_until_done(zmq_port, query_id)

    #
    # Get query result.
    #
    msg = {
        "action": "get_query_kind",
        "params": {"query_id": query_id},
        "request_id": "DUMMY_ID",
    }

    reply = send_zmq_message_and_receive_reply(msg, port=zmq_port, host=zmq_host)
    assert "done" == reply["status"]
    assert query_id == reply["data"]["query_id"]
    assert "daily_location" == reply["data"]["query_kind"]


@pytest.mark.asyncio
async def test_get_query_kind_for_nonexistent_query_id(zmq_port, zmq_host):
    """
    Running 'get_query_kind' on a non-existent query id returns an error.
    """
    #
    # Try getting query result for nonexistent ID.
    #
    msg = {
        "action": "get_query_kind",
        "params": {"query_id": "FOOBAR"},
        "request_id": "DUMMY_ID",
    }

    reply = send_zmq_message_and_receive_reply(msg, port=zmq_port, host=zmq_host)
    assert {
        "status": "error",
        "data": {"query_id": "FOOBAR", "query_state": "awol"},
        "msg": "Unknown query id: 'FOOBAR'",
    } == reply