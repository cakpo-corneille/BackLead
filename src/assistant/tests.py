"""
Tests pour l'app assistant. Les appels Gemini sont mockés pour éviter
de consommer des crédits et pour rendre les tests déterministes.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase

from assistant.models import ChatConversation, ChatMessage
from assistant.services import chat, generate_form_schema

User = get_user_model()


def make_owner(email='owner@example.com'):
    return User.objects.create_user(email=email, password='Pass1234!')


# ============================================================
# 1. SERVICES
# ============================================================

class ChatServiceTest(TestCase):

    def setUp(self):
        self.owner = make_owner()

    @patch('assistant.services.gemini_client.generate_text')
    def test_creates_conversation_and_persists_messages(self, mock_gen):
        mock_gen.return_value = "Bonjour, comment puis-je vous aider ?"

        conv, reply = chat(self.owner, "Salut")

        self.assertIsNotNone(conv.id)
        self.assertEqual(conv.owner, self.owner)
        self.assertEqual(conv.messages.count(), 2)
        self.assertEqual(conv.messages.first().role, ChatMessage.ROLE_USER)
        self.assertEqual(conv.messages.first().content, "Salut")
        self.assertEqual(reply.role, ChatMessage.ROLE_MODEL)
        self.assertEqual(reply.content, "Bonjour, comment puis-je vous aider ?")
        self.assertEqual(conv.title, "Salut")

    @patch('assistant.services.gemini_client.generate_text')
    def test_continues_existing_conversation(self, mock_gen):
        mock_gen.return_value = "OK"
        conv, _ = chat(self.owner, "Premier message")
        first_id = conv.id

        mock_gen.return_value = "Suite OK"
        conv2, reply2 = chat(self.owner, "Deuxième", conversation=conv)

        self.assertEqual(conv2.id, first_id)
        self.assertEqual(conv2.messages.count(), 4)
        # L'historique passé à l'IA contient les 3 messages précédents (user1, model1, user2)
        # mais on ne passe que jusqu'au dernier non-inclus → 3 entrées
        history = mock_gen.call_args.kwargs['history']
        # Avant l'appel #2, la conv contient [user1, model1, user2_courant].
        # On retire user2_courant car il est passé en `prompt`.
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['role'], 'user')
        self.assertEqual(history[1]['role'], 'model')

    @patch('assistant.services.gemini_client.generate_text')
    def test_owner_isolation(self, mock_gen):
        mock_gen.return_value = "OK"
        conv, _ = chat(self.owner, "msg")
        other = make_owner('other@example.com')
        with self.assertRaises(PermissionError):
            chat(other, "intrusion", conversation=conv)

    @patch('assistant.services.gemini_client.generate_text')
    def test_gemini_failure_returns_fallback(self, mock_gen):
        mock_gen.side_effect = RuntimeError("503 from Gemini")
        conv, reply = chat(self.owner, "test")
        self.assertIn("indisponible", reply.content.lower())
        self.assertEqual(conv.messages.count(), 2)


class GenerateFormSchemaTest(TestCase):

    def _mock_response(self, payload):
        return json.dumps(payload)

    @patch('assistant.services.gemini_client.generate_text')
    def test_basic_generation(self, mock_gen):
        mock_gen.return_value = self._mock_response({
            "title": "Wifi gratuit",
            "description": "Inscrivez-vous",
            "button_label": "Connexion",
            "fields": [
                {"name": "full_name", "label": "Nom complet", "type": "text", "required": True},
                {"name": "email", "label": "Email", "type": "email", "required": True},
            ],
        })
        schema = generate_form_schema("Je veux nom et email")
        self.assertEqual(schema['title'], "Wifi gratuit")
        self.assertEqual(len(schema['fields']), 2)
        self.assertEqual(schema['fields'][0]['type'], 'text')

    @patch('assistant.services.gemini_client.generate_text')
    def test_filters_invalid_field_types(self, mock_gen):
        mock_gen.return_value = self._mock_response({
            "fields": [
                {"name": "x", "label": "X", "type": "text", "required": True},
                {"name": "y", "label": "Y", "type": "fancy_unknown_type", "required": True},
                {"name": "", "label": "", "type": "text"},
            ],
        })
        schema = generate_form_schema("test")
        self.assertEqual(len(schema['fields']), 1)
        self.assertEqual(schema['fields'][0]['name'], 'x')

    @patch('assistant.services.gemini_client.generate_text')
    def test_choice_keeps_options(self, mock_gen):
        mock_gen.return_value = self._mock_response({
            "fields": [
                {"name": "type", "label": "Type", "type": "choice",
                 "required": True, "options": ["Étudiant", "Pro"]},
            ],
        })
        schema = generate_form_schema("type de visiteur")
        self.assertEqual(schema['fields'][0]['options'], ["Étudiant", "Pro"])

    @patch('assistant.services.gemini_client.generate_text')
    def test_invalid_json_raises(self, mock_gen):
        mock_gen.return_value = "ceci n'est pas du JSON"
        with self.assertRaises(ValueError):
            generate_form_schema("test")

    @patch('assistant.services.gemini_client.generate_text')
    def test_missing_fields_raises(self, mock_gen):
        mock_gen.return_value = self._mock_response({"title": "X"})
        with self.assertRaises(ValueError):
            generate_form_schema("test")

    @patch('assistant.services.gemini_client.generate_text')
    def test_empty_fields_raises(self, mock_gen):
        mock_gen.return_value = self._mock_response({"fields": []})
        with self.assertRaises(ValueError):
            generate_form_schema("test")

    @patch('assistant.services.gemini_client.generate_text')
    def test_all_invalid_fields_raises(self, mock_gen):
        mock_gen.return_value = self._mock_response({
            "fields": [{"name": "x", "label": "X", "type": "unknown"}],
        })
        with self.assertRaises(ValueError):
            generate_form_schema("test")


# ============================================================
# 2. ENDPOINTS REST
# ============================================================

class AssistantAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner()
        self.client.force_authenticate(self.owner)

    @patch('assistant.services.gemini_client.generate_text')
    def test_chat_endpoint_creates_conversation(self, mock_gen):
        mock_gen.return_value = "Réponse IA"
        r = self.client.post('/api/v1/assistant/chat/', {
            'message': 'Comment configurer mon WiFi ?',
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIn('conversation_id', r.data)
        self.assertEqual(r.data['reply']['content'], 'Réponse IA')

    @patch('assistant.services.gemini_client.generate_text')
    def test_chat_continues_conversation(self, mock_gen):
        mock_gen.return_value = "1"
        r = self.client.post('/api/v1/assistant/chat/',
                             {'message': 'Q1'}, format='json')
        cid = r.data['conversation_id']

        mock_gen.return_value = "2"
        r2 = self.client.post('/api/v1/assistant/chat/', {
            'message': 'Q2', 'conversation_id': cid,
        }, format='json')
        self.assertEqual(r2.data['conversation_id'], cid)
        conv = ChatConversation.objects.get(id=cid)
        self.assertEqual(conv.messages.count(), 4)

    def test_chat_rejects_other_owner_conversation(self):
        other = make_owner('other@example.com')
        conv = ChatConversation.objects.create(owner=other, title='priv')
        r = self.client.post('/api/v1/assistant/chat/', {
            'message': 'hack', 'conversation_id': conv.id,
        }, format='json')
        self.assertEqual(r.status_code, 404)

    def test_chat_validation_error(self):
        r = self.client.post('/api/v1/assistant/chat/',
                             {'message': ''}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_chat_unauthenticated(self):
        self.client.force_authenticate(None)
        r = self.client.post('/api/v1/assistant/chat/',
                             {'message': 'hi'}, format='json')
        self.assertEqual(r.status_code, 401)

    @patch('assistant.services.gemini_client.generate_text')
    def test_generate_form_endpoint(self, mock_gen):
        mock_gen.return_value = json.dumps({
            "title": "T", "description": "D", "button_label": "B",
            "fields": [
                {"name": "email", "label": "Email", "type": "email", "required": True},
            ],
        })
        r = self.client.post('/api/v1/assistant/generate-form/', {
            'prompt': 'Un formulaire pour collecter les emails',
        }, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['fields']), 1)
        self.assertEqual(r.data['fields'][0]['type'], 'email')

    @patch('assistant.services.gemini_client.generate_text')
    def test_generate_form_invalid_response(self, mock_gen):
        mock_gen.return_value = 'not json'
        r = self.client.post('/api/v1/assistant/generate-form/', {
            'prompt': 'un formulaire',
        }, format='json')
        self.assertEqual(r.status_code, 422)

    @patch('assistant.services.gemini_client.generate_text')
    def test_generate_form_gemini_failure(self, mock_gen):
        mock_gen.side_effect = RuntimeError("network error")
        r = self.client.post('/api/v1/assistant/generate-form/', {
            'prompt': 'un formulaire',
        }, format='json')
        self.assertEqual(r.status_code, 503)

    def test_generate_form_unauthenticated(self):
        self.client.force_authenticate(None)
        r = self.client.post('/api/v1/assistant/generate-form/', {
            'prompt': 'x',
        }, format='json')
        self.assertEqual(r.status_code, 401)


class ConversationsAPITest(APITestCase):

    def setUp(self):
        self.owner = make_owner()
        self.other = make_owner('other@example.com')
        self.client.force_authenticate(self.owner)
        self.conv = ChatConversation.objects.create(owner=self.owner, title='Mine')
        ChatMessage.objects.create(conversation=self.conv, role='user', content='hi')
        ChatMessage.objects.create(conversation=self.conv, role='model', content='hello')
        ChatConversation.objects.create(owner=self.other, title='Theirs')

    def test_list_only_own(self):
        r = self.client.get('/api/v1/assistant/conversations/')
        self.assertEqual(r.status_code, 200)
        results = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['title'], 'Mine')
        self.assertEqual(results[0]['messages_count'], 2)

    def test_retrieve_includes_messages(self):
        r = self.client.get(f'/api/v1/assistant/conversations/{self.conv.id}/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.data['messages']), 2)

    def test_cannot_retrieve_others(self):
        their = ChatConversation.objects.filter(owner=self.other).first()
        r = self.client.get(f'/api/v1/assistant/conversations/{their.id}/')
        self.assertEqual(r.status_code, 404)

    def test_delete_own_conversation(self):
        r = self.client.delete(f'/api/v1/assistant/conversations/{self.conv.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(ChatConversation.objects.filter(pk=self.conv.pk).exists())

    def test_unauthenticated(self):
        self.client.force_authenticate(None)
        r = self.client.get('/api/v1/assistant/conversations/')
        self.assertEqual(r.status_code, 401)
