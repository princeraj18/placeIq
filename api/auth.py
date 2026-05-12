import secrets
from django.contrib.auth.hashers import make_password, check_password
from rest_framework import authentication, exceptions
from .models import User, AuthToken


def create_user(username, email, password, first_name='', last_name='', role='student'):
    if User.objects.filter(username=username).exists():
        return None
    user = User.objects.create(
        username=username,
        email=email,
        password=make_password(password),
        first_name=first_name,
        last_name=last_name,
        role=role,
    )
    return user


def verify_user(username, password):
    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        return None
    if check_password(password, user.password):
        return user
    return None


def create_token(user):
    token_value = secrets.token_hex(32)
    AuthToken.objects.create(user=user, token=token_value)
    return token_value


def get_user_from_token(token_value):
    try:
        tok = AuthToken.objects.select_related('user').get(token=token_value)
        return tok.user
    except AuthToken.DoesNotExist:
        return None


def invalidate_token(token_value):
    AuthToken.objects.filter(token=token_value).delete()


def serialize_user(user):
    return {
        'id': user.id,
        'username': user.username,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
    }


class TokenAuthentication(authentication.BaseAuthentication):
    keyword = 'Token'

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header or header[0].lower() != b'token':
            return None
        if len(header) != 2:
            raise exceptions.AuthenticationFailed('Invalid token header.')
        token = header[1].decode()
        user = get_user_from_token(token)
        if not user:
            raise exceptions.AuthenticationFailed('Invalid or expired token.')
        return (user, token)

    def authenticate_header(self, request):
        return self.keyword
