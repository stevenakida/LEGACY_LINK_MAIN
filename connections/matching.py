"""Phase 7 EducationMatchService: the single place that decides *why* two users
match educationally. Templates and views render what this returns; none of
them re-derive a relationship label on their own.

Education lives on the User row as four (institution FK, completion year)
pairs -- Primary, O-Level (`secondary_school`), A-Level (`high_school`) and
University (`tertiary_school`). Matching is always by institution ID
(`alumni.School` primary key) plus level plus year, never by typed school
name.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from django.utils.translation import gettext_lazy as _


PRIMARY = 'PRIMARY'
O_LEVEL = 'O_LEVEL'
A_LEVEL = 'A_LEVEL'
UNIVERSITY = 'UNIVERSITY'

# Level -> (School FK attribute on User, year attribute on User). Display
# order is "most recent education first", used wherever a deterministic
# level ordering is needed (Discover group order, fallback record choice).
LEVELS = [
    (UNIVERSITY, 'tertiary_school', 'tertiary_completion_year'),
    (A_LEVEL, 'high_school', 'high_school_completion_year'),
    (O_LEVEL, 'secondary_school', 'secondary_completion_year'),
    (PRIMARY, 'primary_school', 'primary_completion_year'),
]
LEVEL_FIELDS = {level: (school, year) for level, school, year in LEVELS}
LEVEL_ORDER = [level for level, _, _ in LEVELS]

# URL/filter slug <-> level. "all" is handled by callers.
LEVEL_SLUGS = {
    'primary': PRIMARY,
    'o_level': O_LEVEL,
    'a_level': A_LEVEL,
    'university': UNIVERSITY,
}
SLUG_BY_LEVEL = {level: slug for slug, level in LEVEL_SLUGS.items()}

LEVEL_LABELS = {
    PRIMARY: _('Primary'),
    O_LEVEL: _('O-Level'),
    A_LEVEL: _('A-Level'),
    UNIVERSITY: _('University'),
}

CLASSMATE = 'CLASSMATE'
SAME_PRIMARY = 'SAME_PRIMARY'
SAME_O_LEVEL = 'SAME_O_LEVEL'
SAME_A_LEVEL = 'SAME_A_LEVEL'
SAME_UNIVERSITY = 'SAME_UNIVERSITY'
SAME_SCHOOL = 'SAME_SCHOOL'

REASON_LABELS = {
    CLASSMATE: _('Classmate'),
    SAME_PRIMARY: _('Same primary school'),
    SAME_O_LEVEL: _('Same O-Level'),
    SAME_A_LEVEL: _('Same A-Level'),
    SAME_UNIVERSITY: _('Same university'),
    SAME_SCHOOL: _('Same school'),
}

# Strength order from the Phase 7 spec: lower rank wins when several
# education records match.
_LEVEL_REASON = {
    PRIMARY: SAME_PRIMARY,
    O_LEVEL: SAME_O_LEVEL,
    A_LEVEL: SAME_A_LEVEL,
    UNIVERSITY: SAME_UNIVERSITY,
}
_REASON_RANK = {
    CLASSMATE: 0,
    SAME_PRIMARY: 1,
    SAME_O_LEVEL: 2,
    SAME_A_LEVEL: 3,
    SAME_UNIVERSITY: 4,
    SAME_SCHOOL: 5,
}


@dataclass(frozen=True)
class EducationRecord:
    level: str
    institution_id: int
    institution_name: str
    cohort_year: Optional[int]


@dataclass(frozen=True)
class MatchReason:
    reason_code: str
    institution_id: int
    institution_name: str
    education_level: str
    cohort_year: Optional[int]

    @property
    def display_label(self):
        return REASON_LABELS[self.reason_code]

    @property
    def level_label(self):
        return LEVEL_LABELS[self.education_level]

    @property
    def level_slug(self):
        return SLUG_BY_LEVEL[self.education_level]

    @property
    def rank(self):
        return _REASON_RANK[self.reason_code]

    def as_dict(self):
        return {
            'reason_code': self.reason_code,
            'display_label': str(self.display_label),
            'institution_id': self.institution_id,
            'institution_name': self.institution_name,
            'education_level': self.education_level,
            'cohort_year': self.cohort_year,
        }


@dataclass
class MatchResult:
    """`best` is the match shown on a card; `all_matches` keeps every
    matching record so callers (filters, search) can look at the rest."""
    best: MatchReason
    all_matches: List[MatchReason] = field(default_factory=list)


def education_records(user):
    """The user's non-empty education records. Reads the four School FKs via
    `user.<fk>` -- callers displaying many users should select_related them
    (see connections.services.EDUCATION_SELECT_RELATED) to avoid N+1."""
    records = []
    for level, school_attr, year_attr in LEVELS:
        school = getattr(user, school_attr)
        if school is not None:
            records.append(EducationRecord(level, school.id, school.name, getattr(user, year_attr)))
    return records


def reason_for(level, institution_id, institution_name, same_cohort, other_year):
    """Build the MatchReason for two users who share `institution_id` at the
    same `level`. `same_cohort` says whether their completion years are both
    known and equal (=> CLASSMATE); otherwise it's the level-specific reason.
    `other_year` is the other person's completion year, shown on their card.
    Discovery, connected and pending views all build reasons through here so
    the codes/labels can never drift apart."""
    return MatchReason(
        reason_code=CLASSMATE if same_cohort else _LEVEL_REASON[level],
        institution_id=institution_id,
        institution_name=institution_name,
        education_level=level,
        cohort_year=other_year,
    )


def _pair_reason(mine, theirs):
    if mine.institution_id != theirs.institution_id:
        return None
    if mine.level == theirs.level:
        same_cohort = bool(mine.cohort_year and theirs.cohort_year and mine.cohort_year == theirs.cohort_year)
        return reason_for(mine.level, mine.institution_id, mine.institution_name, same_cohort, theirs.cohort_year)
    # Same institution row appearing under different education levels: we
    # know they share a school but not in what capacity.
    return MatchReason(
        reason_code=SAME_SCHOOL,
        institution_id=mine.institution_id,
        institution_name=mine.institution_name,
        education_level=mine.level,
        cohort_year=None,
    )


def match_records(my_records, their_records):
    """Match two lists of EducationRecord. Returns MatchResult, or None when
    the two share no institution."""
    matches = []
    for mine in my_records:
        for theirs in their_records:
            reason = _pair_reason(mine, theirs)
            if reason is not None:
                matches.append(reason)
    if not matches:
        return None
    matches.sort(key=lambda m: (m.rank, LEVEL_ORDER.index(m.education_level)))
    return MatchResult(best=matches[0], all_matches=matches)


def match_users(viewer, other):
    return match_records(education_records(viewer), education_records(other))


def fallback_record(user):
    """The person's own most recent education record, for showing *something
    factual* on a connection that shares no institution with the viewer.
    None when they've added no education at all."""
    records = education_records(user)
    if not records:
        return None
    records.sort(key=lambda r: LEVEL_ORDER.index(r.level))
    return records[0]
