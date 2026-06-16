# C19F Messaging Permission Control

C19F controls whether two internal users can chat and which message capabilities
are unlocked by their user-to-user friend relationship.

## MessagingPermission Schema

```python
MessagingPermission = {
    "user_id": str,
    "target_user_id": str,
    "can_chat": bool,
    "friend_status": "none | pending | accepted | rejected",
    "unlocked_features": [
        "text",
        "emoji",
        "image",
        "file",
        "voice",
        "video",
    ],
}
```

Default internal permission is `can_chat=True` with only `text` and `emoji`
unlocked.

## Friend System Model

```python
FriendRequest = {
    "from_user_id": str,
    "to_user_id": str,
    "status": "pending | accepted | rejected",
    "created_at": datetime,
}
```

Accepted friend requests unlock all C19F features for the user pair. Pending
requests keep the pair at text and emoji. Rejected requests block communication.

## Permission Evaluation

The service entry point is:

```python
can_send_message(db, sender_user_id, receiver_user_id, content_type, actor, audit)
```

Evaluation order:

1. Sender must match the authenticated actor through C19E.
2. C19A identity and active membership are verified through the C19E/C19D path.
3. Cross-org communication must pass C19E.
4. Rejected friend status blocks all communication.
5. Non-accepted friend status allows only `text` and `emoji`.
6. `image`, `file`, `voice`, and `video` require `friend_status=accepted`.

## Feature Unlocking Rules

Level 1: Internal user

- `can_chat=True`
- unlocked: `text`, `emoji`

Level 2: Friend

- `can_chat=True`
- unlocked: `text`, `emoji`, `image`, `file`, `voice`, `video`

Level 3: Blocked

- `can_chat=False`
- unlocked: none

## API Design

All endpoints are mounted under `/api/app`.

- `POST /friends/request`
- `POST /friends/accept`
- `POST /friends/reject`
- `GET /friends/list`
- `POST /messages/permission/check`

`/messages/send` also runs C19F before continuing to the existing C19E/C19D/C19C
send boundary.

## Integration

- C19A: participant identity source remains `contact_identities`.
- C19C: message schema remains the content schema boundary. C19F authorizes
  feature use but does not implement media payloads.
- C19D: conversation binding remains owned by `conversation_service`.
- C19E: cross-org communication must pass `can_communicate`.
- C18G: data isolation remains separate and still applies.

## Security Boundaries

- Messaging permission is not org access.
- Messaging permission is not data isolation.
- All C19F permissions are user-to-user scoped.
- There is no owner/admin bypass for friend-required features.
- Rejected relationships block chat.
- No UI, websocket, group chat, voice/video transport, or migration is included.
