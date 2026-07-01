DEFAULT_TEST_ORG_DB_ID = "org_11111111111111111111111111111111"
DEFAULT_TEST_ORG_MEMBERSHIP_ID = "mem_11111111111111111111111111111111"
TARGET_TEST_ORG_NAME = "涌龙麟（深圳）国际贸易有限公司"

default_test_org = {
    "id": "org_yonglonglin_sz",
    "db_id": DEFAULT_TEST_ORG_DB_ID,
    "name": TARGET_TEST_ORG_NAME,
}


def test_org_payload(
    *,
    org_id: str = DEFAULT_TEST_ORG_DB_ID,
    org_name: str = TARGET_TEST_ORG_NAME,
) -> dict[str, object]:
    return {
        "org_id": org_id,
        "org_name": org_name,
        "org_type": "store",
        "status": "active",
        "metadata_json": {},
    }
