# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# -*- coding: utf-8 -*-
"""
Contains the definition of callables to be used in the production ETL dag.
"""
import pendulum
import re
import structlog

from pathlib import Path
from uuid import uuid1

from airflow.models import DagRun
from airflow.api.common.experimental.trigger_dag import trigger_dag

from etl.model import ETLRecord
from etl.etl_utils import CDRType, get_session, find_files, filter_files, get_config

logger = structlog.get_logger("flowetl")


# pylint: disable=unused-argument
def record_ingestion_state__callable(*, dag_run: DagRun, to_state: str, **kwargs):
    """
    Function to deal with recording the state of the ingestion. The actual
    change to the DB to record new state is accomplished in the
    ETLRecord.set_state function.

    Parameters
    ----------
    dag_run : DagRun
        Passed as part of the Dag context - contains the config.
    to_state : str
        The the resulting state of the file
    """
    cdr_type = dag_run.conf["cdr_type"]
    cdr_date = dag_run.conf["cdr_date"]

    session = get_session()
    ETLRecord.set_state(
        cdr_type=cdr_type, cdr_date=cdr_date, state=to_state, session=session
    )


# pylint: disable=unused-argument
def success_branch__callable(*, dag_run: DagRun, **kwargs):
    """
    Function to determine if we should follow the quarantine or
    the archive branch. If no downstream tasks have failed we follow
    archive branch and quarantine otherwise.
    """
    previous_task_failures = [
        dag_run.get_task_instance(task_id).state == "failed"
        for task_id in ["init", "extract", "transform", "load"]
    ]

    logger.info(f"Dag run: {dag_run}")

    if any(previous_task_failures):
        branch = "quarantine"
    else:
        branch = "archive"

    return branch


def production_trigger__callable__OLD(
    *, dag_run: DagRun, files_path: Path, cdr_type_config: dict, **kwargs
):
    """
    Function that determines which files in files/ should be processed
    and triggers the correct ETL dag with config based on filename.

    Parameters
    ----------
    dag_run : DagRun
        Passed as part of the Dag context - contains the config.
    files_path : Path
        Location of files directory
    cdr_type_config : dict
        ETL config for each cdr type
    """

    found_files = find_files(files_path=files_path)
    logger.info(found_files)
    logger.info(f"Files found: {found_files}")

    # remove files that either do not match a pattern
    # or have been processed successfully already...
    filtered_files = filter_files(
        found_files=found_files, cdr_type_config=cdr_type_config
    )
    logger.info(
        f"Files found that match the filename pattern and have not been processed: {filtered_files}"
    )

    # what to do with these!?
    bad_files = list(set(found_files) - set(filtered_files))
    logger.info(f"Bad files found: {bad_files}")

    for file in filtered_files:
        config = get_config(file_name=file.name, cdr_type_config=cdr_type_config)

        cdr_type = config["cdr_type"]
        cdr_date = config["cdr_date"]
        uuid = uuid1()
        trigger_dag(
            f"etl_{cdr_type}",
            execution_date=cdr_date,
            run_id=f"{file.name}-{str(uuid)}",
            conf=config,
            replace_microseconds=False,
        )


def find_unprocessed_dates_from_files(
    files, filename_pattern, cdr_type, session, ignore_filenames=["README.md"]
):
    logger.info(f"all_files_found: {files}")
    filename_matches = {
        file: re.fullmatch(filename_pattern, str(file))
        for file in files
        if file not in ignore_filenames
    }
    logger.info(f"filename_matches: {filename_matches}")
    found_dates = {
        file: pendulum.parse(m.group(1))
        for file, m in filename_matches.items()
        if m is not None
    }
    logger.info(f"found_dates: {found_dates}")
    unprocessed_dates = {
        file: date
        for file, date in found_dates.items()
        if ETLRecord.can_process(cdr_type=cdr_type, cdr_date=date, session=session)
    }
    logger.info(f"unprocessed_dates: {unprocessed_dates}")
    return unprocessed_dates


def production_trigger__callable(
    *, dag_run: DagRun, files_path: Path, cdr_type_config: dict, **kwargs
):
    """
    Function that determines which files in files/ should be processed
    and triggers the correct ETL dag with config based on filename.

    Parameters
    ----------
    dag_run : DagRun
        Passed as part of the Dag context - contains the config.
    files_path : Path
        Location of files directory
    cdr_type_config : dict
        ETL config for each cdr type
    """
    session = get_session()

    for cdr_type, cfg in cdr_type_config.items():
        cdr_type = CDRType(cdr_type)

        source_type = cfg["source"]["source_type"]
        print(f"{cdr_type!r} ({source_type}): {cfg}")

        if source_type == "csv":
            filename_pattern = cfg["source"]["filename_pattern"]
            print(f"Filename pattern: {filename_pattern!r}")
            all_files_found = sorted([file.name for file in files_path.glob("*")])
            unprocessed_files_and_dates = find_unprocessed_dates_from_files(
                all_files_found, filename_pattern, cdr_type, session
            )
            for file, cdr_date in unprocessed_files_and_dates.items():
                uuid = uuid1()
                cdr_date_str = cdr_date.strftime("%Y%m%d")
                config = {
                    "cdr_type": cdr_type,
                    "cdr_date": cdr_date,
                    "file_name": file,
                    "template_path": f"etl/{cdr_type}",
                }
                trigger_dag(
                    f"etl_{cdr_type}",
                    execution_date=cdr_date,
                    run_id=f"{cdr_type.upper()}_{cdr_date_str}-{str(uuid)}",
                    conf=config,
                    replace_microseconds=False,
                )
        elif source_type == "sql":
            source_table = cfg["source"]["table_name"]

            # TODO: extract unprocessed dates from source_table
            # unprocessed_dates
            raise NotImplementedError()
        else:
            raise NotImplementedError()
