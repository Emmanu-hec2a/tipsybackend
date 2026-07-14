from django.core.management.base import BaseCommand
from urbanfoods.models import Store
from datetime import date
import requests
from django.conf import settings

def send_telegram(chat_id, message):
    if not chat_id:
        return
    token = settings.TELEGRAM_BOTT_TOKEN
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending telegram: {e}")

class Command(BaseCommand):
    help = 'Check store subscription expiry and send reminders'

    def handle(self, *args, **options):
        self.stdout.write("Checking subscription expiries...")
        for store in Store.objects.filter(is_active=True):
            if not store.subscription_expires:
                continue
                
            days_left = (store.subscription_expires - date.today()).days
            
            if days_left == 5 and store.last_expiry_reminder_sent != date.today():
                send_telegram(store.telegram_chat_id,
                    f"⚠️ *Subscription Reminder*\nYour subscription for *{store.name}* expires in 5 days. Renew now: {settings.SITE_URL}/merchant/billing/")
                store.last_expiry_reminder_sent = date.today()
                store.save()
                self.stdout.write(self.style.SUCCESS(f"Sent 5-day reminder to {store.name}"))
                
            if days_left <= 0 and store.billing_status != 'suspended':
                store.billing_status = 'suspended'
                store.is_active = False # Deactivate store visibility
                store.save()
                send_telegram(store.telegram_chat_id,
                    f"🔒 *Subscription Expired*\nSubscription for *{store.name}* has expired. Your store is now paused and hidden from customers. Renew to reactivate.")
                self.stdout.write(self.style.WARNING(f"Suspended and Deactivated {store.name} due to expiry"))
        
        self.stdout.write(self.style.SUCCESS("Finished checking expiries."))
