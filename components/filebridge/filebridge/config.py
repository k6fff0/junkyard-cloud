"""Settings, read once from the environment. Every value the installer writes lives here."""
import os
import re
from dataclasses import dataclass


def _num(env, name, default, kind=float):
    raw = (env.get(name) or "").strip()
    return kind(raw) if raw else default


def _digits(value):
    return re.sub(r"\D", "", value or "")


@dataclass(frozen=True)
class Config:
    bridge_key: str
    data_dir: str = "/data"
    port: int = 8790
    owner: str = "the owner"          # how tool results name the person the assistant works for
    lang: str = "en"                  # language of the messages the owner gets

    # WhatsApp through WAHA (optional)
    waha_url: str = ""
    waha_key: str = ""
    wa_session: str = "default"
    wa_owner: str = ""                # owner's phone, digits only, e.g. 15551234567
    wa_extra_allowed: frozenset = frozenset()

    # Telegram (optional)
    tg_token: str = ""
    tg_chat: str = ""
    tg_api: str = "https://api.telegram.org"

    # Documents archive (Paperless-ngx, optional) and file tools (Stirling-PDF, optional)
    paperless_url: str = ""
    paperless_token: str = ""
    stirling_url: str = ""
    docs_url: str = ""                # public links shown to the owner, optional
    pdf_url: str = ""

    # Vision (optional)
    openai_key: str = ""
    openai_url: str = "https://api.openai.com/v1"
    look_model: str = "gpt-6-luna"

    # Timings (seconds). Tests make them small.
    group_wait: float = 4             # Telegram album
    wa_wait: float = 6                # quiet time before a WhatsApp file is handled
    wa_window: float = 20             # loose files this recent belong to a caption or a text
    chain: float = 8                  # WhatsApp photos closer than this (no words) = one album
    text_wait: float = 5              # a text about files waits this long when no files came
    text_max: float = 45              # and never longer than this
    archive_check_delay: float = 120  # then check that the archive could read the file
    keep_days: float = 3
    poll: float = 1                   # how often waiting loops look again

    @property
    def whatsapp(self):
        return bool(self.waha_url and self.waha_key and self.wa_owner)

    @property
    def telegram(self):
        return bool(self.tg_token and self.tg_chat)

    @property
    def archive(self):
        return bool(self.paperless_url and self.paperless_token)

    @property
    def stirling(self):
        return bool(self.stirling_url)

    @property
    def wa_chat(self):
        return "%s@c.us" % self.wa_owner if self.wa_owner else ""

    @property
    def default_channel(self):
        return "whatsapp" if self.whatsapp else "telegram"

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        g = lambda k, d="": (env.get(k) or d).strip()
        cfg = cls(
            bridge_key=g("BRIDGE_KEY"),
            data_dir=g("DATA_DIR", "/data"),
            port=_num(env, "PORT", 8790, int),
            owner=g("OWNER_NAME", "the owner"),
            lang=g("LANG_CODE", "en"),
            waha_url=g("WAHA_URL").rstrip("/"),
            waha_key=g("WAHA_KEY"),
            wa_session=g("WA_SESSION", "default"),
            wa_owner=_digits(g("WA_OWNER")),
            wa_extra_allowed=frozenset(x.strip() for x in g("WA_EXTRA_ALLOWED").split(",") if x.strip()),
            tg_token=g("TG_TOKEN"),
            tg_chat=g("TG_CHAT"),
            tg_api=g("TG_API", "https://api.telegram.org").rstrip("/"),
            paperless_url=g("PAPERLESS_URL").rstrip("/"),
            paperless_token=g("PAPERLESS_TOKEN"),
            stirling_url=g("STIRLING_URL").rstrip("/"),
            docs_url=g("DOCS_URL").rstrip("/"),
            pdf_url=g("PDF_URL").rstrip("/"),
            openai_key=g("OPENAI_API_KEY"),
            openai_url=g("OPENAI_URL", "https://api.openai.com/v1").rstrip("/"),
            look_model=g("LOOK_MODEL", "gpt-6-luna"),
            group_wait=_num(env, "GROUP_WAIT", 4),
            wa_wait=_num(env, "WA_WAIT", 6),
            wa_window=_num(env, "WA_WINDOW", 20),
            chain=_num(env, "CHAIN", 8),
            text_wait=_num(env, "TEXT_WAIT", 5),
            text_max=_num(env, "TEXT_MAX", 45),
            archive_check_delay=_num(env, "ARCHIVE_CHECK_DELAY", 120),
            keep_days=_num(env, "KEEP_DAYS", 3),
            poll=_num(env, "POLL", 1),
        )
        cfg.validate()
        return cfg

    def validate(self):
        if len(self.bridge_key) < 24:
            raise ValueError("BRIDGE_KEY must be set (24+ random characters)")
        if not (self.whatsapp or self.telegram):
            raise ValueError("Set up at least one channel: WhatsApp (WAHA_URL, WAHA_KEY, WA_OWNER) "
                             "or Telegram (TG_TOKEN, TG_CHAT)")
