import hmac
import hashlib
from typing import Dict


def verify_signature(headers: Dict[str, str], body: bytes, secret: str) -> bool:
    """Verify Twitch EventSub webhook signature"""
    try:
        # Get the signature from headers
        signature = headers.get("Twitch-Eventsub-Message-Signature", "")

        # Extract the signature value (remove 'sha256=' prefix)
        if not signature.startswith("sha256="):
            return False

        received_signature = signature[7:]  # Remove 'sha256=' prefix

        # Get other required headers
        message_id = headers.get("Twitch-Eventsub-Message-Id", "")
        timestamp = headers.get("Twitch-Eventsub-Message-Timestamp", "")

        # Create the message to verify
        message = message_id + timestamp + body.decode("utf-8")

        # Calculate expected signature
        expected_signature = hmac.new(
            secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Compare signatures
        return hmac.compare_digest(received_signature, expected_signature)

    except Exception:
        return False
