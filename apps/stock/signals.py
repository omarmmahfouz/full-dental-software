from django.db.models.signals import pre_delete
from django.dispatch import receiver

from apps.purchasing.models import PurchaseItem

from .models import StockMovement
from .services import undo_movement


@receiver(pre_delete, sender=PurchaseItem)
def take_back_deleted_purchase_line(sender, instance, **kwargs):
    """A deleted purchase line no longer adds to stock."""
    movement = StockMovement.objects.filter(purchase_item=instance).first()
    if movement is not None:
        undo_movement(movement)
