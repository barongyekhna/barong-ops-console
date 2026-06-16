from __future__ import annotations

from string import ascii_uppercase
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator

from .organization import ORG_ID_PATTERN


ALPHABET_GROUPS = tuple(ascii_uppercase) + ("#",)
ALPHABET_GROUP_SET = frozenset(ALPHABET_GROUPS)

# GBK pinyin initial ranges used by common Chinese contact-list sorting.
_GBK_PINYIN_INITIALS: tuple[tuple[int, int, str], ...] = (
    (45217, 45252, "A"),
    (45253, 45760, "B"),
    (45761, 46317, "C"),
    (46318, 46825, "D"),
    (46826, 47009, "E"),
    (47010, 47296, "F"),
    (47297, 47613, "G"),
    (47614, 48118, "H"),
    (48119, 49061, "J"),
    (49062, 49323, "K"),
    (49324, 49895, "L"),
    (49896, 50370, "M"),
    (50371, 50613, "N"),
    (50614, 50621, "O"),
    (50622, 50905, "P"),
    (50906, 51386, "Q"),
    (51387, 51445, "R"),
    (51446, 52217, "S"),
    (52218, 52697, "T"),
    (52698, 52979, "W"),
    (52980, 53688, "X"),
    (53689, 54480, "Y"),
    (54481, 55289, "Z"),
)


class GlobalContact(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True, extra="forbid")

    user_id: str = Field(min_length=1, max_length=255)

    display_name: str = Field(min_length=1, max_length=255)

    org_id: str = Field(min_length=1, max_length=40)
    org_name: str = Field(min_length=1, max_length=255)

    title: str = Field(min_length=1, max_length=255)

    role: str = Field(min_length=1, max_length=40)

    sort_key: str = Field(min_length=1, max_length=1)

    @field_validator("user_id", "display_name", "org_name", "title", "role")
    @classmethod
    def normalize_non_empty_string(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Global contact fields must not be empty.")
        return normalized

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, value: str) -> str:
        normalized = value.strip()
        if not ORG_ID_PATTERN.fullmatch(normalized):
            raise ValueError("org_id must reference an Organization.org_id.")
        return normalized

    @field_validator("sort_key", mode="before")
    @classmethod
    def normalize_sort_key(cls, value: object) -> str:
        normalized = str(value).strip().upper()
        if normalized not in ALPHABET_GROUP_SET:
            raise ValueError("sort_key must be A-Z or #.")
        return normalized


class GlobalContactDirectory(RootModel[dict[str, list[GlobalContact]]]):
    model_config = ConfigDict(frozen=True)

    @field_validator("root")
    @classmethod
    def validate_directory_groups(
        cls,
        value: dict[str, list[GlobalContact]],
    ) -> dict[str, list[GlobalContact]]:
        keys = set(value)
        allowed = set(ALPHABET_GROUPS)
        if keys != allowed:
            raise ValueError("Global contact directory must include A-Z and # groups.")
        return value


def _is_ascii_letter(char: str) -> bool:
    return len(char) == 1 and ("A" <= char <= "Z" or "a" <= char <= "z")


def _is_cjk_unified_ideograph(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


def pinyin_first_letter(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        return "#"

    first_char = normalized[0]
    if not _is_cjk_unified_ideograph(first_char):
        return "#"

    try:
        encoded = first_char.encode("gbk")
    except UnicodeEncodeError:
        return "#"

    if len(encoded) < 2:
        return "#"

    gbk_code = encoded[0] * 256 + encoded[1]
    for lower_bound, upper_bound, initial in _GBK_PINYIN_INITIALS:
        if lower_bound <= gbk_code <= upper_bound:
            return initial
    return "#"


def get_sort_key(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        return "#"

    first_char = normalized[0]
    if _is_cjk_unified_ideograph(first_char):
        return pinyin_first_letter(first_char)
    if _is_ascii_letter(first_char):
        return first_char.upper()
    return "#"


def empty_global_contact_directory() -> dict[str, list[GlobalContact]]:
    return {group: [] for group in ALPHABET_GROUPS}


class GlobalContactDirectoryAlgorithm(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    algorithm_id: Literal["c19b_global_directory_build_v1"] = (
        "c19b_global_directory_build_v1"
    )
    steps: tuple[
        Literal["fetch all ContactIdentity records"],
        Literal["join active C18C org memberships"],
        Literal["merge current organization name when available"],
        Literal["generate sort_key from display_name"],
        Literal["group contacts by A-Z and #"],
        Literal["sort groups alphabetically with # last"],
    ] = (
        "fetch all ContactIdentity records",
        "join active C18C org memberships",
        "merge current organization name when available",
        "generate sort_key from display_name",
        "group contacts by A-Z and #",
        "sort groups alphabetically with # last",
    )


class GlobalContactApiEndpointDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["GET"] = "GET"
    path: Literal["/contacts/directory"] = "/contacts/directory"
    response: Literal["A-Z plus # grouped GlobalContact directory"] = (
        "A-Z plus # grouped GlobalContact directory"
    )
    authenticated_internal_user_required: Literal[True] = True
    external_access_allowed: Literal[False] = False


class GlobalContactApiDesign(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    design_id: Literal["c19b_global_contact_api_design_v1"] = (
        "c19b_global_contact_api_design_v1"
    )
    endpoints: tuple[GlobalContactApiEndpointDesign, ...] = (
        GlobalContactApiEndpointDesign(),
    )
    chat_implemented: Literal[False] = False
    ui_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


class GlobalContactIntegrationModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    integration_id: Literal["c19b_directory_integrations_v1"] = (
        "c19b_directory_integrations_v1"
    )
    c19a_identity_source: Literal["contact_identities"] = "contact_identities"
    c18c_membership_source: Literal["org_memberships"] = "org_memberships"
    c19c_future_consumer: Literal["messaging may consume directory contacts later"] = (
        "messaging may consume directory contacts later"
    )
    c18f_boundary: Literal["authenticated internal user plus active C18C membership"] = (
        "authenticated internal user plus active C18C membership"
    )
    modifies_c19a: Literal[False] = False
    modifies_c18_system: Literal[False] = False
    implements_chat: Literal[False] = False


class GlobalContactSecurityModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    security_id: Literal["c19b_global_directory_security_v1"] = (
        "c19b_global_directory_security_v1"
    )
    internal_authenticated_session_required: Literal[True] = True
    active_c18c_membership_required_for_non_owner: Literal[True] = True
    owner_override_follows_c18f: Literal[True] = True
    cross_org_visibility_allowed_for_internal_users: Literal[True] = True
    external_access_allowed: Literal[False] = False
    mutates_contact_identity: Literal[False] = False
    mutates_org_membership: Literal[False] = False


class GlobalContactCompletionStatus(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: Literal["C19B"] = "C19B"
    component: Literal["Global Contact Directory"] = "Global Contact Directory"
    completion_status: Literal["complete"] = "complete"
    global_contact_schema_defined: Literal[True] = True
    directory_building_algorithm_defined: Literal[True] = True
    alphabet_grouping_logic_defined: Literal[True] = True
    sort_key_generation_defined: Literal[True] = True
    api_design_defined: Literal[True] = True
    c19a_integrated: Literal[True] = True
    c18c_integrated: Literal[True] = True
    c19c_integration_point_defined: Literal[True] = True
    c18f_security_boundary_defined: Literal[True] = True
    chat_implemented: Literal[False] = False
    ui_implemented: Literal[False] = False
    migration_executed: Literal[False] = False


GLOBAL_CONTACT_DATA_FLOW_DIAGRAM = """
GET /contacts/directory
  -> authenticated internal user (session)
  -> C18F boundary: owner override or active C18C membership
  -> read C19A contact_identities
  -> join C18C org_memberships where status = active
  -> merge organization name when available
  -> GlobalContact(user_id, display_name, org, title, role, sort_key)
  -> group A-Z, #
  -> return directory
""".strip()


def get_global_contact_directory_algorithm() -> GlobalContactDirectoryAlgorithm:
    return GlobalContactDirectoryAlgorithm()


def get_global_contact_api_design() -> GlobalContactApiDesign:
    return GlobalContactApiDesign()


def get_global_contact_integration_model() -> GlobalContactIntegrationModel:
    return GlobalContactIntegrationModel()


def get_global_contact_security_model() -> GlobalContactSecurityModel:
    return GlobalContactSecurityModel()


def get_global_contact_completion_status() -> GlobalContactCompletionStatus:
    return GlobalContactCompletionStatus()
