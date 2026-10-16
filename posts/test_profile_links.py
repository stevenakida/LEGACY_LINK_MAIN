"""Names and avatars on Home and in the feed open the person's profile, and
the "liked by" line is built on the server so its names can be linked."""
import html
import json
import re

from django.test import TestCase, override_settings
from django.urls import reverse

from connections.models import UserRelationshipOverride

from .models import Post, PostComment, PostLike
from .tests import connect, make_school, make_user
from .views import like_summary, recent_likers


def profile_href(user):
    return 'href="%s"' % reverse('view_profile', args=[user.id])


def summary_for(page, post):
    """The data-summary JSON the page hands the script for one post."""
    body = page.content.decode()
    article = body[body.index('id="feed-post-%s"' % post.id):]
    attr = re.search(r'data-summary="([^"]*)"', article).group(1)
    return json.loads(html.unescape(attr))


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class FeedProfileLinkTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700500001', 'Alice Viewer')
        self.bob = make_user('+255700500002', 'Bob Author')
        self.carol = make_user('+255700500003', 'Carol Liker')
        connect(self.alice, self.bob)
        connect(self.alice, self.carol)
        self.bob_post = Post.objects.create(author=self.bob, body='hello from bob')
        self.own_post = Post.objects.create(author=self.alice, body='hello from me')
        self.client.force_login(self.alice)

    def home(self):
        return self.client.get(reverse('dashboard'))

    def test_another_persons_name_and_avatar_both_link_to_their_profile(self):
        body = self.home().content.decode()
        self.assertGreaterEqual(body.count(profile_href(self.bob)), 2)      # avatar + name
        self.assertIn('<a %s class="profile-link"><strong>Bob Author</strong></a>' % profile_href(self.bob), body)

    def test_your_own_posts_link_to_your_own_profile_page(self):
        body = self.home().content.decode()
        self.assertIn('<a href="%s" class="profile-link"><strong>Alice Viewer</strong></a>' % reverse('profile'), body)
        self.assertNotIn(profile_href(self.alice), body)                    # no needless redirect hop

    def test_the_original_author_inside_a_repost_links_to_their_profile(self):
        original = Post.objects.create(author=self.bob, body='public news', audience=Post.Audience.PUBLIC)
        Post.objects.create(author=self.carol, body='', reposted_from=original, is_repost=True,
                            audience=Post.Audience.PUBLIC)
        body = self.home().content.decode()
        embed = body[body.index('feed-repost-embed-head'):]
        self.assertIn('<a %s class="profile-link"><strong>Bob Author</strong></a>' % profile_href(self.bob), embed)

    def test_suggested_people_link_to_their_profile(self):
        school = make_school('Arusha')
        alice = self.alice
        alice.secondary_school, alice.secondary_completion_year = school, 2004
        alice.save()
        dave = make_user('+255700500004', 'Dave Classmate', secondary_school=school, secondary_completion_year=2004)
        body = self.home().content.decode()
        card = body[body.index('suggested-card'):]
        self.assertIn('<a %s class="profile-link"><strong>Dave Classmate</strong></a>' % profile_href(dave), card)

    def test_the_comment_json_carries_the_author_id_the_page_links_with(self):
        PostComment.objects.create(post=self.bob_post, author=self.carol, body='nice')
        data = self.client.get(reverse('list_post_comments', args=[self.bob_post.id])).json()
        self.assertEqual(data['comments'][0]['author_id'], str(self.carol.id))


@override_settings(MEDIA_ASSETS_S3_ENABLED=False)
class LikedByLineTests(TestCase):
    def setUp(self):
        self.alice = make_user('+255700500011', 'Alice Viewer')
        self.bob = make_user('+255700500012', 'Bob Author')
        self.carol = make_user('+255700500013', 'Carol Liker')
        self.dave = make_user('+255700500014', 'Dave Liker')
        for other in (self.bob, self.carol, self.dave):
            connect(self.alice, other)
        self.post = Post.objects.create(author=self.bob, body='hello')
        self.client.force_login(self.alice)

    def like(self, user):
        return PostLike.objects.create(post=self.post, user=user)

    def test_the_page_names_the_newest_likers_with_their_ids_on_first_load(self):
        self.like(self.carol)
        self.like(self.dave)
        summary = summary_for(self.client.get(reverse('dashboard')), self.post)
        self.assertEqual(summary['parts'], [
            {'id': str(self.dave.id), 'name': 'Dave Liker'},
            {'id': str(self.carol.id), 'name': 'Carol Liker'},
        ])
        self.assertEqual(summary['others'], 0)

    def test_you_come_first_and_the_rest_are_counted(self):
        self.like(self.alice)
        self.like(self.carol)
        self.like(self.dave)
        self.like(self.bob)
        summary = summary_for(self.client.get(reverse('dashboard')), self.post)
        self.assertEqual(summary['parts'][0], {'name': 'You'})
        self.assertEqual(len(summary['parts']), 2)
        self.assertEqual(summary['others'], 2)

    def test_tapping_like_returns_the_same_structured_line(self):
        self.like(self.carol)
        data = self.client.post(reverse('toggle_post_like', args=[self.post.id])).json()
        self.assertTrue(data['liked'])
        self.assertEqual(data['summary'], {
            'parts': [{'name': 'You'}, {'id': str(self.carol.id), 'name': 'Carol Liker'}],
            'others': 0,
        })
        self.assertEqual(data['sample_names'], ['Carol Liker'])             # still sent for older clients

    def test_unliking_the_only_like_clears_the_line(self):
        self.like(self.alice)
        data = self.client.post(reverse('toggle_post_like', args=[self.post.id])).json()
        self.assertEqual((data['liked'], data['count'], data['summary']), (False, 0, {'parts': [], 'others': 0}))

    def test_people_you_blocked_are_not_named_but_still_counted(self):
        self.like(self.carol)
        UserRelationshipOverride.objects.create(
            actor=self.alice, target=self.carol, type=UserRelationshipOverride.Type.BLOCK)
        summary = summary_for(self.client.get(reverse('dashboard')), self.post)
        self.assertEqual(summary, {'parts': [], 'others': 1})

    def test_deactivated_accounts_are_not_named(self):
        self.like(self.carol)
        self.carol.is_active = False
        self.carol.save()
        self.assertEqual(recent_likers([self.post.id], self.alice), {})

    def test_a_name_with_html_cannot_break_out_of_the_attribute(self):
        evil = make_user('+255700500015', '<script>alert(1)</script> "Q"')
        connect(self.alice, evil)
        self.like(evil)
        page = self.client.get(reverse('dashboard'))
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertEqual(summary_for(page, self.post)['parts'][0]['name'], '<script>alert(1)</script> "Q"')


class LikeSummaryUnitTests(TestCase):
    def test_no_likes_is_empty(self):
        self.assertEqual(like_summary(False, 0, []), {'parts': [], 'others': 0})

    def test_only_you(self):
        self.assertEqual(like_summary(True, 1, []), {'parts': [{'name': 'You'}], 'others': 0})

    def test_two_named_people_when_you_have_not_liked(self):
        likers = [{'id': '1', 'name': 'A'}, {'id': '2', 'name': 'B'}, {'id': '3', 'name': 'C'}]
        self.assertEqual(like_summary(False, 5, likers), {'parts': likers[:2], 'others': 3})

    def test_one_named_person_after_you(self):
        likers = [{'id': '1', 'name': 'A'}, {'id': '2', 'name': 'B'}]
        self.assertEqual(like_summary(True, 4, likers), {'parts': [{'name': 'You'}, likers[0]], 'others': 2})
