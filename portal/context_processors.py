from .access import user_role


def coaching_context(request):
    return user_role(request)
