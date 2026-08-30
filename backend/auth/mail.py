"""Send login OTP mail through Resend."""
import resend

from storage.config import RESEND_API_KEY, RESEND_FROM


def send_otp_email(to: str, code: str) -> None:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is not set")
    resend.api_key = RESEND_API_KEY
    resend.Emails.send(
        {
            "from": RESEND_FROM,
            "to": [to],
            "subject": f"{code} — your chat login code",
            "html": (
                f"<p>Your login code is:</p>"
                f'<p style="font-size:24px;letter-spacing:4px"><strong>{code}</strong></p>'
                f"<p>This code expires in 10 minutes. "
                f"If you did not request it, you can ignore this email.</p>"
            ),
            "text": f"Your login code is {code}. It expires in 10 minutes.",
        }
    )
