"""
WSGI config for main project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings')


def bootstrap_admin_environment():
	if os.getenv('RUN_STARTUP_BOOTSTRAP', 'true').lower() != 'true':
		return

	import django
	from django.contrib.auth import get_user_model
	from django.core.management import call_command
	from django.db import OperationalError

	django.setup()

	try:
		call_command('migrate', interactive=False, verbosity=0)
	except OperationalError:
		# Another worker may be applying migrations at the same time.
		return

	username = os.getenv('DJANGO_SUPERUSER_USERNAME', 'owner')
	password = (
		os.getenv('DJANGO_SUPERUSER_PASSWORD')
		or os.getenv('SHOPPING_ADMIN_PASSWORD')
		or 'ishirettu25252'
	)
	email = os.getenv('DJANGO_SUPERUSER_EMAIL', 'owner@example.com')

	User = get_user_model()
	user, created = User.objects.get_or_create(
		username=username,
		defaults={
			'email': email,
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
	if created or not user.check_password(password):
		user.set_password(password)
		changed = True
	if changed:
		user.save()


bootstrap_admin_environment()

application = get_wsgi_application()
