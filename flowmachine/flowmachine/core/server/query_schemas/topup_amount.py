# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

from marshmallow import fields, post_load
from marshmallow.validate import OneOf, Length

from flowmachine.features import TopUpAmount
from .custom_fields import SubscriberSubset, Statistic
from .base_query_with_sampling import (
    BaseQueryWithSamplingSchema,
    BaseExposedQueryWithSampling,
)

__all__ = ["TopUpAmountSchema", "TopUpAmountExposed"]


class TopUpAmountSchema(BaseQueryWithSamplingSchema):
    query_kind = fields.String(validate=OneOf(["topup_amount"]))
    start = fields.Date(required=True)
    stop = fields.Date(required=True)
    statistic = Statistic()
    subscriber_subset = SubscriberSubset()

    @post_load
    def make_query_object(self, params, **kwargs):
        return TopUpAmountExposed(**params)


class TopUpAmountExposed(BaseExposedQueryWithSampling):
    def __init__(
        self, *, start, stop, statistic, subscriber_subset=None, sampling=None
    ):
        # Note: all input parameters need to be defined as attributes on `self`
        # so that marshmallow can serialise the object correctly.
        self.start = start
        self.stop = stop
        self.statistic = statistic
        self.subscriber_subset = subscriber_subset
        self.sampling = sampling

    @property
    def _unsampled_query_obj(self):
        """
        Return the underlying flowmachine topup_amount object.

        Returns
        -------
        Query
        """
        return TopUpAmount(
            start=self.start,
            stop=self.stop,
            statistic=self.statistic,
            subscriber_subset=self.subscriber_subset,
        )
