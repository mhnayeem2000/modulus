from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import UserProfile


def get_role(user):
    if user.is_superuser:
        return 'superadmin'
    profile, _ = UserProfile.objects.get_or_create(user=user)
    return profile.role


def role_required(*roles):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if get_role(request.user) not in roles:
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def user_role(request):
    user = request.user
    if not user.is_authenticated:
        return {'user_role': ''}
    if user.is_superuser:
        return {'user_role': 'superadmin'}
    profile = UserProfile.objects.filter(user=user).only('role').first()
    return {'user_role': profile.role if profile else 'teacher'}
