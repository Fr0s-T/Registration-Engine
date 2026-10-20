"""Stable credit identities shared by import, normalization, and reconciliation."""

from __future__ import annotations

from collections.abc import Hashable, Iterable, Mapping


def canonical_course_credit_identities(
    course_keys: Mapping[Hashable, tuple[str, str]],
    equivalent_pairs: Iterable[tuple[Hashable, Hashable]],
) -> dict[Hashable, str]:
    """Return a stable identity for every course in an exact-equivalency component.

    Database primary keys are intentionally excluded from the returned value because
    curriculum replacement recreates course rows.  The lexicographically smallest
    curriculum-version/course-code pair gives equivalent OLD and NEW courses the same
    repeat/credit identity while remaining stable across those replacements.
    """

    parent = {course_id: course_id for course_id in course_keys}

    def find(course_id: Hashable) -> Hashable:
        parent.setdefault(course_id, course_id)
        if parent[course_id] != course_id:
            parent[course_id] = find(parent[course_id])
        return parent[course_id]

    def union(left: Hashable, right: Hashable) -> None:
        if left not in course_keys or right not in course_keys:
            return
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        left_key = course_keys[left_root]
        right_key = course_keys[right_root]
        if left_key <= right_key:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    for left, right in equivalent_pairs:
        union(left, right)

    members: dict[Hashable, list[tuple[str, str]]] = {}
    for course_id, key in course_keys.items():
        members.setdefault(find(course_id), []).append(
            (key[0].upper(), key[1].upper())
        )

    component_identity = {
        root: "course:" + ":".join(min(keys))
        for root, keys in members.items()
    }
    return {
        course_id: component_identity[find(course_id)]
        for course_id in course_keys
    }
