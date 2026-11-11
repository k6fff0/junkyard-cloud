# mailwatch (email to the assistant)

Watches IMAP inboxes and hands every new email to n8n (`Mail In`), which sends one-time codes to the owner at
once, a summary of important mail right away, and the rest in one evening digest.

- one thread per mailbox; INBOX is opened read-only, so nothing is ever marked as read
- waits with IMAP IDLE, renewed every 9 minutes, with TCP keepalive every 60 s: Gmail is silent during IDLE and a
  router on the way forgets a silent connection, so new mail could be late without it
- remembers the last UID per mailbox and moves forward only after n8n accepted the email: nothing is lost if n8n
  is down. The first start on a mailbox begins from "now"
- a mailbox down for 30 minutes sends one `{"type": "status"}` message, and another when it is back

Settings: `N8N_URL` (the `mail-in` webhook), `MAIL_SECRET` (header `X-Mail-Secret`), `ACCOUNTS_FILE`
(see `accounts.example.json`; Gmail and other mailboxes with two-step login need an app password), `DATA_DIR`.
The container runs `python:3.14.10-slim` as is, read-only, on its own isolated network (`jc-isolate mailwatch`).

Tests: `python -m unittest test_mailwatch`.
