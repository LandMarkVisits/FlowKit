import textwrap
from typing import List

from flowmachine.core import Query
from flowmachine.core.date_range import DateRange


class DFSTotalTransactionAmount(Query):
    def __init__(self, *, start_date, end_date, aggregation_unit):
        self.date_range = DateRange(start_date, end_date)
        self.aggregation_unit = aggregation_unit
        super().__init__()

    @property
    def column_names(self) -> List[str]:
        return ["date", "pcod", "value"]

    def _make_query(self):
        sql = textwrap.dedent(
            f"""
            WITH filtered_transactions AS (
                SELECT * FROM dfs.transactions
                WHERE timestamp >= '{self.date_range.start_date_as_str}'::timestamptz
                AND timestamp < '{self.date_range.one_day_past_end_date_as_str}'::timestamptz
            ),
            geolocated_transactions AS (
                SELECT * FROM filtered_transactions t1
                JOIN dfs.transactions_metadata t2
                ON t1.id = t2.transaction_id
            ),
            cell_mapping AS (
                SELECT
                    id,
                    version,
                    site_id,
                    admin1name as name,
                    admin1pcod as pcod
                FROM infrastructure.cells c
                JOIN geography.admin1 a
                ON ST_Within(c.geom_point, a.geom)
            )
            SELECT
                timestamp::date as date,
                pcod,
                sum(amount) as value
            FROM geolocated_transactions t
            JOIN cell_mapping c
            ON t.cell_id = c.id AND t.cell_version = c.version
            GROUP BY date, pcod
            """
        )
        return sql
