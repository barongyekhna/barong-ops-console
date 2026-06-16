# C19C Message System Schema

## 1. Message Schema Design

`backend/app/schemas/message.py` defines the internal message contract:

```python
class Message:
    message_id: str
    from_user_id: str
    to_user_id: str
    conversation_id: str
    content_type: "text | emoji"
    content: str
    status: "sent | delivered | read"
    created_at: datetime
    updated_at: datetime
    attachments: []
    media_type: "text | emoji"
```

`attachments` is reserved and must remain empty in C19C. `media_type` is
reserved and must match `content_type`.

## 2. Conversation Binding Logic

`Conversation` contains:

```python
class Conversation:
    conversation_id: str
    participants: [user_id, user_id]
```

C19C supports one-to-one internal conversations only. A message is valid only
when:

- `message.conversation_id == conversation.conversation_id`
- `message.from_user_id` is a participant
- `message.to_user_id` is a participant
- the sender and recipient are distinct users

Group-chat behavior is not implemented.

## 3. Content Restriction Rules

Allowed:

- `text`
- `emoji`

Denied:

- `voice`
- `video`
- `file`
- `image`
- any unknown `content_type`

The rule is enforced by the Pydantic enum and design model:

```text
IF content_type NOT IN ["text", "emoji"]:
    DENY
```

## 4. Message State Machine

Message status can only move forward:

```text
sent -> delivered -> read
```

Backward transitions and skipped transitions are denied. Idempotent same-state
updates are allowed so repeated delivery/read acknowledgements do not regress
state.

## 5. API Design

`backend/app/api/routes/messages.py` defines the internal application API
contract:

- `POST /messages/send`
- `GET /messages/{conversation_id}`
- `POST /messages/read`

Runtime mount:

- `/api/app/messages/send`
- `/api/app/messages/{conversation_id}`
- `/api/app/messages/read`

C19C is schema-only. The routes require an authenticated internal user and
return a schema-only `501` notice until message persistence is implemented by a
future stage.

## 6. Database Schema

Logical table design:

```sql
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY,
    from_user_id TEXT,
    to_user_id TEXT,
    conversation_id TEXT,
    content_type TEXT CHECK (content_type IN ('text', 'emoji')),
    content TEXT,
    status TEXT CHECK (status IN ('sent', 'delivered', 'read')),
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);

CREATE INDEX ix_messages_conversation_id
    ON messages (conversation_id);

CREATE INDEX ix_messages_from_user_id
    ON messages (from_user_id);

CREATE INDEX ix_messages_to_user_id
    ON messages (to_user_id);
```

`backend/app/models/message.py` adds SQLAlchemy metadata for this logical table,
but C19C does not add or execute an Alembic migration.

## 7. C19A / C19B / C18C Integration

- C19A Contact Identity: messages reference internal `user_id` identities and
  may display contact snapshots later.
- C19B Contact Directory: recipient selection can come from the internal global
  directory.
- C18C Org Membership: sender and recipient must exist as valid internal users
  with active membership.
- C18H Org Context: reserved for future message routing context.
- C18G Org Isolation: reserved as the future org isolation enforcement binding.

C19C does not modify C18, C19A, or C19B.

## 8. Security Boundary

- Internal-only message schema.
- No public API mount.
- No external API exposure.
- Authenticated internal user required for route contract access.
- Message sender and recipient must be conversation participants.
- User existence and active membership must be enforced through C18C.
- Org isolation is reserved for C18G future binding.
- No UI, frontend chat, websocket, group chat, file, image, voice, or video.
- No migration is executed.
