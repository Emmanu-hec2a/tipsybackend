from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from .models import User
from .views import get_tokens
from django.db import IntegrityError
import logging

logger = logging.getLogger(__name__)

class UnifiedLoginView(APIView):
    permission_classes = []
    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        
        # Try finding user by phone if username is just digits
        user = None
        if username and username.isdigit():
            user = User.objects.filter(phone=username).first()
            if user:
                username = user.username
        
        user = authenticate(username=username, password=password)
        
        if not user:
            return Response({'error': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)
            
        if user.role == 'partner' and not user.is_approved:
            return Response({'error': 'Merchant account pending approval'}, status=status.HTTP_403_FORBIDDEN)
            
        return Response(get_tokens(user))

class CustomerSignupView(APIView):
    permission_classes = []
    def post(self, request):
        try:
            data = request.data
            email = data.get('email')
            password = data.get('password')
            phone = str(data.get('phone', ''))
            username = data.get('username', email)
            full_name = data.get('full_name', '')
            
            if not email or not password:
                return Response({'error': 'Email and Password are required'}, status=status.HTTP_400_BAD_REQUEST)
                
            if User.objects.filter(username=username).exists():
                return Response({'error': 'An account with this email already exists.'}, status=status.HTTP_400_BAD_REQUEST)
            
            if phone and User.objects.filter(phone=phone).exists():
                 return Response({'error': 'An account with this phone number already exists.'}, status=status.HTTP_400_BAD_REQUEST)

            first_name = ""
            last_name = ""
            if full_name:
                parts = full_name.split(' ', 1)
                first_name = parts[0]
                if len(parts) > 1:
                    last_name = parts[1]
                
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role='customer',
                phone=phone,
                first_name=first_name,
                last_name=last_name,
                is_verified=True
            )
            return Response(get_tokens(user), status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({'error': 'Technical error: Identity already registered.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class RiderSignupView(APIView):
    permission_classes = []
    def post(self, request):
        try:
            data = request.data
            email = data.get('email')
            password = data.get('password')
            phone = str(data.get('phone', ''))
            username = data.get('username', email)
            full_name = data.get('full_name', '')
            
            if not email or not password:
                return Response({'error': 'Email and Password are required'}, status=status.HTTP_400_BAD_REQUEST)

            if User.objects.filter(username=username).exists():
                return Response({'error': 'An account with this email already exists.'}, status=status.HTTP_400_BAD_REQUEST)
            
            if phone and User.objects.filter(phone=phone).exists():
                 return Response({'error': 'An account with this phone number already exists.'}, status=status.HTTP_400_BAD_REQUEST)

            first_name = ""
            last_name = ""
            if full_name:
                parts = full_name.split(' ', 1)
                first_name = parts[0]
                if len(parts) > 1:
                    last_name = parts[1]

            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role='rider',
                phone=phone,
                first_name=first_name,
                last_name=last_name,
                is_approved=True 
            )
            return Response(get_tokens(user), status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({'error': 'Technical error: Identity already registered.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
