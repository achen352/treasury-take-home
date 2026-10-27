"""Net contents: the volume must match the application, in any unit."""

from app.domain.models import FieldResult, LabelField, Status
from app.domain.normalize import parse_net_contents, same_volume


def check_net_contents(expected: str | None, found: str | None, *, cfr: str) -> FieldResult:
    def result(status: Status, note: str) -> FieldResult:
        return FieldResult(
            field=LabelField.NET_CONTENTS,
            status=status,
            cfr=cfr,
            expected=expected,
            found=found,
            notes=(note,),
        )

    if found is None or not found.strip():
        return result(Status.FAIL, "Not found on the label.")
    parsed = parse_net_contents(found)
    label = parsed.volume
    if label is None:
        return result(Status.REVIEW, parsed.problem or "Couldn't read the volume.")

    application = parse_net_contents(expected)
    if application.volume is None:
        detail = f": {application.problem}" if application.problem else "."
        return result(Status.REVIEW, f"Couldn't read the application's net contents{detail}")

    if same_volume(label, application.volume):
        if label.unit == application.volume.unit:
            return result(Status.PASS, "Same volume.")
        return result(
            Status.PASS, f"Same volume in different units ({label} = {application.volume})."
        )
    return result(
        Status.FAIL, f"The label says {label} but the application says {application.volume}."
    )
