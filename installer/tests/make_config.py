"""Writes the test config and secrets (fake services, all modules that need no extra container)."""
import json
import sys

work = sys.argv[1]
cfg = json.load(open(__file__.replace("tests/make_config.py", "config.example.json")))
cfg.update(n8n_url="http://127.0.0.1:15679", openai_url="http://fake:9000/v1", main_channel="whatsapp",
           modules={"whatsapp": True, "email": True, "mail": True, "uptime": True})
cfg["whatsapp"] = {"waha_url": "http://fake:9000", "session": "default", "owner_phone": "15550001111"}
cfg["urls"]["filebridge"] = "http://filebridge:8790"
cfg["assistant_db"] = {"host": "db", "port": 5432, "database": "assistant", "user": "jc"}
cfg["ssh_ops"] = {"host": "fake", "port": 22, "user": "root"}
json.dump(cfg, open(work + "/config.json", "w"), indent=1)
sec = {"openai_api_key": "sk-test", "assistant_db_password": "db-test-password-123", "waha_key": "waha-test-key",
       "smtp": {"user": "u", "password": "p", "host": "fake", "port": 465, "secure": True},
       "ssh_ops_private_key": open(work + "/ops").read(),
       "notify_secret": "notify-test-secret-0123456789abcdef", "mail_secret": "mail-test-secret-0123456789abcdef",
       "filebridge_key": "filebridge-test-key-0123456789abcdef"}
json.dump(sec, open(work + "/secrets.json", "w"), indent=1)
