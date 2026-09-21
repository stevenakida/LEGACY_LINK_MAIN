"""Phase 7: EducationMatchService -- structured matching rules."""
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.models import User
from alumni.models import School

from . import matching as m

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])


def school(name, kind='secondary'):
    return School.objects.create(name=name, school_type=kind)


def person(ident, name='P', **edu):
    return User.objects.create_user(phone_or_email=ident, password='x', full_name=name, **edu)


class RecordMatchingRules(SimpleTestCase):
    """Pure-Python rules on EducationRecord lists (no database)."""

    def rec(self, level, inst, year=None, name=None):
        return m.EducationRecord(level, inst, name or f'School {inst}', year)

    def test_same_institution_level_and_year_is_classmate(self):
        r = m.match_records([self.rec(m.O_LEVEL, 1, 2004)], [self.rec(m.O_LEVEL, 1, 2004)])
        self.assertEqual(r.best.reason_code, m.CLASSMATE)
        self.assertEqual(r.best.education_level, m.O_LEVEL)
        self.assertEqual(r.best.cohort_year, 2004)

    def test_same_o_level_different_year(self):
        r = m.match_records([self.rec(m.O_LEVEL, 1, 2004)], [self.rec(m.O_LEVEL, 1, 2007)])
        self.assertEqual(r.best.reason_code, m.SAME_O_LEVEL)
        self.assertEqual(r.best.cohort_year, 2007)   # the other person's year

    def test_same_a_level(self):
        r = m.match_records([self.rec(m.A_LEVEL, 5, 2010)], [self.rec(m.A_LEVEL, 5, 2012)])
        self.assertEqual(r.best.reason_code, m.SAME_A_LEVEL)

    def test_same_primary(self):
        r = m.match_records([self.rec(m.PRIMARY, 9, 1998)], [self.rec(m.PRIMARY, 9, None)])
        self.assertEqual(r.best.reason_code, m.SAME_PRIMARY)

    def test_same_university(self):
        r = m.match_records([self.rec(m.UNIVERSITY, 7, 2015)], [self.rec(m.UNIVERSITY, 7, 2018)])
        self.assertEqual(r.best.reason_code, m.SAME_UNIVERSITY)

    def test_same_school_id_under_different_levels_is_same_school(self):
        r = m.match_records([self.rec(m.O_LEVEL, 3, 2004)], [self.rec(m.A_LEVEL, 3, 2006)])
        self.assertEqual(r.best.reason_code, m.SAME_SCHOOL)
        self.assertIsNone(r.best.cohort_year)

    def test_different_institution_is_no_match(self):
        self.assertIsNone(m.match_records([self.rec(m.O_LEVEL, 1, 2004)], [self.rec(m.O_LEVEL, 2, 2004)]))

    def test_missing_years_never_make_a_classmate(self):
        r = m.match_records([self.rec(m.O_LEVEL, 1, None)], [self.rec(m.O_LEVEL, 1, None)])
        self.assertEqual(r.best.reason_code, m.SAME_O_LEVEL)

    def test_missing_year_on_either_side_still_matches_the_school_at_that_level(self):
        # Incomplete data must never make a real same-school match vanish:
        # it degrades from CLASSMATE to the level-specific reason instead.
        with_year, no_year = self.rec(m.O_LEVEL, 1, 2004), self.rec(m.O_LEVEL, 1, None)
        for mine, theirs in ((with_year, no_year), (no_year, with_year), (no_year, no_year)):
            r = m.match_records([mine], [theirs])
            self.assertEqual(r.best.reason_code, m.SAME_O_LEVEL)
            self.assertEqual(r.best.institution_id, 1)

    def test_classmate_beats_every_other_reason(self):
        mine = [self.rec(m.PRIMARY, 1, 1998), self.rec(m.O_LEVEL, 2, 2004)]
        theirs = [self.rec(m.PRIMARY, 1, 2000), self.rec(m.O_LEVEL, 2, 2004)]
        r = m.match_records(mine, theirs)
        self.assertEqual(r.best.reason_code, m.CLASSMATE)
        self.assertEqual(r.best.education_level, m.O_LEVEL)
        self.assertEqual(len(r.all_matches), 2)   # every match is preserved

    def test_spec_order_primary_before_o_level_before_a_level_before_university(self):
        mine = [self.rec(m.UNIVERSITY, 4, 2015), self.rec(m.A_LEVEL, 3, 2010),
                self.rec(m.O_LEVEL, 2, 2006), self.rec(m.PRIMARY, 1, 2000)]
        theirs = [self.rec(m.UNIVERSITY, 4, 2016), self.rec(m.A_LEVEL, 3, 2011),
                  self.rec(m.O_LEVEL, 2, 2007), self.rec(m.PRIMARY, 1, 2001)]
        order = [x.reason_code for x in m.match_records(mine, theirs).all_matches]
        self.assertEqual(order, [m.SAME_PRIMARY, m.SAME_O_LEVEL, m.SAME_A_LEVEL, m.SAME_UNIVERSITY])

    def test_as_dict_is_structured_not_a_string(self):
        d = m.match_records([self.rec(m.O_LEVEL, 1, 2004, 'Arusha Secondary')],
                            [self.rec(m.O_LEVEL, 1, 2004)]).best.as_dict()
        self.assertEqual(d, {
            'reason_code': 'CLASSMATE', 'display_label': 'Classmate', 'institution_id': 1,
            'institution_name': 'Arusha Secondary', 'education_level': 'O_LEVEL', 'cohort_year': 2004,
        })


@FAST_HASH
class UserMatchingUsesInstitutionIdsNotNames(TestCase):
    def test_two_schools_with_identical_names_do_not_match(self):
        a = school('Same Name Secondary')
        b = School.objects.create(name='Same Name Secondary', slug='same-name-secondary-2',
                                  school_type='secondary')     # different row, same typed name
        self.assertNotEqual(a.id, b.id)
        u1 = person('+255711000001', secondary_school=a, secondary_completion_year=2004)
        u2 = person('+255711000002', secondary_school=b, secondary_completion_year=2004)
        self.assertIsNone(m.match_users(u1, u2))

    def test_users_at_the_same_school_row_match(self):
        s = school('Arusha Secondary')
        u1 = person('+255711000003', secondary_school=s, secondary_completion_year=2004)
        u2 = person('+255711000004', secondary_school=s, secondary_completion_year=2004)
        result = m.match_users(u1, u2)
        self.assertEqual(result.best.reason_code, m.CLASSMATE)
        self.assertEqual(result.best.institution_id, s.id)

    def test_user_without_education_has_no_records_and_no_fallback(self):
        u = person('+255711000005')
        self.assertEqual(m.education_records(u), [])
        self.assertIsNone(m.fallback_record(u))

    def test_fallback_is_the_persons_most_recent_education(self):
        prim, uni = school('Primary X', 'primary'), school('Uni X', 'university')
        u = person('+255711000006', primary_school=prim, primary_completion_year=1998,
                   tertiary_school=uni, tertiary_completion_year=2015)
        self.assertEqual(m.fallback_record(u).level, m.UNIVERSITY)
