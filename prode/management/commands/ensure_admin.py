import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea el superusuario desde ADMIN_USERNAME/ADMIN_PASSWORD si no existe. Idempotente."

    def handle(self, *args, **opts):
        username = os.environ.get("ADMIN_USERNAME")
        password = os.environ.get("ADMIN_PASSWORD")
        if not (username and password):
            self.stdout.write("ADMIN_USERNAME/ADMIN_PASSWORD no seteados, salteo.")
            return
        User = get_user_model()
        user = User.objects.filter(username=username).first()
        if user:
            if not (user.is_staff and user.is_superuser):
                user.is_staff = user.is_superuser = True
                user.save(update_fields=["is_staff", "is_superuser"])
                self.stdout.write(self.style.SUCCESS(f"{username} promovido a admin."))
            else:
                self.stdout.write(f"{username} ya es admin.")
            return
        User.objects.create_superuser(username=username, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superusuario {username} creado."))
