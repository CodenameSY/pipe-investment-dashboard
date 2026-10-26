"""Send a reviewed briefing; keep receipts separate from automated signals."""
import hashlib
import os
from pathlib import Path
import sys
from energy_brief.bot import load_state, save_state, chunk_lines, telegram_send, DefiniteSendError, AmbiguousSendError

def send_reviewed(message_path, state_path):
    content = Path(message_path).read_text(encoding="utf-8").strip()
    if not content:
        raise RuntimeError("Empty briefing")
    digest = hashlib.sha256(content.encode()).hexdigest()[:16]
    state = load_state(Path(state_path))
    records = state.setdefault("manual_deliveries", {})
    if digest not in records:
        parts = chunk_lines(content.splitlines(), limit=3400)
        records[digest] = {"chunks": [{"text": f"[브리프 {digest[:8]} {i}/{len(parts)}]\n" + part, "status": "ready"} for i, part in enumerate(parts, 1)]}
        save_state(Path(state_path), state)
    chunks = records[digest]["chunks"]
    token, chat = os.environ["TELEGRAM_BOT_TOKEN"], os.environ["TELEGRAM_CHAT_ID"]
    for part in chunks:
        if part["status"] == "sent":
            continue
        if part["status"] in ("sending", "uncertain"):
            raise RuntimeError("Delivery uncertain; check Telegram before any retry")
        part["status"] = "sending"
        save_state(Path(state_path), state)
        try:
            receipt = telegram_send(token, chat, part["text"])
        except DefiniteSendError:
            part["status"] = "ready"
            save_state(Path(state_path), state)
            raise
        except AmbiguousSendError:
            part["status"] = "uncertain"
            save_state(Path(state_path), state)
            raise
        part.update(status="sent", message_id=receipt)
        save_state(Path(state_path), state)
    print(f"Reviewed briefing {digest[:8]}: {len(chunks)} parts confirmed delivered.")

if __name__ == "__main__":
    try:
        send_reviewed(sys.argv[1], sys.argv[2])
    except Exception as exc:
        print("Manual briefing stopped: " + type(exc).__name__, file=sys.stderr)
        raise SystemExit(1)
