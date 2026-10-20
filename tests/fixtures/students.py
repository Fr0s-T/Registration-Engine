from academic_planner.fixtures import build_scenario


def fresh_student():
    return build_scenario("fresh")


def struggling_third():
    return build_scenario("struggling-third")


def regular_fourth():
    return build_scenario("regular-fourth")


def failed_fourth(capacity: int = 30):
    return build_scenario("failed-fourth", capacity)
