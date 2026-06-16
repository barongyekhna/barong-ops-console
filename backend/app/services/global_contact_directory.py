from __future__ import annotations

from sqlalchemy.orm import Session

from ..core.roles import is_owner_role
from ..models.user import User
from ..repositories.global_contacts import (
    GlobalContactSourceRow,
    list_global_contact_source_rows,
    user_has_active_org_membership,
)
from ..schemas.global_contact import (
    ALPHABET_GROUPS,
    GlobalContact,
    empty_global_contact_directory,
    get_sort_key,
)
from .data_isolation import without_org_data_isolation


class GlobalContactDirectoryAccessDeniedError(PermissionError):
    pass


_GROUP_INDEX = {group: index for index, group in enumerate(ALPHABET_GROUPS)}


def _actor_user_id(actor: User) -> str:
    return str(actor.id)


def _ensure_actor_can_read_directory(db: Session, *, actor: User) -> None:
    if is_owner_role(actor.role):
        return

    if user_has_active_org_membership(db, user_id=_actor_user_id(actor)):
        return

    raise GlobalContactDirectoryAccessDeniedError(
        "Global contact directory requires an internal C18C org user."
    )


def _directory_role(row: GlobalContactSourceRow) -> str:
    if row.membership.role == "owner":
        return "owner"
    if row.membership.role == "admin":
        return "org_admin"
    if row.membership.role == "member":
        return "member"
    return row.identity.role


def _row_to_global_contact(row: GlobalContactSourceRow) -> GlobalContact:
    org_name = row.organization.org_name if row.organization is not None else None
    display_name = row.identity.name
    return GlobalContact(
        user_id=row.identity.user_id,
        display_name=display_name,
        org_id=row.identity.org_id,
        org_name=org_name or row.identity.org_name,
        title=row.identity.title,
        role=_directory_role(row),
        sort_key=get_sort_key(display_name),
    )


def _contact_sort_value(contact: GlobalContact) -> tuple[int, str, str, str]:
    return (
        _GROUP_INDEX[contact.sort_key],
        contact.display_name.casefold(),
        contact.org_name.casefold(),
        contact.user_id,
    )


def build_global_directory(
    db: Session,
    *,
    actor: User,
) -> dict[str, list[GlobalContact]]:
    with without_org_data_isolation():
        _ensure_actor_can_read_directory(db, actor=actor)
        contacts = [
            _row_to_global_contact(row)
            for row in list_global_contact_source_rows(db)
        ]

    contacts.sort(key=_contact_sort_value)
    directory = empty_global_contact_directory()
    for contact in contacts:
        directory[contact.sort_key].append(contact)
    return directory
