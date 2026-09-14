"""
OTP delivery, via MSG91 (SMS + WhatsApp) for India.

By default (no MSG91 auth key configured) this ONLY logs/prints the
code -- nothing is actually sent. Once you've signed up with MSG91,
completed DLT registration for SMS, and got a WhatsApp OTP template
approved, set the env vars below and real messages will start going
out automatically -- no other file in this project needs to change.

Required .env settings once you're ready to go live:

    OTP_PROVIDER=msg91
    MSG91_AUTH_KEY=your-msg91-auth-key

    # SMS (needs DLT registration -- see MSG91's dashboard):
    MSG91_SMS_SENDER_ID=YOURID          # your registered 6-letter sender ID
    MSG91_SMS_DLT_TEMPLATE_ID=123456789012345    # DLT template ID
    MSG91_SMS_TEMPLATE=Your Butterfly Cloud Kitchen verification code is {otp}. Valid for 5 minutes.
        # ^ must match your DLT-approved template text EXACTLY, with {otp}
        #   where the OTP digits go.

    # WhatsApp (needs an approved WhatsApp "Authentication" template):
    MSG91_WHATSAPP_INTEGRATED_NUMBER=919876543210   # your WhatsApp Business number
    MSG91_WHATSAPP_TEMPLATE_NAME=otp_verification   # template name in MSG91
    MSG91_WHATSAPP_NAMESPACE=your-template-namespace
    MSG91_WHATSAPP_LANGUAGE=en                       # optional, defaults to en

See MSG91's docs (https://msg91.com/help) for how to get each of these
values -- they're all things you configure once in the MSG91
dashboard, not values you invent.
"""

import logging
import os

import requests

logger = logging.getLogger("accounts.otp")

# Set to "msg91" once the env vars above are filled in. Any other
# value (including unset) uses the console/log stub instead.
OTP_PROVIDER = os.environ.get("OTP_PROVIDER", "console")

MSG91_AUTH_KEY = os.environ.get("MSG91_AUTH_KEY", "")
MSG91_SMS_SENDER_ID = os.environ.get("MSG91_SMS_SENDER_ID", "")
MSG91_SMS_DLT_TEMPLATE_ID = os.environ.get("MSG91_SMS_DLT_TEMPLATE_ID", "")
MSG91_SMS_TEMPLATE = os.environ.get(
    "MSG91_SMS_TEMPLATE",
    "Your Butterfly Cloud Kitchen verification code is {otp}. Valid for 5 minutes.",
)
MSG91_WHATSAPP_INTEGRATED_NUMBER = os.environ.get("MSG91_WHATSAPP_INTEGRATED_NUMBER", "")
MSG91_WHATSAPP_TEMPLATE_NAME = os.environ.get("MSG91_WHATSAPP_TEMPLATE_NAME", "")
MSG91_WHATSAPP_NAMESPACE = os.environ.get("MSG91_WHATSAPP_NAMESPACE", "")
MSG91_WHATSAPP_LANGUAGE = os.environ.get("MSG91_WHATSAPP_LANGUAGE", "en")

MSG91_SMS_URL = "https://api.msg91.com/api/v2/sendsms"
MSG91_WHATSAPP_URL = "https://api.msg91.com/api/v5/whatsapp/whatsapp-outbound-message/bulk/"

REQUEST_TIMEOUT_SECONDS = 10


def send_otp(mobile_number, channel, code):
    """
    "Sends" an OTP code to mobile_number over the given channel
    ("sms" or "whatsapp"). Returns True if the send step completed
    without error.
    """
    if OTP_PROVIDER == "msg91":
        return _send_via_msg91(mobile_number, channel, code)
    return _send_via_console(mobile_number, channel, code)


def _send_via_console(mobile_number, channel, code):
    message = (
        f"[OTP STUB] {channel.upper()} to {mobile_number}: "
        f"your Butterfly Cloud Kitchen verification code is {code} "
        f"(valid 5 minutes). No real message was sent -- OTP_PROVIDER "
        f"is not configured."
    )
    # Both logged and printed: printed so it's visible directly in the
    # `runserver` terminal during manual testing, logged so it also
    # shows up wherever Django's logging is configured to go.
    print(message)
    logger.info(message)
    return True


def _normalize_indian_mobile(mobile_number):
    """
    MSG91 expects a bare digit string with country code and no '+',
    e.g. "919876543210". Our own validation (accounts.models) accepts
    "+919876543210", "919876543210", or a plain 10-digit "9876543210"
    -- normalize all three to what MSG91 wants, assuming India (91)
    when no country code was given.
    """
    digits = "".join(ch for ch in mobile_number if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return digits


def _send_via_msg91(mobile_number, channel, code):
    if not MSG91_AUTH_KEY:
        logger.warning("OTP_PROVIDER=msg91 but MSG91_AUTH_KEY is not set; falling back to console stub.")
        return _send_via_console(mobile_number, channel, code)

    to_number = _normalize_indian_mobile(mobile_number)
    try:
        if channel == "whatsapp":
            return _send_msg91_whatsapp(to_number, code)
        return _send_msg91_sms(to_number, code)
    except requests.RequestException:
        logger.exception("MSG91 request failed for %s to %s.", channel, mobile_number)
        return False


def _send_msg91_sms(to_number, code):
    if not (MSG91_SMS_SENDER_ID and MSG91_SMS_DLT_TEMPLATE_ID):
        logger.warning(
            "MSG91 SMS is missing MSG91_SMS_SENDER_ID/MSG91_SMS_DLT_TEMPLATE_ID; "
            "falling back to console stub."
        )
        return _send_via_console(to_number, "sms", code)

    message = MSG91_SMS_TEMPLATE.format(otp=code)
    response = requests.post(
        MSG91_SMS_URL,
        headers={"authkey": MSG91_AUTH_KEY, "content-type": "application/json", "accept": "application/json"},
        json={
            "sender": MSG91_SMS_SENDER_ID,
            "route": "4",  # transactional route -- required for OTPs
            "country": "91",
            "sms": [{"message": message, "to": [to_number]}],
            "DLT_TE_ID": MSG91_SMS_DLT_TEMPLATE_ID,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        logger.error("MSG91 SMS send failed (%s): %s", response.status_code, response.text[:500])
        return False
    return True


def _send_msg91_whatsapp(to_number, code):
    if not (MSG91_WHATSAPP_INTEGRATED_NUMBER and MSG91_WHATSAPP_TEMPLATE_NAME and MSG91_WHATSAPP_NAMESPACE):
        logger.warning(
            "MSG91 WhatsApp is missing one of MSG91_WHATSAPP_INTEGRATED_NUMBER/"
            "MSG91_WHATSAPP_TEMPLATE_NAME/MSG91_WHATSAPP_NAMESPACE; falling back to console stub."
        )
        return _send_via_console(to_number, "whatsapp", code)

    response = requests.post(
        MSG91_WHATSAPP_URL,
        headers={"authkey": MSG91_AUTH_KEY, "content-type": "application/json"},
        json={
            "integrated_number": MSG91_WHATSAPP_INTEGRATED_NUMBER,
            "content_type": "template",
            "payload": {
                "messaging_product": "whatsapp",
                "type": "template",
                "template": {
                    "name": MSG91_WHATSAPP_TEMPLATE_NAME,
                    "language": {"code": MSG91_WHATSAPP_LANGUAGE, "policy": "deterministic"},
                    "namespace": MSG91_WHATSAPP_NAMESPACE,
                    "to_and_components": [
                        {"to": [to_number], "components": {"body_1": {"type": "text", "value": code}}}
                    ],
                },
            },
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code >= 400:
        logger.error("MSG91 WhatsApp send failed (%s): %s", response.status_code, response.text[:500])
        return False
    return True
