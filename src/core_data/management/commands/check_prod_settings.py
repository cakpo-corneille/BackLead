import sys
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

class Command(BaseCommand):
    help = 'Checks if all necessary production environment variables are set before deployment.'

    # List of providers that require an API key and a from email.
    KEY_PROVIDERS = ['brevo', 'sendgrid', 'mailgun', 'smtp']

    def handle(self, *args, **options):
        """
        Handles the execution of the management command.
        """
        self.stdout.write("--- Running Production Settings Check ---")

        errors = []

        # -- Check 1: Email Configuration --
        email_provider = getattr(settings, 'EMAIL_PROVIDER', 'console').lower()
        if email_provider in self.KEY_PROVIDERS:
            self.stdout.write(f"EMAIL_PROVIDER is \'{email_provider}\'. Checking dependencies...")
            if not getattr(settings, 'EMAIL_API_KEY', None) and email_provider != 'smtp':
                errors.append('EMAIL_API_KEY is not set.')
            if not getattr(settings, 'DEFAULT_FROM_EMAIL', None):
                errors.append('DEFAULT_FROM_EMAIL is not set.')

        # You can add other checks here in the future.
        # Example: Check if SENTRY_DSN is set
        # if not getattr(settings, 'SENTRY_DSN', None):
        #     errors.append('SENTRY_DSN is not set for error tracking.')

        if errors:
            # Construct the final error message
            error_message = ( 
                "\\n[FATAL] Production settings check failed. The following variables are missing:\\n" + \
                "\\n".join([f"  - {error}" for error in errors]) + \
                "\\n\\nPlease set these environment variables in your deployment service and restart the deployment."
            )
            # CommandError is the standard way to signal a failed management command
            raise CommandError(error_message)

        self.stdout.write(self.style.SUCCESS("\\n--- All Production Settings Checks Passed ---"))
