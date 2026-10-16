"""Home's "Suggested for you" row uses Discover's own candidates, so a person
you are already connected with is never suggested again (CEO checklist item 6)."""
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from alumni.models import School
from connections.models import Connection, UserRelationshipOverride
from connections.services import home_suggestions

FAST_HASH = override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], MEDIA_ASSETS_S3_ENABLED=False)


def school(name, kind='secondary'):
    return School.objects.create(name=name, slug=f'{kind}-{name}'.lower().replace(' ', '-'), school_type=kind)


def person(n, name, **edu):
    return User.objects.create_user(phone_or_email=f'+25574460{n:04d}', password='x', full_name=name, **edu)


def suggested_section(response):
    """The part of Home that is the Suggested row (names elsewhere on the page,
    e.g. a feed, must not confuse these checks)."""
    body = response.content.decode()
    start = body.index('Suggested for you')
    end = body.index('Upcoming events', start)
    return body[start:end]


@FAST_HASH
class HomeSuggestionTests(TestCase):
    def setUp(self):
        self.arusha = school('Arusha')
        self.me = person(1, 'Viewer Me', secondary_school=self.arusha, secondary_completion_year=2004)
        self.classmate = person(2, 'Zed Classmate', secondary_school=self.arusha, secondary_completion_year=2004)
        self.schoolmate = person(3, 'Amy Schoolmate', secondary_school=self.arusha, secondary_completion_year=2006)
        self.client.force_login(self.me)

    def home(self):
        return suggested_section(self.client.get(reverse('dashboard')))

    def test_classmates_and_schoolmates_are_suggested_with_the_right_label(self):
        section = self.home()
        self.assertIn('Zed Classmate', section)
        self.assertIn('Amy Schoolmate', section)
        self.assertIn('Classmate', section[section.index('Zed Classmate'):][:600])
        self.assertIn('Schoolmate', section[section.index('Amy Schoolmate'):][:600])

    def test_classmates_come_before_schoolmates(self):
        section = self.home()
        self.assertLess(section.index('Zed Classmate'), section.index('Amy Schoolmate'))

    def test_you_are_never_suggested_to_yourself(self):
        self.assertNotIn('Viewer Me', self.home())

    def test_an_existing_connection_is_never_suggested(self):
        Connection.objects.create(requester=self.me, receiver=self.classmate, status='accepted')
        section = self.home()
        self.assertNotIn('Zed Classmate', section)
        self.assertIn('Amy Schoolmate', section)

    def test_a_connection_where_they_sent_the_request_is_never_suggested_either(self):
        Connection.objects.create(requester=self.classmate, receiver=self.me, status='accepted')
        self.assertNotIn('Zed Classmate', self.home())

    def test_someone_waiting_on_my_decision_is_not_suggested(self):
        Connection.objects.create(requester=self.classmate, receiver=self.me, status='pending')
        self.assertNotIn('Zed Classmate', self.home())

    def test_a_request_i_already_sent_shows_request_sent_and_no_connect_button(self):
        Connection.objects.create(requester=self.me, receiver=self.classmate, status='pending')
        section = self.home()
        card = section[section.index('Zed Classmate'):section.index('Amy Schoolmate')]
        self.assertIn('Request Sent', card)
        self.assertNotIn(reverse('send_connection_web', args=[self.classmate.id]), card)

    def test_declined_and_dismissed_people_are_not_suggested(self):
        Connection.objects.create(requester=self.me, receiver=self.classmate, status='declined')
        self.assertNotIn('Zed Classmate', self.home())

    def test_blocked_people_are_not_suggested_in_either_direction(self):
        UserRelationshipOverride.objects.create(
            actor=self.me, target=self.classmate, type=UserRelationshipOverride.Type.BLOCK)
        UserRelationshipOverride.objects.create(
            actor=self.schoolmate, target=self.me, type=UserRelationshipOverride.Type.BLOCK)
        section = self.home()
        self.assertNotIn('Zed Classmate', section)
        self.assertNotIn('Amy Schoolmate', section)

    def test_deactivated_accounts_are_not_suggested(self):
        self.classmate.is_active = False
        self.classmate.save()
        self.assertNotIn('Zed Classmate', self.home())

    def test_people_at_a_different_school_are_not_suggested(self):
        other = school('Elsewhere')
        person(4, 'Far Stranger', secondary_school=other, secondary_completion_year=2004)
        self.assertNotIn('Far Stranger', self.home())

    def test_cards_link_to_the_profile_and_connect_from_home(self):
        section = self.home()
        self.assertIn('href="%s"' % reverse('view_profile', args=[self.classmate.id]), section)
        self.assertIn('action="%s"' % reverse('send_connection_web', args=[self.classmate.id]), section)

    def test_connecting_from_home_then_accepting_removes_them_from_the_row(self):
        self.client.post(reverse('send_connection_web', args=[self.classmate.id]), {'next': reverse('dashboard')})
        self.assertIn('Request Sent', self.home())
        Connection.objects.filter(requester=self.me, receiver=self.classmate).update(status='accepted')
        self.assertNotIn('Zed Classmate', self.home())


@FAST_HASH
class HomeSuggestionEdgeCaseTests(TestCase):
    def test_someone_matching_at_two_levels_appears_once(self):
        primary, secondary = school('Njiro Hill', 'primary'), school('Arusha')
        me = person(10, 'Viewer Me', primary_school=primary, primary_completion_year=2000,
                    secondary_school=secondary, secondary_completion_year=2004)
        person(11, 'Twice Classmate', primary_school=primary, primary_completion_year=2000,
               secondary_school=secondary, secondary_completion_year=2004)
        picks, _ = home_suggestions(me)
        self.assertEqual([c.user.full_name for c in picks], ['Twice Classmate'])

    def test_at_most_six_are_suggested(self):
        arusha = school('Arusha')
        me = person(20, 'Viewer Me', secondary_school=arusha, secondary_completion_year=2004)
        for i in range(9):
            person(21 + i, f'Mate {i}', secondary_school=arusha, secondary_completion_year=2004)
        picks, has_education = home_suggestions(me)
        self.assertEqual((len(picks), has_education), (6, True))

    def test_someone_with_no_education_is_asked_to_add_it(self):
        me = person(40, 'Nobody Yet')
        self.client.force_login(me)
        section = suggested_section(self.client.get(reverse('dashboard')))
        self.assertIn('Complete your school and graduation year', section)

    def test_someone_with_education_but_no_one_new_is_told_so_instead(self):
        me = person(41, 'Lonely Me', secondary_school=school('Arusha'), secondary_completion_year=2004)
        self.client.force_login(me)
        section = suggested_section(self.client.get(reverse('dashboard')))
        self.assertIn('No new people to suggest right now', section)
        self.assertNotIn('Complete your school and graduation year', section)

    def test_the_service_returns_candidates_and_the_has_education_flag(self):
        me = person(42, 'Nobody Yet')
        self.assertEqual(home_suggestions(me), ([], False))
