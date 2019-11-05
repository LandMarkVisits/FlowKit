# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

"""
Prefect tasks used in workflows.
"""

import prefect
from prefect import task
from prefect.triggers import all_successful, any_failed, all_finished
from prefect.engine import signals
import papermill
from typing import Optional, Dict, Sequence, List, Tuple, Any
from pathlib import Path
import pendulum
import json
import warnings
from get_secret_or_env_var import environ

import flowclient

from .utils import (
    get_output_filename,
    get_params_hash,
    dates_are_available,
    stencil_type_alias,
    get_session,
    stencil_to_date_pairs,
    make_json_serialisable,
    notebook_to_asciidoc,
    asciidoc_to_pdf,
)
from .model import WorkflowRuns


@task
def get_tag(reference_date: Optional["datetime.date"] = None) -> str:
    """
    Task to get a string to append to output filenames from this workflow run.
    The tag is unique for each set of workflow parameters and reference date.

    Parameters
    ----------
    reference_date : date, optional
        Reference date for which the workflow is running

    Returns
    -------
    str
        Tag for output filenames
    """
    params_hash = get_params_hash(prefect.context.parameters)
    ref_date_string = f"_{reference_date}" if reference_date is not None else ""
    return f"{prefect.context.flow_name}_{params_hash}{ref_date_string}"


@task
def get_date_ranges(
    reference_date: "datetime.date", date_stencil: Optional[stencil_type_alias] = None
) -> List[Tuple[pendulum.Date, pendulum.Date]]:
    """
    Task to get a list of date pairs from a date stencil.

    Parameters
    ----------
    reference_date : date
        Date to calculate offsets relative to.
    date_stencil : list of datetime.date, int and/or pairs of date/int; optional
        List of elements defining dates or date intervals.
        Each element can be:
            - a date object corresponding to an absolute date,
            - an int corresponding to an offset (in days) relative to reference_date,
            - a length-2 list [start, end] of dates or offsets, corresponding to a
              date interval (inclusive of both limits).
        Default [0]
    
    Returns
    -------
    list of tuple (pendulum.Date, pendulum.Date)
        List of pairs of date objects, each representing a date interval.
    """
    if date_stencil is None:
        date_stencil = [0]
    return stencil_to_date_pairs(stencil=date_stencil, reference_date=reference_date)


@task
def get_flowapi_url() -> str:
    """
    Task to return FlowAPI URL.

    Returns
    -------
    str
        FlowAPI URL
    """
    # This task is defined so that the flowapi url can be passed as a parameter
    # to other tasks in a workflow.
    return prefect.config.flowapi_url


@task
def get_available_dates(
    cdr_types: Optional[Sequence[str]] = None
) -> List[pendulum.Date]:
    """
    Task to return a union of the dates for which data is available in FlowDB for the specified set of CDR types.
    
    Parameters
    ----------
    cdr_types : list of str, optional
        Subset of CDR types for which to find available dates.
        If not provided, the union of available dates for all CDR types will be returned.
    
    Returns
    -------
    list of pendulum.Date
        List of available dates, in chronological order
    """
    prefect.context.logger.info(
        f"Getting available dates from FlowAPI at '{prefect.config.flowapi_url}'."
    )
    conn = flowclient.connect(
        url=prefect.config.flowapi_url, token=environ["FLOWAPI_TOKEN"]
    )
    dates = flowclient.get_available_dates(connection=conn)
    if cdr_types is None:
        prefect.context.logger.debug(
            "No CDR types provided. Will return available dates for all CDR types."
        )
        cdr_types = dates.keys()
    else:
        prefect.context.logger.debug(
            f"Returning available dates for CDR types {cdr_types}."
        )
        unknown_cdr_types = set(cdr_types).difference(dates.keys())
        if unknown_cdr_types:
            warnings.warn(f"No data available for CDR types {unknown_cdr_types}.")
    dates_union = set.union(
        *[
            set(pendulum.parse(date, exact=True) for date in dates[cdr_type])
            for cdr_type in cdr_types
            if cdr_type in dates.keys()
        ]
    )
    return sorted(list(dates_union))


@task
def filter_dates_by_earliest_date(
    dates: Sequence["datetime.date"], earliest_date: Optional["datetime.date"] = None
) -> List["datetime.date"]:
    """
    Filter task to return only dates later than or equal to earliest_date.
    If earliest_date is not provided, no filtering will be applied.
    
    Parameters
    ----------
    dates : list of date
        List of dates to filter
    earliest_date : date, optional
        Earliest date that will pass the filter
    
    Returns
    -------
    list of date
        Filtered list of dates
    """
    prefect.context.logger.info(f"Filtering out dates earlier than {earliest_date}.")
    if earliest_date is None:
        prefect.context.logger.debug(
            "No earliest date provided. Returning unfiltered list of dates."
        )
        return dates
    else:
        return [date for date in dates if date >= earliest_date]


@task
def filter_dates_by_stencil(
    dates: Sequence["datetime.date"],
    available_dates: Sequence["datetime.date"],
    date_stencil: Optional[stencil_type_alias] = None,
) -> List["datetime.date"]:
    """
    Filter task to return only dates for which all dates in the stencil are available.
    If no stencil is provided, no filtering will be applied
    (this is equivalent to 'stencil=[0]' if dates is a subset of available_dates).
    
    Parameters
    ----------
    dates : list of date
        List of dates to filter
    available_dates : list of date
        List of all dates that are available
    date_stencil : list of datetime.date, int and/or pairs of date/int; optional
        List of elements defining dates or date intervals.
        Each element can be:
            - a date object corresponding to an absolute date,
            - an int corresponding to an offset (in days) relative to a date in 'dates',
            - a length-2 list [start, end] of dates or offsets, corresponding to a
              date interval (inclusive of both limits).
    
    Returns
    -------
    list of date
        Filtered list of dates
    """
    prefect.context.logger.info("Filtering dates by stencil.")
    if date_stencil is None:
        prefect.context.logger.debug(
            "No stencil provided. Returning unfiltered list of dates."
        )
        return dates
    else:
        prefect.context.logger.debug(
            f"Returning reference dates for which all dates in stencil {date_stencil} are available."
        )
        return [
            date
            for date in dates
            if dates_are_available(date_stencil, date, available_dates)
        ]


@task
def filter_dates_by_previous_runs(
    dates: Sequence["datetime.date"]
) -> List["datetime.date"]:
    """
    Filter task to return only dates for which the workflow hasn't previously run successfully.

    Parameters
    ----------
    dates : list of date
        List of dates to filter
    
    Returns
    -------
    list of date
        Filtered list of dates
    """
    prefect.context.logger.info(
        "Filtering out dates for which this workflow has already run successfully."
    )
    session = get_session(prefect.config.db_uri)
    filtered_dates = [
        date
        for date in dates
        if WorkflowRuns.can_process(
            workflow_name=prefect.context.flow_name,
            workflow_params=prefect.context.parameters,
            reference_date=date,
            session=session,
        )
    ]
    session.close()
    return filtered_dates


@task
def record_workflow_in_process(
    reference_date: Optional["datetime.date"] = None
) -> None:
    """
    Add a row to the database to record that a workflow is running.

    Parameters
    ----------
    reference_date : date, optional
        Reference date for which the workflow is running
    """
    if reference_date is not None:
        message = (
            f"Recording workflow run 'in_process' for reference date {reference_date}."
        )
    else:
        message = "Recording workflow run 'in_process'."
    prefect.context.logger.debug(message)
    session = get_session(prefect.config.db_uri)
    WorkflowRuns.set_state(
        workflow_name=prefect.context.flow_name,
        workflow_params=prefect.context.parameters,
        reference_date=reference_date,
        scheduled_start_time=prefect.context.scheduled_start_time,
        state="in_process",
        session=session,
    )
    session.close()


@task(trigger=all_successful)
def record_workflow_done(reference_date: Optional["datetime.date"] = None) -> None:
    """
    Add a row to the database to record that a workflow completed successfully.

    Parameters
    ----------
    reference_date : date, optional
        Reference date for which the workflow is running
    """
    if reference_date is not None:
        message = f"Recording workflow run 'done' for reference date {reference_date}."
    else:
        message = "Recording workflow run 'done'."
    prefect.context.logger.debug(message)
    session = get_session(prefect.config.db_uri)
    WorkflowRuns.set_state(
        workflow_name=prefect.context.flow_name,
        workflow_params=prefect.context.parameters,
        reference_date=reference_date,
        scheduled_start_time=prefect.context.scheduled_start_time,
        state="done",
        session=session,
    )
    session.close()


@task(trigger=any_failed)
def record_workflow_failed(reference_date: Optional["datetime.date"] = None) -> None:
    """
    Add a row to the database to record that a workflow failed.

    Parameters
    ----------
    reference_date : date, optional
        Reference date for which the workflow is running
    """
    if reference_date is not None:
        message = (
            f"Recording workflow run 'failed' for reference date {reference_date}."
        )
    else:
        message = "Recording workflow run 'failed'."
    prefect.context.logger.debug(message)
    session = get_session(prefect.config.db_uri)
    WorkflowRuns.set_state(
        workflow_name=prefect.context.flow_name,
        workflow_params=prefect.context.parameters,
        reference_date=reference_date,
        scheduled_start_time=prefect.context.scheduled_start_time,
        state="failed",
        session=session,
    )
    session.close()


@task(trigger=all_finished)
def record_any_failed_workflows(reference_dates: List["datetime.date"]) -> None:
    """
    For each of the provided reference dates, if the corresponding workflow run is
    recorded as 'in_process', add a row to the database to record that the workflow failed.

    Parameters
    ----------
    reference_dates : list of date
        List of reference dates for which the workflow ran
    """
    # Note: unlike the 'record_workflow_failed' task, this task takes a list of dates,
    # not a single date. This is because if this task was mapped, and a mistake when
    # defining the workflow meant that a previous task failed to map, this task would
    # also fail to map and would therefore not run.
    prefect.context.logger.debug(
        f"Ensuring no workflow runs are left in 'in_process' state."
    )
    some_failed = False
    session = get_session(prefect.config.db_uri)
    for reference_date in reference_dates:
        if not WorkflowRuns.is_done(
            workflow_name=prefect.context.flow_name,
            workflow_params=prefect.context.parameters,
            reference_date=reference_date,
            session=session,
        ):
            some_failed = True
            prefect.context.logger.debug(
                f"Recording workflow run 'failed' for reference date {reference_date}."
            )
            WorkflowRuns.set_state(
                workflow_name=prefect.context.flow_name,
                workflow_params=prefect.context.parameters,
                reference_date=reference_date,
                scheduled_start_time=prefect.context.scheduled_start_time,
                state="failed",
                session=session,
            )
    session.close()
    if some_failed:
        raise signals.FAIL()


@task
def mappable_dict(**kwargs) -> Dict[str, Any]:
    """
    Task that returns keyword arguments as a dict.
    Equivalent to passing dict(**kwargs) within a Flow context,
    except that this is a prefect task so it can be mapped.
    """
    return kwargs


@task
def papermill_execute_notebook(
    input_filename: str,
    output_tag: str,
    parameters: Optional[Dict[str, Any]] = None,
    **kwargs,
) -> str:
    """
    Task to execute a notebook using Papermill.
    
    Parameters
    ----------
    input_filename : str
        Filename of input notebook (assumed to be in the inputs directory)
    output_tag : str
        Tag to append to output filename
    parameters : dict, optional
        Parameters to pass to the notebook
    **kwargs
        Additional keyword arguments to pass to papermill.execute_notebook
    
    Returns
    -------
    str
        Path to executed notebook
    """
    # Papermill injects all parameters into the notebook metadata, which gets
    # json-serialised, so all parameters must be json serialisable
    # (see https://github.com/nteract/papermill/issues/412).
    # 'make_json_serialisable()' has the convenient side-effect of converting tuples to
    # lists, where we would otherwise have to register a custom papermill translator
    # for tuples.
    safe_params = make_json_serialisable(parameters)
    prefect.context.logger.info(
        f"Executing notebook '{input_filename}' with parameters {safe_params}."
    )

    output_filename = get_output_filename(input_filename=input_filename, tag=output_tag)
    input_path = str(Path(prefect.config.inputs.inputs_dir) / input_filename)
    output_path = str(Path(prefect.config.outputs.notebooks_dir) / output_filename)

    prefect.context.logger.debug(f"Output notebook will be '{output_path}'.")

    papermill.execute_notebook(
        input_path, output_path, parameters=safe_params, **kwargs
    )

    prefect.context.logger.info(f"Finished executing notebook.")

    return output_path


@task
def convert_notebook_to_pdf(
    notebook_path: str,
    output_filename: Optional[str] = None,
    asciidoc_template: Optional[str] = None,
) -> str:
    """
    Task to convert a notebook to PDF, via asciidoc (without executing the notebook).
    
    Parameters
    ----------
    notebook_path : str
        Path to notebook
    output_filename : str, optional
        Filename for output PDF file.
        If not provided, this will be the name of the input notebook with the extension changed to '.pdf'
    asciidoc_template : str, optional
        Filename of a non-default template to use when exporting to asciidoc
        (assumed to be in the inputs directory)
    
    Returns
    -------
    str
        Path to output PDF file
    """
    prefect.context.logger.info(f"Converting notebook '{notebook_path}' to PDF.")
    if output_filename is None:
        output_filename = f"{Path(notebook_path).stem}.pdf"
    output_path = str(Path(prefect.config.outputs.reports_dir) / output_filename)

    if asciidoc_template is None:
        try:
            asciidoc_template_path = prefect.config.asciidoc_template_path
        except AttributeError:
            # If no template is provided, and no default template is set in the config,
            # run nbconvert without specifying a template (i.e. use the default nbconvert asciidoc template).
            asciidoc_template_path = None
    else:
        asciidoc_template_path = str(
            Path(prefect.config.inputs.inputs_dir) / asciidoc_template
        )
    prefect.context.logger.debug(
        f"Using template '{asciidoc_template_path}' to convert notebook to asciidoc."
    )

    body, resources = notebook_to_asciidoc(notebook_path, asciidoc_template_path)

    prefect.context.logger.debug("Converted notebook to asciidoc.")
    prefect.context.logger.debug("Converting asciidoc to PDF...")

    asciidoc_to_pdf(body, resources, output_path)

    prefect.context.logger.info(f"Created report '{output_filename}'.")

    return output_path
