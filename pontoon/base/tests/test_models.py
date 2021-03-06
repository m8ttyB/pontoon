import os.path

from django_nose.tools import assert_equal, assert_false, assert_raises, assert_true
from django.test.utils import override_settings

from mock import call, Mock, patch

from pontoon.base.models import Repository, Translation, User
from pontoon.base.tests import (
    assert_attributes_equal,
    IdenticalTranslationFactory,
    LocaleFactory,
    ProjectFactory,
    RepositoryFactory,
    TranslationFactory,
    UserFactory,
    TestCase
)
from pontoon.base.utils import aware_datetime


class ProjectTests(TestCase):
    def test_can_commit_no_repos(self):
        """can_commit should be False if there are no repos."""
        project = ProjectFactory.create(repositories=[])
        assert_false(project.can_commit)

    def test_can_commit_false(self):
        """
        can_commit should be False if there are no repo that can be
        committed to.
        """
        repo = RepositoryFactory.build(type=Repository.FILE)
        project = ProjectFactory.create(repositories=[repo])
        assert_false(project.can_commit)

    def test_can_commit_true(self):
        """
        can_commit should be True if there is a repo that can be
        committed to.
        """
        repo = RepositoryFactory.build(type=Repository.GIT)
        project = ProjectFactory.create(repositories=[repo])
        assert_true(project.can_commit)

    # We only test type here because the other compatibility methods are
    # basically the same, and they're meant to be removed in the future
    # anyway.

    def test_repository_type_no_repo(self):
        """If a project has no repos, repository_type should be None."""
        project = ProjectFactory.create(repositories=[])
        assert_equal(project.repository_type, None)

    def test_repository_type_first(self):
        """
        If a project has repos, return the type of the repo created
        first.
        """
        project = ProjectFactory.create(repositories=[])
        RepositoryFactory.create(project=project, type=Repository.GIT)
        RepositoryFactory.create(project=project, type=Repository.HG)
        assert_equal(project.repository_type, Repository.GIT)

    def test_repository_for_path_none(self):
        """
        If the project has no matching repositories, raise a ValueError.
        """
        project = ProjectFactory.create(repositories=[])
        with assert_raises(ValueError):
            project.repository_for_path('doesnt/exist')

    def test_repository_for_path(self):
        """
        Return the first repo found with a checkout path that contains
        the given path.
        """
        repo1, repo2, repo3 = RepositoryFactory.build_batch(3)
        project = ProjectFactory.create(repositories=[repo1, repo2, repo3])
        path = os.path.join(repo2.checkout_path, 'foo', 'bar')
        assert_equal(project.repository_for_path(path), repo2)


class RepositoryTests(TestCase):
    def test_checkout_path(self):
        """checkout_path should be determined by the repo URL."""
        repo = RepositoryFactory.create(
            url='https://example.com/path/to/locale/',
            project__slug='test-project'
        )
        with self.settings(MEDIA_ROOT='/media/root'):
            assert_equal(
                repo.checkout_path,
                '/media/root/projects/test-project/path/to/locale'
            )

    def test_checkout_path_multi_locale(self):
        """
        The checkout_path for multi-locale repos should not include the
        locale_code variable.
        """
        repo = RepositoryFactory.create(
            url='https://example.com/path/to/{locale_code}/',
            project__slug='test-project',
            multi_locale=True
        )
        with self.settings(MEDIA_ROOT='/media/root'):
            assert_equal(
                repo.checkout_path,
                '/media/root/projects/test-project/path/to'
            )

    def test_checkout_path_source_repo(self):
        """
        The checkout_path for a source repo should end with an en-US
        directory.
        """
        repo = RepositoryFactory.create(
            url='https://example.com/path/to/locale/',
            project__slug='test-project',
            source_repo=True
        )
        with self.settings(MEDIA_ROOT='/media/root'):
            assert_equal(
                repo.checkout_path,
                '/media/root/projects/test-project/path/to/locale/en-US'
            )

    def test_locale_checkout_path(self):
        """Append the locale code the the project's checkout_path."""
        repo = RepositoryFactory.create(
            url='https://example.com/path/',
            project__slug='test-project',
            multi_locale=True
        )
        locale = LocaleFactory.create(code='test-locale')

        with self.settings(MEDIA_ROOT='/media/root'):
            assert_equal(
                repo.locale_checkout_path(locale),
                '/media/root/projects/test-project/path/test-locale'
            )

    def test_locale_checkout_path_non_multi_locale(self):
        """If the repo isn't multi-locale, throw a ValueError."""
        repo = RepositoryFactory.create(multi_locale=False)
        locale = LocaleFactory.create()
        with assert_raises(ValueError):
            repo.locale_checkout_path(locale)

    def test_locale_url(self):
        """Fill in the {locale_code} variable in the URL."""
        repo = RepositoryFactory.create(
            url='https://example.com/path/to/{locale_code}/',
            multi_locale=True
        )
        locale = LocaleFactory.create(code='test-locale')

        assert_equal(repo.locale_url(locale), 'https://example.com/path/to/test-locale/')

    def test_locale_url_non_multi_locale(self):
        """If the repo isn't multi-locale, throw a ValueError."""
        repo = RepositoryFactory.create(multi_locale=False)
        locale = LocaleFactory.create()
        with assert_raises(ValueError):
            repo.locale_url(locale)

    def test_url_for_path(self):
        """
        Return the first locale_checkout_path for locales active for the
        repo's project that matches the given path.
        """
        matching_locale = LocaleFactory.create(code='match')
        non_matching_locale = LocaleFactory.create(code='nomatch')
        repo = RepositoryFactory.create(
            project__locales=[matching_locale, non_matching_locale],
            project__slug='test-project',
            url='https://example.com/path/to/{locale_code}/',
            multi_locale=True
        )

        with self.settings(MEDIA_ROOT='/media/root'):
            test_path = '/media/root/projects/test-project/path/to/match/foo/bar.po'
            assert_equal(repo.url_for_path(test_path), 'https://example.com/path/to/match/')

    def test_url_for_path_no_match(self):
        """
        If no active locale matches the given path, raise a ValueError.
        """
        repo = RepositoryFactory.create(
            project__locales=[],
            url='https://example.com/path/to/{locale_code}/',
            multi_locale=True
        )

        with assert_raises(ValueError):
            repo.url_for_path('/media/root/path/to/match/foo/bar.po')

    def test_pull(self):
        repo = RepositoryFactory.create(type=Repository.GIT, url='https://example.com')
        with patch('pontoon.base.models.update_from_vcs') as update_from_vcs:
            repo.pull()
            update_from_vcs.assert_called_with(
                Repository.GIT,
                'https://example.com',
                repo.checkout_path
            )

    def test_pull_multi_locale(self):
        """
        If the repo is multi-locale, pull all of the repos for the
        active locales.
        """
        locale1 = LocaleFactory.create(code='locale1')
        locale2 = LocaleFactory.create(code='locale2')
        repo = RepositoryFactory.create(
            type=Repository.GIT,
            url='https://example.com/{locale_code}/',
            multi_locale=True,
            project__locales=[locale1, locale2]
        )

        repo.locale_url = lambda locale: 'https://example.com/' + locale.code
        repo.locale_checkout_path = lambda locale: '/media/' + locale.code

        with patch('pontoon.base.models.update_from_vcs') as update_from_vcs:
            repo.pull()
            update_from_vcs.assert_has_calls([
                call(Repository.GIT, 'https://example.com/locale1', '/media/locale1'),
                call(Repository.GIT, 'https://example.com/locale2', '/media/locale2')
            ])

    def test_commit(self):
        repo = RepositoryFactory.create(type=Repository.GIT, url='https://example.com')
        with patch('pontoon.base.models.commit_to_vcs') as commit_to_vcs:
            repo.commit('message', 'author', 'path')
            commit_to_vcs.assert_called_with(
                Repository.GIT,
                'path',
                'message',
                'author',
                'https://example.com',
            )

    def test_commit_multi_locale(self):
        """
        If the repo is multi-locale, use the url from url_for_path for
        committing.
        """
        repo = RepositoryFactory.create(
            type=Repository.GIT,
            url='https://example.com/{locale_code}/',
            multi_locale=True
        )

        repo.url_for_path = Mock(return_value='https://example.com/for_path')
        with patch('pontoon.base.models.commit_to_vcs') as commit_to_vcs:
            repo.commit('message', 'author', 'path')
            commit_to_vcs.assert_called_with(
                Repository.GIT,
                'path',
                'message',
                'author',
                'https://example.com/for_path',
            )
            repo.url_for_path.assert_called_with('path')


class TranslationQuerySetTests(TestCase):
    def setUp(self):
        self.user0, self.user1 = UserFactory.create_batch(2)

    def _translation(self, user, submitted, approved):
        return TranslationFactory.create(
            date=aware_datetime(*submitted),
            user=user,
            approved_date=aware_datetime(*approved) if approved else None,
            approved_user=user
        )

    def test_latest_activity_translated(self):
        """
        If latest activity in Translation QuerySet is translation submission,
        return submission date and user.
        """
        latest_submission = self._translation(self.user0, submitted=(1970, 1, 3), approved=None)
        latest_approval = self._translation(self.user1, submitted=(1970, 1, 1), approved=(1970, 1, 2))
        assert_equal(Translation.objects.all().latest_activity(), {
            'date': latest_submission.date,
            'user': latest_submission.user
        })

    def test_latest_activity_approved(self):
        """
        If latest activity in Translation QuerySet is translation approval,
        return approval date and user.
        """
        latest_submission = self._translation(self.user0, submitted=(1970, 1, 2), approved=(1970, 1, 2))
        latest_approval = self._translation(self.user1, submitted=(1970, 1, 1), approved=(1970, 1, 3))
        assert_equal(Translation.objects.all().latest_activity(), {
            'date': latest_approval.date,
            'user': latest_approval.user
        })

    def test_latest_activity_none(self):
        """If empty Translation QuerySet, return None."""
        assert_equal(Translation.objects.none().latest_activity(), None)


class UserTranslationManagerTests(TestCase):
    @override_settings(EXCLUDE=('excluded@example.com',))
    def test_excluded_contributors(self):
        """
        Checks if contributors with mails in settings.EXCLUDE are excluded
        from top contributors list.
        """
        included_contributor = TranslationFactory.create(user__email='included@example.com').user
        excluded_contributor = TranslationFactory.create(user__email='excluded@example.com').user

        top_contributors = User.translators.with_translation_counts()
        assert_true(included_contributor in top_contributors)
        assert_true(excluded_contributor not in top_contributors)

    def test_users_without_translations(self):
        """
        Checks if user contributors without translations aren't returned.
        """
        active_contributor = TranslationFactory.create(user__email='active@example.com').user
        inactive_contributor = UserFactory.create(email='inactive@example.com')

        top_contributors = User.translators.with_translation_counts()
        assert_true(active_contributor in top_contributors)
        assert_true(inactive_contributor not in top_contributors)

    def test_unique_translations(self):
        """
        Checks if contributors with identical translations are returned.
        """

        unique_translator = TranslationFactory.create().user
        identical_translator = IdenticalTranslationFactory.create().user
        top_contributors = User.translators.with_translation_counts()

        assert_true(unique_translator in top_contributors)
        assert_true(identical_translator not in top_contributors)


    def test_contributors_order(self):
        """
        Checks if users are ordered by count of contributions.
        """
        contributors = [
            self.create_contributor_with_translation_counts(2),
            self.create_contributor_with_translation_counts(4),
            self.create_contributor_with_translation_counts(9),
            self.create_contributor_with_translation_counts(1),
            self.create_contributor_with_translation_counts(6),
        ]

        assert_equal(list(User.translators.with_translation_counts()), [
            contributors[2],
            contributors[4],
            contributors[1],
            contributors[0],
            contributors[3]])

    def test_contributors_limit(self):
        """
        Checks if proper count of user is returned.
        """
        TranslationFactory.create_batch(110)

        top_contributors = User.translators.with_translation_counts()

        assert_equal(top_contributors.count(), 100)

    def create_contributor_with_translation_counts(self, approved=0, unapproved=0, needs_work=0, **kwargs):
        """
        Helper method, creates contributor with given translations counts.
        """
        contributor = UserFactory.create()
        TranslationFactory.create_batch(approved, user=contributor, approved=True, **kwargs)
        TranslationFactory.create_batch(unapproved, user=contributor, approved=False, fuzzy=False, **kwargs)
        TranslationFactory.create_batch(needs_work, user=contributor, fuzzy=True, **kwargs)
        return contributor

    def test_translation_counts(self):
        """
        Checks if translation counts are calculated properly.
        Tests creates 3 contributors with different numbers translations and checks if their counts match.
        """

        first_contributor = self.create_contributor_with_translation_counts(approved=7, unapproved=3, needs_work=2)
        second_contributor = self.create_contributor_with_translation_counts(approved=5, unapproved=9, needs_work=2)
        third_contributor = self.create_contributor_with_translation_counts(approved=1, unapproved=2, needs_work=5)

        top_contributors = User.translators.with_translation_counts()
        assert_equal(top_contributors.count(), 3)

        assert_equal(top_contributors[0], second_contributor)
        assert_equal(top_contributors[1], first_contributor)
        assert_equal(top_contributors[2], third_contributor)

        assert_attributes_equal(top_contributors[0], translations_count=16,
            translations_approved_count=5, translations_unapproved_count=9,
            translations_needs_work_count=2)
        assert_attributes_equal(top_contributors[1], translations_count=12,
            translations_approved_count=7, translations_unapproved_count=3,
            translations_needs_work_count=2)
        assert_attributes_equal(top_contributors[2], translations_count=8,
            translations_approved_count=1, translations_unapproved_count=2,
            translations_needs_work_count=5)

    def test_period_filters(self):
        """
        Total counts should be filtered by given date.
        Test creates 2 contributors with different activity periods and checks if they are filtered properly.
        """

        first_contributor = self.create_contributor_with_translation_counts(approved=12, unapproved=1, needs_work=2,
            date=aware_datetime(2015, 3, 2))
        second_contributor = self.create_contributor_with_translation_counts(approved=2, unapproved=11, needs_work=2,
            date=aware_datetime(2015, 6, 1))

        TranslationFactory.create_batch(5, approved=True, user=first_contributor, date=aware_datetime(2015, 7, 2))

        top_contributors = User.translators.with_translation_counts(aware_datetime(2015, 6, 10))

        assert_equal(top_contributors.count(), 1)
        assert_attributes_equal(top_contributors[0], translations_count=5,
            translations_approved_count=5, translations_unapproved_count=0,
            translations_needs_work_count=0)

        top_contributors = User.translators.with_translation_counts(aware_datetime(2015, 5, 10))

        assert_equal(top_contributors.count(), 2)
        assert_attributes_equal(top_contributors[0], translations_count=15,
            translations_approved_count=2, translations_unapproved_count=11,
            translations_needs_work_count=2)
        assert_attributes_equal(top_contributors[1], translations_count=5,
            translations_approved_count=5, translations_unapproved_count=0,
            translations_needs_work_count=0)

        top_contributors = User.translators.with_translation_counts(aware_datetime(2015, 1, 10))

        assert_equal(top_contributors.count(), 2)
        assert_attributes_equal(top_contributors[0], translations_count=20,
            translations_approved_count=17, translations_unapproved_count=1,
            translations_needs_work_count=2)
        assert_attributes_equal(top_contributors[1], translations_count=15,
            translations_approved_count=2, translations_unapproved_count=11,
            translations_needs_work_count=2)
