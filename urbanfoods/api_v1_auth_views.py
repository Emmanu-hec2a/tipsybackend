from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from .models import User
from .views import get_tokens
from django.db import IntegrityError
import logging
import firebase_admin
from firebase_admin import auth as firebase_auth

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
            dob = data.get('dob')
            meta = data.get('verification_metadata', {})
            
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
                is_verified=True,
                date_of_birth=dob,
                verification_metadata=meta
            )
            return Response(get_tokens(user), status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({'error': 'Technical error: Identity already registered.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

class FirebaseSocialLoginView(APIView):
    """
    Production-ready social login using Firebase ID Tokens.
    Supports Google and Apple authentication.
    Handles 'Smart Linking' with phone-based accounts.
    """
    permission_classes = []
    
    def post(self, request):
        token = request.data.get('token')
        
        if not token:
            return Response({'error': 'Token is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            # Verify the Firebase ID token
            decoded_token = firebase_auth.verify_id_token(token)
            uid = decoded_token.get('uid')
            email = decoded_token.get('email')
            name = decoded_token.get('name', '')
            picture = decoded_token.get('picture', '')
            
            if not email:
                return Response({'error': 'Email not provided by social provider'}, status=status.HTTP_400_BAD_REQUEST)
                
            # 1. Attempt to find user by Email
            user = User.objects.filter(email=email).first()
            
            is_new_user = False
            if not user:
                # 🛡️ New Social Users default to 'customer'
                first_name = ""
                last_name = ""
                if name:
                    parts = name.split(' ', 1)
                    first_name = parts[0]
                    last_name = parts[1] if len(parts) > 1 else ""
                
                # Create new user (using email as username)
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=User.objects.make_random_password(),
                    role='customer',
                    first_name=first_name,
                    last_name=last_name,
                    is_verified=True,
                    profile_picture=picture
                )
                is_new_user = True
            
            # 2. Check if phone setup is needed
            # A user needs phone setup if they don't have a phone number yet.
            requires_phone_setup = not bool(user.phone)
            
            res_data = get_tokens(user)
            res_data['requires_phone_setup'] = requires_phone_setup
            res_data['is_new_user'] = is_new_user
            
            return Response(res_data)
            
        except Exception as e:
            logger.error(f"Firebase social login error: {e}")
            return Response({'error': 'Invalid social token or verification failed'}, status=status.HTTP_401_UNAUTHORIZED)

class LinkSocialPhoneView(APIView):
    """
    Finalizes social login by linking a phone number.
    Handles 'Account Merging' if the phone already exists.
    """
    def post(self, request):
        phone = request.data.get('phone')
        if not phone:
            return Response({'error': 'Phone number is required'}, status=400)
            
        current_user = request.user
        
        # 1. Check if another account already uses this phone
        existing_user = User.objects.filter(phone=phone).exclude(id=current_user.id).first()
        
        if existing_user:
            # 🛡️ SMART MERGE: Move social identity (Email/Name) to the phone account
            # and delete the temporary social-only account.
            
            # Only merge if the existing account doesn't have an email yet, 
            # or if it's the SAME email.
            if not existing_user.email or existing_user.email == current_user.email:
                existing_user.email = current_user.email
                if not existing_user.first_name:
                    existing_user.first_name = current_user.first_name
                if not existing_user.last_name:
                    existing_user.last_name = current_user.last_name
                if not existing_user.profile_picture:
                    existing_user.profile_picture = current_user.profile_picture
                
                existing_user.is_verified = True
                existing_user.save()
                
                # Delete the temporary placeholder
                current_user.delete()
                
                return Response({
                    'message': 'Accounts merged successfully',
                    **get_tokens(existing_user)
                })
            else:
                return Response({
                    'error': 'This phone is already linked to a different email address.'
                }, status=400)
        
        # 2. Simply update the current user if phone is unique
        current_user.phone = phone
        current_user.save()
        
        return Response({
            'message': 'Phone linked successfully',
            'role': current_user.role
        })

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
            dob = data.get('dob')
            meta = data.get('verification_metadata', {})
            
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
                is_approved=True,
                date_of_birth=dob,
                verification_metadata=meta
            )
            return Response(get_tokens(user), status=status.HTTP_201_CREATED)
        except IntegrityError:
            return Response({'error': 'Technical error: Identity already registered.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
