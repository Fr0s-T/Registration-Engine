from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from academic_planner.database.models import (
    CourseRecord, CourseRequirementGroupRecognition, CurriculumRevision,
    DegreeContract, DegreeRequirement, Equivalency, EquivalencyMatch,
    LabRelationship, Offering, PrerequisiteGroup, PrerequisiteItem,
    RequirementGroupCourseRecord, RequirementGroupRecord, SourceDocument,
    StudentAttemptRecord, StudentOfferingOverride, StudentRecognitionRecord,
    StudentOptionalCreditApproval, StudentRecord, StudentRequirementRecord,
    TranscriptCodeMapping,
)

from .models import ParsedCurriculum, ValidationReport
from .validation import validate_curriculum
from academic_planner.policies.graduation_role import (
    IUL_CREDIT_BAND_RULE,
    graduation_role_for,
)
from academic_planner.matching.catalogue import synchronize_transition_catalogue


@dataclass(frozen=True)
class ImportResult:
    curriculum_version: str
    courses_inserted: int
    prerequisites_inserted: int
    requirements_inserted: int
    lab_relationships_inserted: int
    equivalencies_invalidated: int
    matching_decisions_invalidated: int
    offerings_invalidated: int
    external_prerequisites_invalidated: int
    student_links_rebound: int
    student_links_invalidated: int


class CurriculumImportService:
    """Publishes one parsed curriculum as a clean replacement.

    The caller owns the transaction and must commit only after this method returns.
    """
    def replace(self, session: Session, parsed: ParsedCurriculum,
                source_document: SourceDocument, report: ValidationReport | None = None) -> ImportResult:
        report = report or validate_curriculum(parsed)
        if report.fatal_errors:
            raise ValueError("Curriculum has fatal validation errors and cannot be imported")
        version = parsed.curriculum_version
        revisions = session.scalars(select(CurriculumRevision).where(CurriculumRevision.version == version)).all()
        revision_ids = [row.id for row in revisions]
        old_ids = list(session.scalars(select(CourseRecord.id).where(CourseRecord.curriculum_id.in_(revision_ids))).all()) if revision_ids else []
        course_keys = {
            row.id: (row.curriculum.version, row.code)
            for row in session.scalars(
                select(CourseRecord).join(CurriculumRevision)
            ).all()
        }
        equivalencies = matching_decisions = offerings = external_groups = 0
        student_attempts = []
        student_requirements = []
        student_recognitions = []
        student_offering_overrides = []
        optional_approvals = []
        contract_snapshots: list[dict] = []
        group_snapshots: list[dict] = []
        membership_snapshots: list[dict] = []
        category_recognition_snapshots: list[dict] = []
        student_contract_links: list[tuple[int, int]] = []
        memberships: list[RequirementGroupCourseRecord] = []
        category_recognitions: list[CourseRequirementGroupRecognition] = []

        replaced_contracts = list(session.scalars(
            select(DegreeContract).where(
                DegreeContract.curriculum_id.in_(revision_ids)
            )
        )) if revision_ids else []
        replaced_contract_ids = {contract.id for contract in replaced_contracts}
        replaced_groups = list(session.scalars(
            select(RequirementGroupRecord).where(
                RequirementGroupRecord.contract_id.in_(replaced_contract_ids)
            )
        )) if replaced_contract_ids else []
        replaced_group_ids = {group.id for group in replaced_groups}
        contract_key_by_id = {
            contract.id: (
                version, contract.program_code, contract.effective_academic_year,
            )
            for contract in replaced_contracts
        }
        group_key_by_id = {
            group.id: (*contract_key_by_id[group.contract_id], group.code)
            for group in replaced_groups
        }
        if replaced_contract_ids:
            student_contract_links = [
                (student.id, student.degree_contract_id)
                for student in session.scalars(select(StudentRecord).where(
                    StudentRecord.degree_contract_id.in_(replaced_contract_ids)
                ))
            ]
            contract_snapshots = [
                {
                    "old_id": contract.id,
                    "key": contract_key_by_id[contract.id],
                    "program_code": contract.program_code,
                    "title": contract.title,
                    "graduation_ects_target": contract.graduation_ects_target,
                    "effective_academic_year": contract.effective_academic_year,
                    "source_document_id": contract.source_document_id,
                    "verification_status": contract.verification_status,
                }
                for contract in replaced_contracts
            ]
            group_snapshots = [
                {
                    "old_id": group.id,
                    "contract_old_id": group.contract_id,
                    "parent_old_id": group.parent_id,
                    "key": group_key_by_id[group.id],
                    "code": group.code,
                    "title": group.title,
                    "required_ects": group.required_ects,
                    "rule_type": group.rule_type,
                    "display_order": group.display_order,
                    "source_locator": group.source_locator,
                    "verification_status": group.verification_status,
                }
                for group in replaced_groups
            ]
            memberships = list(session.scalars(
                select(RequirementGroupCourseRecord).where(
                    RequirementGroupCourseRecord.group_id.in_(replaced_group_ids)
                )
            )) if replaced_group_ids else []
            membership_snapshots = [
                {
                    "group_old_id": membership.group_id,
                    "course_key": course_keys[membership.course_id],
                    "contribution_ects": membership.contribution_ects,
                    "membership_type": membership.membership_type,
                    "language_track": membership.language_track,
                    "source_locator": membership.source_locator,
                }
                for membership in memberships
            ]

        # Recognition rows may either belong to a replaced contract group or
        # point from a course that is about to be recreated. Preserve both forms.
        all_group_keys = dict(group_key_by_id)
        for group, contract, curriculum in session.execute(
            select(RequirementGroupRecord, DegreeContract, CurriculumRevision)
            .join(DegreeContract, DegreeContract.id == RequirementGroupRecord.contract_id)
            .join(CurriculumRevision, CurriculumRevision.id == DegreeContract.curriculum_id)
        ):
            all_group_keys.setdefault(group.id, (
                curriculum.version, contract.program_code,
                contract.effective_academic_year, group.code,
            ))
        recognition_filters = []
        if old_ids:
            recognition_filters.append(
                CourseRequirementGroupRecognition.source_course_id.in_(old_ids)
            )
        if replaced_group_ids:
            recognition_filters.append(
                CourseRequirementGroupRecognition.requirement_group_id.in_(
                    replaced_group_ids
                )
            )
        if recognition_filters:
            category_recognitions = list(session.scalars(
                select(CourseRequirementGroupRecognition).where(
                    or_(*recognition_filters)
                )
            ))
            category_recognition_snapshots = [
                {
                    "source_key": course_keys[row.source_course_id],
                    "group_key": all_group_keys[row.requirement_group_id],
                    "recognition_scope": row.recognition_scope,
                    "verification_status": row.verification_status,
                    "provenance": row.provenance,
                    "notes": row.notes,
                }
                for row in category_recognitions
            ]
            session.execute(delete(CourseRequirementGroupRecognition).where(
                CourseRequirementGroupRecognition.id.in_(
                    [row.id for row in category_recognitions]
                )
            ))
            session.flush()
            for recognition in category_recognitions:
                if recognition in session:
                    session.expunge(recognition)
        if replaced_contract_ids:
            session.execute(update(StudentRecord).where(
                StudentRecord.degree_contract_id.in_(replaced_contract_ids)
            ).values(degree_contract_id=None))
            session.execute(delete(DegreeContract).where(
                DegreeContract.id.in_(replaced_contract_ids)
            ))
            session.flush()
            for deleted in [
                *category_recognitions, *memberships, *replaced_groups,
                *replaced_contracts,
            ]:
                if deleted in session:
                    session.expunge(deleted)
        if old_ids:
            # Student data is durable. Catalog integer IDs are not: a replacement
            # creates new rows, so preserve links by (curriculum version, code),
            # remove the restrictive link rows, then rebind them below.
            student_attempts = [
                (row.id, course_keys[row.course_id])
                for row in session.scalars(select(StudentAttemptRecord).where(
                    StudentAttemptRecord.course_id.in_(old_ids))).all()
            ]
            student_requirements = [
                (row.student_id, course_keys[row.course_id], row.authority,
                 row.source_reference, row.notes)
                for row in session.scalars(select(StudentRequirementRecord).where(
                    StudentRequirementRecord.course_id.in_(old_ids))).all()
            ]
            student_recognitions = [
                (row.student_id, course_keys[row.source_course_id],
                 course_keys[row.target_course_id], row.recognizes_history,
                 row.verification_status, row.authority, row.notes)
                for row in session.scalars(select(StudentRecognitionRecord).where(or_(
                    StudentRecognitionRecord.source_course_id.in_(old_ids),
                    StudentRecognitionRecord.target_course_id.in_(old_ids),
                ))).all()
            ]
            student_offering_overrides = [
                (row.student_id, course_keys[row.course_id], row.academic_year_start,
                 row.semester, row.language_track, row.delivery_mode, row.authority,
                 row.verified, row.notes)
                for row in session.scalars(select(StudentOfferingOverride).where(
                    StudentOfferingOverride.course_id.in_(old_ids))).all()
            ]
            optional_approvals = [
                (row.id, course_keys[row.course_id])
                for row in session.scalars(select(StudentOptionalCreditApproval).where(
                    StudentOptionalCreditApproval.course_id.in_(old_ids))).all()
            ]
            session.execute(update(StudentAttemptRecord).where(
                StudentAttemptRecord.course_id.in_(old_ids)).values(course_id=None))
            session.execute(delete(StudentRecognitionRecord).where(or_(
                StudentRecognitionRecord.source_course_id.in_(old_ids),
                StudentRecognitionRecord.target_course_id.in_(old_ids),
            )))
            session.execute(delete(StudentOfferingOverride).where(
                StudentOfferingOverride.course_id.in_(old_ids)))
            session.execute(delete(StudentRequirementRecord).where(
                StudentRequirementRecord.course_id.in_(old_ids)))
            # Approval rows are durable audit records. Detach their catalog link
            # before replacement and require renewed review even if the code returns.
            session.execute(update(StudentOptionalCreditApproval).where(
                StudentOptionalCreditApproval.course_id.in_(old_ids)).values(
                    course_id=None, status="UNVERIFIED"
                ))
            matching_decisions = session.query(EquivalencyMatch).filter(or_(
                EquivalencyMatch.old_course_id.in_(old_ids),
                EquivalencyMatch.new_course_id.in_(old_ids),
            )).delete(synchronize_session=False)
            equivalencies = session.query(Equivalency).filter(or_(Equivalency.source_course_id.in_(old_ids), Equivalency.target_course_id.in_(old_ids))).delete(synchronize_session=False)
            offerings = session.query(Offering).filter(Offering.course_id.in_(old_ids)).delete(synchronize_session=False)
            referenced_groups = list(session.scalars(select(PrerequisiteItem.group_id).where(PrerequisiteItem.prerequisite_course_id.in_(old_ids))).all())
            owned_groups = set(session.scalars(select(PrerequisiteGroup.id).where(PrerequisiteGroup.course_id.in_(old_ids))).all())
            external = set(referenced_groups) - owned_groups
            external_groups = len(external)
            if external: session.execute(delete(PrerequisiteGroup).where(PrerequisiteGroup.id.in_(external)))
            session.execute(delete(PrerequisiteGroup).where(PrerequisiteGroup.course_id.in_(old_ids)))
            session.execute(delete(LabRelationship).where(or_(LabRelationship.course_id.in_(old_ids), LabRelationship.lab_course_id.in_(old_ids))))
            session.execute(delete(DegreeRequirement).where(DegreeRequirement.curriculum_id.in_(revision_ids)))
            session.execute(delete(CourseRecord).where(CourseRecord.id.in_(old_ids)))
        if revision_ids:
            session.execute(delete(CurriculumRevision).where(CurriculumRevision.id.in_(revision_ids)))
        session.flush()
        # SQLite may immediately reuse integer primary keys. Detach bulk-deleted rows
        # before inserting their replacements so the identity map cannot associate a
        # new course with an obsolete in-memory object.
        for state in list(session.identity_map.all_states()):
            identity = state.identity[0] if state.identity else None
            if ((state.class_ is CourseRecord and identity in old_ids)
                    or (state.class_ is CurriculumRevision and identity in revision_ids)):
                session.expunge(state.obj())
        revision = CurriculumRevision(
            version=version, revision=parsed.source_revision,
            accepted_credit_target=parsed.stated_total_ects or report.total_ects,
            active=True, source_document_id=source_document.id,
        )
        session.add(revision); session.flush()
        non_degree_codes = {
            row.source_code.upper()
            for row in session.scalars(select(TranscriptCodeMapping).where(
                TranscriptCodeMapping.mapping_kind == "NON_DEGREE"
            ))
        }
        ids: dict[str, int] = {}
        graduation_roles: dict[str, str] = {}
        for item in parsed.courses:
            graduation_role = graduation_role_for(
                item.ects,
                item.is_fyp,
                item.course_type,
                degree_credit_eligible=item.code.upper() not in non_degree_codes,
            )
            row = CourseRecord(
                curriculum_id=revision.id, code=item.code, title=item.title, ects=item.ects,
                reference_year=item.reference_year, reference_semester=item.reference_semester,
                course_type=item.course_type, is_fyp=item.is_fyp, notes=item.notes,
                provenance=f"{version}_CURRICULUM_IMPORT", verification_status="SOURCE_IMPORTED",
                source_document_id=source_document.id, source_locator=item.source.location,
                academic_track_policy=("TRACK_SPECIFIC" if item.language_track else "SHARED"),
                permitted_student_tracks=([item.language_track] if item.language_track else ["EN", "FR"]),
                graduation_role=graduation_role,
                graduation_role_basis=IUL_CREDIT_BAND_RULE,
            )
            session.add(row); session.flush(); ids[item.code] = row.id
            graduation_roles[item.code] = graduation_role
        requirement_codes = [
            code for code in parsed.degree_requirements
            if graduation_roles.get(code) == "MANDATORY"
        ]
        by_code = {item.code: item for item in parsed.courses}
        for code in requirement_codes:
            item = by_code[code]
            session.add(DegreeRequirement(
                curriculum_id=revision.id, course_id=ids[code], language_track=item.language_track,
                requirement_type=("TRAINING" if item.course_type == "TRAINING" else "FYP" if item.is_fyp else "COURSE"),
            ))
        prerequisite_count = 0
        for rule in parsed.prerequisite_rules:
            group = PrerequisiteGroup(
                course_id=ids[rule.course_code], logic=rule.logic, ambiguous=rule.ambiguous,
                provenance=f"{version}_CURRICULUM_IMPORT", source_text=rule.source_text,
            )
            session.add(group); session.flush()
            for code in rule.prerequisite_codes:
                session.add(PrerequisiteItem(group_id=group.id, prerequisite_course_id=ids[code]))
                prerequisite_count += 1
        for relation in parsed.lab_relationships:
            session.add(LabRelationship(
                course_id=ids[relation.course_code], lab_course_id=ids[relation.lab_code],
                mandatory=relation.mandatory, source_locator=relation.source.location,
            ))
        current_keys = {
            (row.curriculum.version, row.code): row.id
            for row in session.scalars(
                select(CourseRecord).join(CurriculumRevision)
            ).all()
        }
        contract_id_by_old: dict[int, int] = {}
        for snapshot in contract_snapshots:
            contract = DegreeContract(
                curriculum_id=revision.id,
                program_code=snapshot["program_code"],
                title=snapshot["title"],
                graduation_ects_target=snapshot["graduation_ects_target"],
                effective_academic_year=snapshot["effective_academic_year"],
                source_document_id=snapshot["source_document_id"],
                verification_status=snapshot["verification_status"],
            )
            session.add(contract)
            session.flush()
            contract_id_by_old[snapshot["old_id"]] = contract.id

        group_id_by_old: dict[int, int] = {}
        pending_groups = list(group_snapshots)
        while pending_groups:
            ready = [
                snapshot for snapshot in pending_groups
                if snapshot["parent_old_id"] is None
                or snapshot["parent_old_id"] in group_id_by_old
            ]
            if not ready:
                raise ValueError(
                    "Degree-contract group hierarchy could not be rebound during "
                    "curriculum replacement."
                )
            for snapshot in ready:
                group = RequirementGroupRecord(
                    contract_id=contract_id_by_old[snapshot["contract_old_id"]],
                    parent_id=(
                        group_id_by_old[snapshot["parent_old_id"]]
                        if snapshot["parent_old_id"] is not None else None
                    ),
                    code=snapshot["code"],
                    title=snapshot["title"],
                    required_ects=snapshot["required_ects"],
                    rule_type=snapshot["rule_type"],
                    display_order=snapshot["display_order"],
                    source_locator=snapshot["source_locator"],
                    verification_status=snapshot["verification_status"],
                )
                session.add(group)
                session.flush()
                group_id_by_old[snapshot["old_id"]] = group.id
                pending_groups.remove(snapshot)

        for snapshot in membership_snapshots:
            course_id = current_keys.get(snapshot["course_key"])
            if course_id is None:
                raise ValueError(
                    "Curriculum replacement would remove contract course "
                    f"{snapshot['course_key'][1]}; update the degree contract first."
                )
            session.add(RequirementGroupCourseRecord(
                group_id=group_id_by_old[snapshot["group_old_id"]],
                course_id=course_id,
                contribution_ects=snapshot["contribution_ects"],
                membership_type=snapshot["membership_type"],
                language_track=snapshot["language_track"],
                source_locator=snapshot["source_locator"],
            ))

        current_group_keys: dict[tuple[str, str, str, str], int] = {}
        for group, contract, curriculum in session.execute(
            select(RequirementGroupRecord, DegreeContract, CurriculumRevision)
            .join(DegreeContract, DegreeContract.id == RequirementGroupRecord.contract_id)
            .join(CurriculumRevision, CurriculumRevision.id == DegreeContract.curriculum_id)
        ):
            current_group_keys[(
                curriculum.version, contract.program_code,
                contract.effective_academic_year, group.code,
            )] = group.id
        for snapshot in category_recognition_snapshots:
            source_id = current_keys.get(snapshot["source_key"])
            group_id = current_group_keys.get(snapshot["group_key"])
            if source_id is None or group_id is None:
                raise ValueError(
                    "Curriculum replacement would orphan a verified contract-category "
                    "recognition; update the curriculum and contract together."
                )
            session.add(CourseRequirementGroupRecognition(
                source_course_id=source_id,
                requirement_group_id=group_id,
                recognition_scope=snapshot["recognition_scope"],
                verification_status=snapshot["verification_status"],
                provenance=snapshot["provenance"],
                notes=snapshot["notes"],
            ))
        for student_id, old_contract_id in student_contract_links:
            session.execute(update(StudentRecord).where(
                StudentRecord.id == student_id
            ).values(degree_contract_id=contract_id_by_old[old_contract_id]))

        student_links_rebound = 0
        student_links_invalidated = 0
        for attempt_id, key in student_attempts:
            course_id = current_keys.get(key)
            if course_id is None:
                student_links_invalidated += 1
                continue
            session.execute(update(StudentAttemptRecord).where(
                StudentAttemptRecord.id == attempt_id).values(course_id=course_id))
            student_links_rebound += 1
        for student_id, key, authority, source_reference, notes in student_requirements:
            course_id = current_keys.get(key)
            if course_id is None:
                student_links_invalidated += 1
                continue
            session.add(StudentRequirementRecord(
                student_id=student_id, course_id=course_id,
                authority=authority, source_reference=source_reference, notes=notes,
            ))
            student_links_rebound += 1
        for (student_id, source_key, target_key, recognizes_history,
             verification_status, authority, notes) in student_recognitions:
            source_id = current_keys.get(source_key)
            target_id = current_keys.get(target_key)
            if source_id is None or target_id is None:
                student_links_invalidated += 1
                continue
            session.add(StudentRecognitionRecord(
                student_id=student_id, source_course_id=source_id,
                target_course_id=target_id, recognizes_history=recognizes_history,
                verification_status=verification_status, authority=authority,
                notes=notes,
            ))
            student_links_rebound += 1
        for (student_id, key, academic_year_start, semester, language_track,
             delivery_mode, authority, verified, notes) in student_offering_overrides:
            course_id = current_keys.get(key)
            if course_id is None:
                student_links_invalidated += 1
                continue
            session.add(StudentOfferingOverride(
                student_id=student_id, course_id=course_id,
                academic_year_start=academic_year_start, semester=semester,
                language_track=language_track, delivery_mode=delivery_mode,
                authority=authority, verified=verified, notes=notes,
            ))
            student_links_rebound += 1
        for approval_id, key in optional_approvals:
            course_id = current_keys.get(key)
            values = {"status": "UNVERIFIED"}
            if course_id is not None:
                values["course_id"] = course_id
                student_links_rebound += 1
            else:
                student_links_invalidated += 1
            session.execute(update(StudentOptionalCreditApproval).where(
                StudentOptionalCreditApproval.id == approval_id).values(**values))
        # Curriculum replacement recreates integer IDs. Rebind the durable
        # code-based transition catalogue before any subsequent plan can run.
        synchronize_transition_catalogue(session)
        source_document.status = "IMPORTED"
        source_document.notes = f"Active {version} curriculum source; {len(parsed.courses)} courses imported."
        session.flush()
        return ImportResult(version, len(parsed.courses), prerequisite_count,
            len(requirement_codes), len(parsed.lab_relationships), equivalencies,
            matching_decisions, offerings, external_groups,
            student_links_rebound, student_links_invalidated)
