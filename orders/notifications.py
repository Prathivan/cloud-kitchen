"""
Order notification destination + send-stub, kept deliberately separate
from accounts.otp_service (which is specifically for the signup OTP
flow and its own MSG91 wiring). This module is about ORDER
notifications -- "order confirmed", "out for delivery", etc. -- once
that's needed.

The one rule this module exists to enforce: the destination phone
number for any order notification is ALWAYS order.recipient_phone,
never the account holder's phone directly. For a "Myself" order these
are the same value anyway (see orders.views.checkout), but for a
"Someone Else" order they are NOT, and getting this wrong would text
the wrong person.

No real provider is wired up here yet -- sending currently only logs.
When you're ready to send real order-status messages, follow the same
pattern accounts/otp_service.py already uses for MSG91: swap
_send_via_console() below for a real API call, gated behind an env var
so nothing here needs to change at the call site.
"""

import logging

logger = logging.getLogger("orders.notifications")


def get_notification_recipient_phone(order):
    """
    The one function every future SMS/WhatsApp call site should use to
    decide who to text about `order` -- never `order.customer_phone`
    directly, and never `order.user.customer_profile.mobile_number`.
    Returns "" if somehow neither is set (should not normally happen,
    since checkout always fills in at least the account holder's own
    number).
    """
    return order.recipient_phone or order.customer_phone or ""


def notify_order_recipient(order, message):
    """
    Send `message` to whoever should actually receive it for this
    order (see get_notification_recipient_phone above). Currently only
    logs/prints -- no SMS/WhatsApp provider is connected yet. Returns
    True if the send step completed without error (always True for the
    console stub).
    """
    phone = get_notification_recipient_phone(order)
    if not phone:
        logger.warning("Order #%s has no recipient phone on file; notification not sent.", order.id)
        return False

    log_line = f"[ORDER NOTIFICATION STUB] To {phone} (Order #{order.id}): {message}"
    print(log_line)
    logger.info(log_line)
    return True
