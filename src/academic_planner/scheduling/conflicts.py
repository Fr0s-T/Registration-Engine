from academic_planner.domain.models import Meeting, RegistrationBundle


def meetings_conflict(left: Meeting, right: Meeting) -> bool:
    return left.overlaps(right)


def bundles_conflict(left: RegistrationBundle, right: RegistrationBundle) -> bool:
    return any(a.overlaps(b) for x in left.sections for y in right.sections for a in x.meetings for b in y.meetings)
