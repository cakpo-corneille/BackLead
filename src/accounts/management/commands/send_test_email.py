from django.core.management.base import BaseCommand, CommandError
from django.conf import settings
from django.contrib.auth import get_user_model
from accounts.utils import send_email_code_async_or_sync

class Command(BaseCommand):
    help = 'Sends a confirmation email to the superuser to verify email settings during deployment.'

    def handle(self, *args, **options):
        """
        Handles the execution of the management command.
        """
        User = get_user_model()

        # Only run this check if a real email provider is configured
        if getattr(settings, 'EMAIL_PROVIDER', 'console').lower() == 'console':
            self.stdout.write(self.style.SUCCESS("EMAIL_PROVIDER is 'console', skipping test email."))
            return

        self.stdout.write("--- Verifying Email Service --- ")

        # --- 1. Find the Superuser ---
        try:
            # Get the most recently created superuser
            superuser = User.objects.filter(is_superuser=True).latest('date_joined')
        except User.DoesNotExist:
            raise CommandError("Deployment Error: Superuser has not been created yet. Cannot send test email.")

        if not superuser.email:
            # Corrected: Use email for the error message as well
            raise CommandError(f"Deployment Error: Superuser found, but they do not have an email address.")

        # --- 2. Send the Email ---
        try:
            self.stdout.write(f"Sending confirmation email to {superuser.email}...")
            send_email_code_async_or_sync(superuser)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f'[FATAL] Failed to send email: {e}'))
            raise CommandError(
                "Deployment halted. The email service is not configured correctly. "
                "Please check your EMAIL_PROVIDER, EMAIL_API_KEY, and other related environment variables."
            )

        self.stdout.write(self.style.SUCCESS('--- Email Service Verified Successfully ---'))
