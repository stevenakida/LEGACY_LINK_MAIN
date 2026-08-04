from rest_framework import permissions


class IsMediaOwner(permissions.BasePermission):
    """Phase 1 authorization floor: owner-only. A UUID alone never grants
    access to anyone else. Once messaging/posts attach a MediaAsset in a
    later phase, that feature's own authorization (conversation participant
    / post audience) governs access for attached media — this check is
    what remains in force for anything not yet attached to anything."""

    def has_object_permission(self, request, view, obj):
        return obj.owner_id == request.user.id
