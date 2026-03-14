import logging
import requests
from abc import ABC, abstractmethod
from django.conf import settings

logger = logging.getLogger(__name__)

class SMSBackend(ABC):
    @abstractmethod
    def send(self, phone: str, message: str) -> bool:
        pass

class BrevoSMSBackend(SMSBackend):
    """
    Implémentation Brevo Transactional SMS
    """
    def __init__(self):
        config = settings.ACTIVE_SMS_CONFIG
        self.api_key = config.get('API_KEY')
        self.sender_id = config.get('SENDER_ID')
        self.url = config.get('URL', 'https://api.brevo.com/v3/transactionalSMS/sms')

    def send(self, phone, message):
        if not all([self.api_key, self.sender_id, self.url]):
            logger.error("Brevo SMS backend is not configured. Missing API_KEY, SENDER_ID or URL.")
            return False

        headers = {
            "accept": "application/json",
            "api-key": self.api_key,
            "content-type": "application/json"
        }

        payload = {
            "sender": self.sender_id,
            "recipient": phone.replace("+", ""),
            "content": message,
            "type": "transactional"
        }

        try:
            response = requests.post(
                self.url,
                json=payload,
                headers=headers,
                timeout=10
            )

            if response.status_code == 201:
                logger.info(f"SMS envoyé via Brevo à {phone}")
                return True
            else:
                logger.error(f"Brevo SMS error: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Brevo connection error: {e}")
            return False

class ConsoleSMSBackend(SMSBackend):
    def send(self, phone, message):
        """A backend that prints SMS to the console."""
        print(f"--- SMS [to:{phone}, from:{getattr(settings, 'SMS_PROVIDER', 'console')}] ---")
        print(message)
        print("---------------------------------------------------------")
        logger.info(f"ConsoleSMSBackend: Sent SMS to {phone}")
        return True

class FasterMessageBackend(SMSBackend):
    """
    Implémentation pour FasterMessage (Bénin)
    """
    def __init__(self):
        config = settings.ACTIVE_SMS_CONFIG
        self.api_key = config.get('API_KEY')
        self.sender_id = config.get('SENDER_ID')
        self.base_url = config.get('URL', 'https://api.fastermessage.com/v1/send')

    def send(self, phone, message):
        if not all([self.api_key, self.sender_id, self.base_url]):
            logger.error("FasterMessage backend is not configured. Missing API_KEY, SENDER_ID or URL.")
            return False
            
        clean_phone = phone.replace('+', '')

        payload = {
            'apiKey': self.api_key,
            'phone': clean_phone,
            'message': message,
            'sender': self.sender_id
        }

        try:
            response = requests.post(self.base_url, json=payload, timeout=10)
            data = response.json()

            if response.status_code == 200 and data.get('status') == 'success':
                logger.info(f"SMS envoyé avec succès à {phone} via FasterMessage")
                return True
            else:
                logger.error(f"Erreur FasterMessage: {data}")
                return False
        except Exception as e:
            logger.error(f"Erreur connexion FasterMessage: {e}")
            return False

class Hub2SMSBackend(SMSBackend):
    """
    Implémentation Hub2 (Très utilisé au Bénin/Togo)
    """
    def __init__(self):
        config = settings.ACTIVE_SMS_CONFIG
        self.token = config.get('TOKEN')
        self.sender_id = config.get('SENDER_ID')
        self.url = config.get('URL', 'https://api.hub2.com/sms/send')

    def send(self, phone, message):
        if not all([self.token, self.sender_id, self.url]):
            logger.error("Hub2 backend is not configured. Missing TOKEN, SENDER_ID or URL.")
            return False

        headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json'
        }
        payload = {
            "to": phone,
            "content": message,
            "from": self.sender_id
        }
        try:
            response = requests.post(self.url, json=payload, headers=headers, timeout=10)
            return response.status_code == 201
        except Exception as e:
            logger.error(f"Hub2 Error: {e}")
            return False

def get_sms_backend():
    """Factory : retourne le service configuré"""
    provider = getattr(settings, 'SMS_PROVIDER', 'console')

    # The provider name in settings must match the key in the backend map.
    backend_map = {
        'fastermessage': FasterMessageBackend,
        'hub2': Hub2SMSBackend,
        'brevo': BrevoSMSBackend,
        'console': ConsoleSMSBackend,
    }

    # Get the backend class, defaulting to ConsoleSMSBackend if not found.
    backend_class = backend_map.get(provider, ConsoleSMSBackend)
    
    return backend_class()
