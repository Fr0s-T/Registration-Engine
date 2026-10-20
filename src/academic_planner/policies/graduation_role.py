from typing import Literal

GraduationRole = Literal["MANDATORY", "OPTIONAL", "NEEDS_REVIEW"]
IUL_CREDIT_BAND_RULE = "IUL_300_ECTS_CREDIT_BAND_RULE"


def graduation_role_for(
    ects: int,
    is_fyp: bool = False,
    course_type: str = "COURSE",
    *,
    degree_credit_eligible: bool = True,
) -> GraduationRole:
    """Apply the IUL 300-ECTS course-selection policy.

    Five-or-more ECTS courses are mandatory.  Training placements and final
    projects are mandatory independently of their credit value.  A course
    explicitly excluded from degree credit never enters either graduation
    pool.
    """
    if not degree_credit_eligible:
        return "NEEDS_REVIEW"
    if is_fyp or course_type == "TRAINING" or ects >= 5:
        return "MANDATORY"
    if 1 <= ects <= 4:
        return "OPTIONAL"
    return "NEEDS_REVIEW"
