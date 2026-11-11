# jc-ops (server actions and reminders)

The only things the assistant may do on the server itself. n8n reaches it over SSH with a key that is locked to
this one command in `authorized_keys`:

    restrict,from="172.16.0.0/12",command="/usr/local/sbin/jc-ops ssh" ssh-ed25519 AAAA... n8n

Actions: `status` (time, load, memory, disks, tunnel, containers, backup status files), `restart <container>`
(only names in `restartable`), `remind_add <time> <base64 text or JSON {text, channels, repeat}>`,
`remind_list`, `remind_cancel <id>`. Anything else, or any odd character, is refused. No shell is ever used.

Reminders: kept in `/var/lib/jc-ops/reminders.json`; cron runs `jc-ops fire-reminders` every minute
(`jc-ops.cron`) and hands due ones to Notify Me. A reminder moves on only after n8n took it. `repeat` is
`none`, `daily` or `weekly`; channels are `whatsapp`, `telegram`, `email`, `call` (a voice reads it) and
`ai_call` (a live call with the assistant). The same time with the same words is refused as a duplicate.

Settings: `/etc/junkyard/ops.json` (see `ops.example.json`). Tests: `python -m unittest test_ops`.
