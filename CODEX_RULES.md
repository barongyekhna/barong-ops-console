# Codex Safety Rules

1. Work only inside /opt/barong-ops-console unless explicitly approved.
2. Do not modify /opt/n8n, /opt/filebrowser, /opt/minio, /root, or existing production docker-compose files.
3. Do not stop, restart, delete, or modify existing production containers.
4. Do not run rm -rf.
5. Do not read, print, or modify real secrets.
6. Create .env.example only. Never create real .env with secrets unless the owner explicitly provides values.
7. Every task must have a plan before changes.
8. Every task must report changed files.
9. Every task must include verification steps.
10. Do not add business modules before the empty console foundation is complete.
