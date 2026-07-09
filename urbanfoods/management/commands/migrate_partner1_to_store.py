from django.core.management.base import BaseCommand
from django.db import transaction
from urbanfoods.models import User, Store, Order, FoodItem

class Command(BaseCommand):
    help = 'Migrates existing client data to the new Store model structure'

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, default='admin', help='Username of the existing client')

    def handle(self, *args, **options):
        username = options['username']
        try:
            client_user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User '{username}' not found."))
            return

        with transaction.atomic():
            # Create the initial store for Partner #1
            store, created = Store.objects.get_or_create(
                owner=client_user,
                defaults={
                    'name': "Tipsy Theoryy",
                    'subdomain': "tipsytheoryy",
                    'latitude': -1.286389, # Default Nairobi lat
                    'longitude': 36.817223, # Default Nairobi lng
                    'is_active': True,
                    'plan': 'base',
                    'subscription_active': True,
                }
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f"Created store '{store.name}' for user '{username}'."))
            else:
                self.stdout.write(self.style.WARNING(f"Store for user '{username}' already exists."))

            # Update user role
            client_user.role = User.Role.PARTNER
            client_user.is_approved = True
            # Per instructions: "CAREFUL — verify panel still works after this"
            # In SaaS, partners shouldn't need is_staff/is_superuser
            client_user.is_staff = False
            client_user.is_superuser = False
            client_user.save()
            self.stdout.write(self.style.SUCCESS(f"Updated user '{username}' role to 'partner' and removed staff/superuser status."))

            # Scoping existing data to the new store
            order_count = Order.objects.filter(store__isnull=True).update(store=store)
            item_count = FoodItem.objects.filter(store__isnull=True).update(store=store)

            self.stdout.write(self.style.SUCCESS(f"Linked {order_count} orders and {item_count} food items to store '{store.name}'."))
            self.stdout.write(self.style.SUCCESS("Migration complete."))
