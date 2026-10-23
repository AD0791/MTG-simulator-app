"""The risk planner page.

A GET form: the URL holds the whole state, so Back, Forward, reload and a
bookmark all reproduce the same answer. The last valid query is also kept in a
cookie, so coming back to a bare `/planner` restores it.
"""

from datetime import date
from typing import Any

from fastapi import APIRouter, Request, status
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.datastructures import QueryParams

from ..log import logger
from ..schemas.risk_plan import PlannerForm, RawPlannerForm, RiskPlanRead
from ..services import risk_planner
from . import form_errors, form_state
from .templates import templates

router = APIRouter(include_in_schema=False)

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def default_form(today: date) -> dict[str, Any]:
    start, end = risk_planner.default_dates(today)
    return RawPlannerForm(
        capital="1600",
        target_capital="2000",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        payout_percent="92",
        style="session",
        per_day="4",
        weekdays=["0", "1", "2", "3", "4"],
        risk_1="0.25",
        risk_2="0.5",
        risk_3="1",
    ).model_dump()


def _raw(params: QueryParams) -> dict[str, Any]:
    """The query as the form sent it. Repeated `weekdays` keys become a list."""
    data: dict[str, Any] = {key: params.get(key) for key in params}
    data["weekdays"] = params.getlist("weekdays")
    return RawPlannerForm.model_validate(data).model_dump()


def _plan(values: dict[str, Any], today: date) -> tuple[RiskPlanRead | None, dict[str, str]]:
    """The plan for these values, or the field messages that refuse it.

    The one try/except for the page, as on the simulator: the reader's values
    come back intact beside the field at fault. The rules are not restated —
    `PlannerForm` checks shape and the domain checks the plan.
    """
    try:
        query, risk_fields = PlannerForm.model_validate(values).to_query()
    except ValidationError as exc:
        return None, form_errors.from_validation(exc)
    try:
        return risk_planner.plan_read(query, today), {}
    except ValueError as exc:
        return None, form_errors.from_planner(exc, risk_fields)


@router.get("/planner", summary="What a capital target requires")
def planner(request: Request) -> Response:
    today = date.today()
    params = request.query_params

    if "reset" in params:
        response = _render(request, default_form(today), None, {})
        form_state.forget(response, request, form_state.PLANNER_COOKIE)
        return response

    saved = request.cookies.get(form_state.PLANNER_COOKIE)
    from_cookie = not params and bool(saved)
    if not params and not saved:
        return _render(request, default_form(today), None, {})

    query_string = saved if from_cookie and saved else str(request.url.query)
    values = _raw(QueryParams(query_string))
    plan, errors = _plan(values, today)

    if errors and from_cookie:
        # A saved query that no longer validates is dropped, not shown as an error.
        response = _render(request, default_form(today), None, {})
        form_state.forget(response, request, form_state.PLANNER_COOKIE)
        return response
    if errors:
        # Field names, never the values.
        logger.info("form.rejected", form="planner", fields=sorted(errors))
        return _render(request, values, None, errors, rejected=True)

    response = _render(request, values, plan, {})
    form_state.remember(
        response, request, form_state.PLANNER_COOKIE, query_string, form_state.FORM_MAX_AGE
    )
    return response


def _render(
    request: Request,
    values: dict[str, Any],
    plan: RiskPlanRead | None,
    errors: dict[str, str],
    *,
    rejected: bool = False,
) -> Response:
    return templates.TemplateResponse(
        request,
        "planner.html",
        {
            "values": values,
            "plan": plan,
            "errors": errors,
            "weekday_names": WEEKDAY_NAMES,
        },
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT if rejected else status.HTTP_200_OK,
    )
