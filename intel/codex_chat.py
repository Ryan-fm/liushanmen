"""Use the signed-in Codex CLI for a single task answer."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "points": {"type": "array", "items": {
            "type": "object",
            "properties": {"text": {"type": "string"}, "ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["text", "ids"],
            "additionalProperties": False,
        }},
        "limitation": {"type": "string"},
    },
    "required": ["points", "limitation"],
    "additionalProperties": False,
}


def codex_reply(settings, instructions, context):
    # Use the CLI's ChatGPT login. Keep project API keys out of the subprocess.
    env = {key: value for key, value in os.environ.items() if key == "CODEX_HOME"
           or not key.startswith(("CODEX_", "OPENAI_", "LSM_LLM_", "LSM_TASK_LLM_"))}
    try:
        with TemporaryDirectory(prefix="liushanmen-codex-") as directory:
            schema = Path(directory) / "schema.json"
            output = Path(directory) / "answer.json"
            schema.write_text(json.dumps(ANSWER_SCHEMA), encoding="utf-8")
            command = [settings.executable, "-a", "never", "exec", "--ephemeral", "--ignore-user-config",
                       "--skip-git-repo-check", "--sandbox", "read-only", "--disable", "shell_tool",
                       "--disable", "plugins", "--disable", "apps", "--disable", "multi_agent_v2",
                       "--disable", "view_image", "-c", 'web_search="disabled"',
                       "-c", 'forced_login_method="chatgpt"', "-c", 'model_reasoning_effort="low"',
                       "--output-schema", str(schema), "--output-last-message", str(output)]
            if settings.model:
                command.extend(["--model", settings.model])
            prompt = instructions + "\n\n" + json.dumps(context, ensure_ascii=False)
            result = subprocess.run([*command, "-"], input=prompt, text=True, encoding="utf-8",
                                    env=env, cwd=directory, timeout=75,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                value = json.loads(output.read_text(encoding="utf-8"))
                return value if isinstance(value, dict) else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None
