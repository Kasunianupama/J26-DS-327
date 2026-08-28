"""Security extension points; authentication is intentionally not implemented."""
from shared.schemas.user import UserRole


def role_can_view_risk(role: UserRole) -> bool:
    return role in {UserRole.FARM_MANAGER, UserRole.VETERINARIAN, UserRole.NLDB_MANAGEMENT}

