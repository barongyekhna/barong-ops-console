# C19G Attachment System Schema

## 1. Attachment Schema Design

`backend/app/schemas/attachment.py` defines the metadata contract for all future
non-text IM content:

```python
class Attachment:
    attachment_id: str
    message_id: str
    type: "image | file | video | audio"
    url: str
    filename: str
    size: int
    mime_type: str
    created_at: datetime
```

`attachment_id` uses `att_ + uuid4().hex`. `message_id` references the C19C
message id format. `url` is treated as an internal storage locator; external
HTTP(S) URLs are rejected by default.

## 2. Supported File Types

Strict type rules:

- `image`: `jpg`, `png`, `webp`, `gif`
- `file`: `pdf`, `doc`, `xlsx`, `zip`
- `video`: `mp4`, `mov`
- `audio`: `mp3`, `wav`

The schema validates both filename extension and MIME family. Upload, transfer,
object storage, CDN, and file processing are not implemented.

## 3. Message Attachment Extension Model

C19G reserves the C19C message extension field:

```python
attachments: list[Attachment]
```

The list can be empty. `Message` can represent attachment metadata for future
read/persistence paths, while `MessageSendRequest` still requires the attachment
list to be empty in the current stage. C19F remains responsible for deciding
whether attachment upload is allowed.

## 4. Database Schema

Logical table design only. No Alembic migration is added or executed.

```sql
CREATE TABLE attachments (
    attachment_id TEXT PRIMARY KEY,
    message_id TEXT,
    type TEXT,
    url TEXT,
    filename TEXT,
    size INTEGER,
    mime_type TEXT,
    created_at TIMESTAMP
);

CREATE INDEX ix_attachments_message_id
    ON attachments (message_id);

CREATE INDEX ix_attachments_type
    ON attachments (type);
```

C18G future enforcement must scope attachment storage and access by `org_id`.

## 5. API Design

Placeholder-only internal application routes:

- `POST /attachments/upload`
- `GET /attachments/{message_id}`

Runtime mount:

- `/api/app/attachments/upload`
- `/api/app/attachments/{message_id}`

Both routes require an authenticated internal user and return a C19G schema-only
`501` notice. No upload, retrieval, storage, or transfer logic is implemented.

## 6. Integration Points

- C19C: `Message.attachments` is the future message metadata extension point.
- C19F: `friend_status == accepted` is required before attachment upload can be
  enabled by a future implementation.
- C19D: `message_id` resolves conversation context before attachment access.
- C18G: attachment storage and lookup must be org-scoped by `org_id`.

C19G does not modify C19A-F runtime behavior.

## 7. Security Boundary Design

- Attachment permission is not message permission.
- Attachment permission is not org permission.
- Attachment metadata and storage access must be scoped by `org_id` through C18G.
- External access is denied by default.
- Public API mounting is not allowed.
- Authenticated internal user is required for placeholder contract access.
- C19F controls whether attachment upload is allowed.
- C18G controls data isolation.

## 8. Future Extension Architecture

Reserved but not implemented:

- image compression pipeline
- video transcoding
- file storage backend
- CDN integration
- virus scanning hook

C19G is only the schema and contract reservation layer for non-text IM content.
