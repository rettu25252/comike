import os

from django.contrib.auth import get_user_model


class OwnerBootstrapBackend:
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username != os.getenv('DJANGO_SUPERUSER_USERNAME', 'owner'):
            return None

        expected_password = (
            os.getenv('DJANGO_SUPERUSER_PASSWORD')
            or os.getenv('SHOPPING_ADMIN_PASSWORD')
            or 'ishirettu25252'
        )
        if password != expected_password:
            return None

        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=username,
            defaults={
                'email': os.getenv('DJANGO_SUPERUSER_EMAIL', 'owner@example.com'),
                'is_staff': True,
                'is_superuser': True,
            },
        )

        changed = created
        if not user.is_staff:
            user.is_staff = True
            changed = True
        if not user.is_superuser:
            user.is_superuser = True
            changed = True
        if created or not user.check_password(expected_password):
            user.set_password(expected_password)
            changed = True
        if changed:
            user.save()

        return user

    def get_user(self, user_id):
        user_model = get_user_model()
        try:
            return user_model.objects.get(pk=user_id)
        except user_model.DoesNotExist:
            return None
