"""Voucher background tasks — expiration processing.

These tasks are designed to be called by Celery or APScheduler.
If neither is available, they can be invoked via manage.py CLI.
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def expire_vouchers_task(tenant_id: str = None):
    """
    Process expired vouchers: mark as expired and create quarantine accounting entry.

    Should run daily at 00:05 UTC (via Celery beat or cron).
    If tenant_id is None, processes all tenants.
    """
    from app.modules.vouchers.services import expire_due_vouchers

    logger.info("Starting voucher expiration task (tenant=%s)", tenant_id or "ALL")

    result = expire_due_vouchers(tenant_id=tenant_id)

    if result["expired_count"] > 0:
        logger.info("Expired %d vouchers", result["expired_count"])

        # Create accounting entries for each expired voucher
        for v in result["vouchers"]:
            try:
                from app.modules.accounting.services import post_voucher_expiry_entry
                post_voucher_expiry_entry(
                    tenant_id=v["tenant_id"],
                    created_by="system",
                    voucher_id=v["voucher_id"],
                    amount=v["expired_balance"],
                    quarantine=True,
                )
                logger.info(
                    "Created quarantine entry for voucher %s ($%s)",
                    v["code"], v["expired_balance"]
                )
            except Exception as e:
                logger.error(
                    "Failed to create accounting entry for expired voucher %s: %s",
                    v["voucher_id"], str(e), exc_info=True,
                )
    else:
        logger.info("No vouchers to expire")

    return result


def recognize_quarantine_vouchers_task(tenant_id: str = None):
    """
    Recognize income from vouchers that have been in quarantine for 30+ days.

    Should run daily after expire_vouchers_task.
    Moves 291002 (quarantine) → 429505 (non-operational income).
    """
    from app.extensions import db
    from app.modules.vouchers.models import Voucher, VoucherTransaction
    from datetime import timedelta

    logger.info("Starting quarantine recognition task (tenant=%s)", tenant_id or "ALL")

    now = datetime.now(timezone.utc)
    quarantine_cutoff = now - timedelta(days=30)

    # Find vouchers expired > 30 days ago that haven't been recognized yet
    q = Voucher.query.filter(
        Voucher.status == "expired",
    ).join(
        VoucherTransaction,
        (VoucherTransaction.voucher_id == Voucher.id) &
        (VoucherTransaction.transaction_type == "expired")
    ).filter(
        VoucherTransaction.occurred_at < quarantine_cutoff,
    )

    if tenant_id:
        q = q.filter(Voucher.tenant_id == tenant_id)

    vouchers = q.all()
    recognized = 0

    for voucher in vouchers:
        # Check if already recognized (look for a recognition transaction)
        already = VoucherTransaction.query.filter_by(
            voucher_id=voucher.id,
            transaction_type="adjusted",
        ).filter(
            VoucherTransaction.notes.like("%cuarentena%reconocimiento%")
        ).first()

        if already:
            continue

        try:
            from app.modules.accounting.services import post_voucher_expiry_entry
            post_voucher_expiry_entry(
                tenant_id=str(voucher.tenant_id),
                created_by="system",
                voucher_id=str(voucher.id),
                amount=float(voucher.face_value - voucher.remaining_balance)
                if voucher.remaining_balance > 0 else float(voucher.face_value),
                quarantine=False,
            )

            # Log the recognition
            from app.modules.vouchers.services import _log_transaction
            from decimal import Decimal
            _log_transaction(
                voucher=voucher,
                transaction_type="adjusted",
                amount_change=Decimal("0"),
                performed_by="system",
                notes="Cuarentena completada - reconocimiento ingreso no operacional",
            )
            db.session.commit()
            recognized += 1

            logger.info("Recognized quarantine voucher %s", voucher.code)
        except Exception as e:
            logger.error(
                "Failed to recognize quarantine voucher %s: %s",
                voucher.id, str(e), exc_info=True,
            )

    logger.info("Recognized %d quarantine vouchers", recognized)
    return {"recognized_count": recognized}
