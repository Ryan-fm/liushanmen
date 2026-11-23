"""Configure the OpenAI-compatible model used by task chat."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

DOTENV = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)")
OPENAI_ENDPOINT = "https://api.openai.com/v1/chat/completions"
DEFAULT_CODEX_MODEL = "gpt-6.2-sol"
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def read_env(path: Path):
    """Read project settings as values, without executing the file."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return {}
    values = {}
    for line in lines:
        match = DOTENV.fullmatch(line.strip())
        if match is None:
            continue
        name, value = match.groups()
        if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
            value = value[1:-1]
        values.setdefault(name, value)
    return values


def load_env(path: Path):
    for name, value in read_env(path).items():
        os.environ.setdefault(name, value)


@dataclass(frozen=True)
class ChatModel:
    endpoint: str
    name: str
    key: str = field(repr=False)
    local: bool


@dataclass(frozen=True)
class CodexChatModel:
    executable: str
    model: str
    local = False

    @property
    def name(self):
        return self.model or "Codex"


def chat_model(env=None):
    env = os.environ if env is None else env
    if env.get("LSM_TASK_PROVIDER", "").strip().lower() == "codex":
        command = env.get("LSM_TASK_CODEX_BIN", "").strip() or "codex"
        executable = shutil.which(command, path=env.get("PATH"))
        model = env.get("LSM_TASK_CODEX_MODEL", "").strip() or DEFAULT_CODEX_MODEL
        return CodexChatModel(executable, model) if executable else None
    endpoint = env.get("LSM_TASK_LLM_ENDPOINT", "").strip()
    name = env.get("LSM_TASK_LLM_MODEL", "").strip()
    key = env.get("LSM_TASK_LLM_KEY", "")
    if not (endpoint or name or key):
        endpoint = env.get("LSM_LLM_ENDPOINT", "").strip()
        name = env.get("LSM_LLM_MODEL", "").strip()
        key = env.get("LSM_LLM_KEY", "")
    if not endpoint:
        endpoint = OPENAI_ENDPOINT
        name = name or env.get("OPENAI_MODEL", "").strip()
    if not name:
        return None
    try:
        url = urlsplit(endpoint)
        port = url.port
    except ValueError:
        return None
    local = url.hostname in LOOPBACK
    if (not url.hostname or url.username or url.password or url.fragment or port == 0
            or (url.scheme != "https" and not (local and url.scheme == "http"))):
        return None
    if url.netloc == "api.openai.com" and url.scheme == "https":
        key = key or env.get("OPENAI_API_KEY", "")
    if not local and not key:
        return None
    return ChatModel(endpoint, name, key, local)
