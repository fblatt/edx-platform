# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from datetime import datetime

from django.db import migrations, models

from entitlements.models import CourseEntitlementPolicy


def backfill_refundability(apps, schema_editor):
    now = datetime.now()
    CourseEntitlement = apps.get_model('entitlements', 'CourseEntitlement')
    for entitlement in CourseEntitlement.objects.all():
        # out_of_refund_period = (now - entitlement.created).days > entitlement.policy.refund_period
        # out_of_regain_period = entitlement.enrollment_course_run and (now - )
        # entitlement.is_refundable = not (entitlement.support_details or order_number is None or entitlement.expired_at or out_of_refund_period or out_of_regain_period)
        entitlement.is_refundable = not entitlement.support_details
        entitlement.save()

class Migration(migrations.Migration):

    dependencies = [
        ('entitlements', '0009_auto_20180410_1441'),
    ]

    operations = [
        migrations.RunPython(backfill_refundability),
    ]
