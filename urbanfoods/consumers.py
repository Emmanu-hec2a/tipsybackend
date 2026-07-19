import json
from django.utils import timezone
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .models import Order, ChatMessage, User
from .api_v1_serializers import ChatMessageSerializer

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.order_id = self.scope['url_route']['kwargs']['order_id']
        self.room_group_name = f'chat_{self.order_id}'
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        # Check if user is part of the order
        is_allowed = await self.check_order_permission()
        if not is_allowed:
            await self.close()
            return

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    # Receive message from WebSocket
    async def receive(self, text_data):
        data = json.loads(text_data)
        message_text = data.get('message')

        if not message_text:
            return

        # Save message to database
        saved_msg = await self.save_message(message_text)
        
        if saved_msg:
            # Send message to room group
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'chat_message',
                    'message': saved_msg
                }
            )

    # Receive message from room group
    async def chat_message(self, event):
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps(message))

    @database_sync_to_async
    def check_order_permission(self):
        try:
            order = Order.objects.get(id=self.order_id)
            return self.user == order.user or self.user == order.assigned_rider
        except Order.DoesNotExist:
            return False

    @database_sync_to_async
    def save_message(self, text):
        try:
            order = Order.objects.get(id=self.order_id)
            
            # Security: If no rider is assigned, customer cannot message
            if not order.assigned_rider and self.user.role == 'customer':
                return {'error': 'No rider assigned to this order yet.'}

            msg = ChatMessage.objects.create(
                order=order,
                sender=self.user,
                message=text
            )
            
            # 🔔 Trigger FCM Notification to the other party
            recipient = order.assigned_rider if self.user == order.user else order.user
            if recipient:
                from .utils import send_fcm_notification
                send_fcm_notification(
                    user=recipient,
                    title=f"Message from {self.user.get_full_name() or self.user.username}",
                    body=text,
                    data={
                        'type': 'chat',
                        'order_id': str(order.id),
                        'order_number': order.order_number
                    }
                )

            # Use serializer to get the same format as REST API
            # Note: Serializer uses self.context['request'] for absolute URIs, 
            # we need to simulate or pass a fake context for WebSocket.
            # However, for WebSockets, relative URLs are often fine or we can pass a dummy request.
            serializer = ChatMessageSerializer(msg)
            return serializer.data
        except Exception as e:
            print(f"Error saving socket message: {e}")
            return None
