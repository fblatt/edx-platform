"""
Django ORM model specifications for the User API application
"""
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import RegexValidator
from django.db import models
from django.db.models.signals import post_delete, post_save, pre_save
from django.forms.models import model_to_dict
from django.dispatch import receiver
from model_utils.models import TimeStampedModel
from opaque_keys.edx.django.models import CourseKeyField

# Currently, the "student" app is responsible for
# accounts, profiles, enrollments, and the student dashboard.
# We are trying to move some of this functionality into separate apps,
# but currently the rest of the system assumes that "student" defines
# certain models.  For now we will leave the models in "student" and
# create an alias in "user_api".
from student.models import PendingEmailChange, Registration, UserProfile  # pylint: disable=unused-import
from util.model_utils import emit_setting_changed_event, get_changed_fields_dict


class RetirementStateError(Exception):
    pass


class UserPreference(models.Model):
    """A user's preference, stored as generic text to be processed by client"""
    KEY_REGEX = r"[-_a-zA-Z0-9]+"
    user = models.ForeignKey(User, db_index=True, related_name="preferences")
    key = models.CharField(max_length=255, db_index=True, validators=[RegexValidator(KEY_REGEX)])
    value = models.TextField()

    class Meta(object):
        unique_together = ("user", "key")

    @staticmethod
    def get_all_preferences(user):
        """
        Gets all preferences for a given user

        Returns: Set of (preference type, value) pairs for each of the user's preferences
        """
        return dict([(pref.key, pref.value) for pref in user.preferences.all()])

    @classmethod
    def get_value(cls, user, preference_key, default=None):
        """Gets the user preference value for a given key.

        Note:
            This method provides no authorization of access to the user preference.
            Consider using user_api.preferences.api.get_user_preference instead if
            this is part of a REST API request.

        Arguments:
            user (User): The user whose preference should be set.
            preference_key (str): The key for the user preference.
            default: The object to return if user does not have preference key set

        Returns:
            The user preference value, or default if one is not set.
        """
        try:
            user_preference = cls.objects.get(user=user, key=preference_key)
            return user_preference.value
        except cls.DoesNotExist:
            return default


@receiver(pre_save, sender=UserPreference)
def pre_save_callback(sender, **kwargs):
    """
    Event changes to user preferences.
    """
    user_preference = kwargs["instance"]
    user_preference._old_value = get_changed_fields_dict(user_preference, sender).get("value", None)


@receiver(post_save, sender=UserPreference)
def post_save_callback(sender, **kwargs):
    """
    Event changes to user preferences.
    """
    user_preference = kwargs["instance"]
    emit_setting_changed_event(
        user_preference.user, sender._meta.db_table, user_preference.key,
        user_preference._old_value, user_preference.value
    )
    user_preference._old_value = None


@receiver(post_delete, sender=UserPreference)
def post_delete_callback(sender, **kwargs):
    """
    Event changes to user preferences.
    """
    user_preference = kwargs["instance"]
    emit_setting_changed_event(
        user_preference.user, sender._meta.db_table, user_preference.key, user_preference.value, None
    )


class UserCourseTag(models.Model):
    """
    Per-course user tags, to be used by various things that want to store tags about
    the user.  Added initially to store assignment to experimental groups.
    """
    user = models.ForeignKey(User, db_index=True, related_name="+")
    key = models.CharField(max_length=255, db_index=True)
    course_id = CourseKeyField(max_length=255, db_index=True)
    value = models.TextField()

    class Meta(object):
        unique_together = ("user", "course_id", "key")


class UserOrgTag(TimeStampedModel):
    """
    Per-Organization user tags.

    Allows settings to be configured at an organization level.

    """
    user = models.ForeignKey(User, db_index=True, related_name="+")
    key = models.CharField(max_length=255, db_index=True)
    org = models.CharField(max_length=255, db_index=True)
    value = models.TextField()

    class Meta(object):
        unique_together = ("user", "org", "key")


class RetirementStatus(TimeStampedModel):
    """
    Tracks the progress of a user's retirement request
    """
    user = models.OneToOneField(User)
    username = models.CharField(max_length=150, db_index=True)
    email = models.EmailField(db_index=True)
    current_state = models.CharField(max_length=25, choices=settings.RETIREMENT_STATES)
    last_state = models.CharField(max_length=25, choices=settings.RETIREMENT_STATES, blank=True)
    responses = models.TextField()

    def _validate_state_update(self, new_state):
        """
        Confirm that the state move that's trying to be made is allowed
        """
        if self.current_state in settings.RETIREMENT_DEAD_END_STATES:
            raise RetirementStateError('RetirementStatus: Unable to move user from {}'.format(self.current_state))

        try:
            new_state_index = settings.RETIREMENT_STATES_FLAT.index(new_state)
            if new_state_index <= settings.RETIREMENT_STATES_FLAT.index(self.current_state):
                raise ValueError()
        except ValueError:
            err = '{} does not exist or is an eariler state than current state {}'.format(new_state, self.current_state)
            raise RetirementStateError(err)

    def _validate_update_data(self, data):
        """
        Confirm that the data passed in is properly formatted
        """
        required_keys = ('username', 'new_state', 'response')

        for required_key in required_keys:
            if required_key not in data:
                raise RetirementStateError('RetirementStatus: Required key {} missing from update'.format(required_key))

        for key in data:
            if key not in required_keys:
                raise RetirementStateError('RetirementStatus: Unknown key {} in update'.format(key))

    def update_state(self, update):
        """
        Perform the necessary checks for a state change and update the state and response if passed
        or throw a RetirementStateError with a useful error message
        """
        self._validate_update_data(update)
        self._validate_state_update(update['new_state'])

        old_state = self.current_state
        self.current_state = update['new_state']
        self.last_state = old_state
        self.responses += "\n Moved from {} to {}:\n{}\n".format(old_state, self.current_state, update['response'])
        self.save()

    def to_dict(self, all_fields=False):
        """
        Return a dict format of this model to a consistent format for serialization, removing the long text field
        `responses` for performance reasons.
        """
        retirement_dict = model_to_dict(self)
        retirement_dict['current_username'] = self.user.username
        retirement_dict['current_email'] = self.user.email

        if not all_fields:
            del retirement_dict['responses']

        return retirement_dict
