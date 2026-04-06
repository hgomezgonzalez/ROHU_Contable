"""Email service — Send emails via SMTP for notifications and campaigns."""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    from_email: str,
    to_email: str,
    subject: str,
    body_html: str,
) -> dict:
    """Send a single email via SMTP. Returns status dict."""
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = from_email
        msg["To"] = to_email
        msg["Subject"] = subject

        # Plain text fallback
        import re

        body_text = re.sub(r"<[^>]+>", "", body_html).strip()
        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(body_html, "html", "utf-8"))

        # Connect and send
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=15)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
            server.starttls()

        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()

        return {"success": True, "to": to_email}

    except smtplib.SMTPAuthenticationError:
        return {
            "success": False,
            "to": to_email,
            "error": "Error de autenticación SMTP. Verifique usuario y contraseña.",
        }
    except smtplib.SMTPRecipientsRefused:
        return {"success": False, "to": to_email, "error": f"Email rechazado: {to_email}"}
    except Exception as e:
        return {"success": False, "to": to_email, "error": str(e)}


def send_campaign_emails(
    smtp_config: dict,
    items: list,
    subject: str = "Recordatorio de pago pendiente",
) -> dict:
    """Send campaign emails to all items with email.

    smtp_config: {host, port, user, password, from_email}
    items: [{customer_email, rendered_message, customer_name}]

    Returns: {sent: int, failed: int, no_email: int, results: []}
    """
    if not smtp_config.get("host") or not smtp_config.get("user"):
        return {
            "sent": 0,
            "failed": 0,
            "no_email": 0,
            "error": "SMTP no configurado. Configure en Mi Negocio > Notificaciones.",
        }

    sent = 0
    failed = 0
    no_email = 0
    results = []

    for item in items:
        email = item.get("customer_email")
        message = item.get("rendered_message")
        name = item.get("customer_name", "Cliente")

        if not email:
            no_email += 1
            continue

        if not message:
            failed += 1
            results.append({"to": email, "error": "Sin mensaje renderizado"})
            continue

        # Build HTML email
        body_html = f"""
        <div style="font-family:Arial,sans-serif; max-width:600px; margin:0 auto; padding:20px;">
            <div style="border-bottom:2px solid #1E3A8A; padding-bottom:12px; margin-bottom:20px;">
                <h2 style="color:#1E3A8A; margin:0;">{smtp_config.get('business_name', 'ROHU Contable')}</h2>
            </div>
            <p>Estimado(a) <strong>{name}</strong>,</p>
            <div style="background:#F8FAFC; border:1px solid #E2E8F0; border-radius:8px; padding:16px; margin:16px 0;">
                {message.replace(chr(10), '<br>')}
            </div>
            <p style="color:#64748B; font-size:12px; margin-top:24px;">
                Este es un mensaje automático generado por el sistema de cobro de cartera.
            </p>
        </div>
        """

        result = send_email(
            smtp_host=smtp_config["host"],
            smtp_port=smtp_config.get("port", 587),
            smtp_user=smtp_config["user"],
            smtp_password=smtp_config["password"],
            from_email=smtp_config.get("from_email", smtp_config["user"]),
            to_email=email,
            subject=subject,
            body_html=body_html,
        )

        if result["success"]:
            sent += 1
        else:
            failed += 1
        results.append(result)

    return {"sent": sent, "failed": failed, "no_email": no_email, "results": results}
