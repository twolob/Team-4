from django.core.exceptions import ValidationError
from django.test import TestCase

from .admin import CustomUserCreationForm
from .models import User


class UserManagerTests(TestCase):
    def test_create_user_with_email_and_password(self):
        user = User.objects.create_user(
            email="User@Example.com", password="StrongPass123!"
        )

        field_names = {field.name for field in User._meta.get_fields()}

        self.assertEqual(user.email, "user@example.com")
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertNotEqual(user.password, "StrongPass123!")
        self.assertNotIn("username", field_names)

    def test_email_is_normalized_before_save(self):
        user = User.objects.create_user(
            email="  Mixed.CASE@Example.COM  ", password="StrongPass123!"
        )

        self.assertEqual(user.email, "mixed.case@example.com")

    def test_missing_email_is_rejected(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="", password="StrongPass123!")

    def test_create_superuser(self):
        user = User.objects.create_superuser(
            email="admin@example.com", password="StrongPass123!"
        )

        self.assertTrue(user.is_staff)
        self.assertTrue(user.is_superuser)
        self.assertEqual(user.email, "admin@example.com")

    def test_superuser_requires_is_staff_true(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="admin@example.com",
                password="StrongPass123!",
                is_staff=False,
            )

    def test_superuser_requires_is_superuser_true(self):
        with self.assertRaises(ValueError):
            User.objects.create_superuser(
                email="admin@example.com",
                password="StrongPass123!",
                is_superuser=False,
            )


class AdminFormTests(TestCase):
    def test_custom_admin_form_uses_email(self):
        form = CustomUserCreationForm()

        self.assertIn("email", form.fields)
        self.assertNotIn("username", form.fields)
        self.assertIn("password1", form.fields)
        self.assertIn("password2", form.fields)

    def test_password_confirmation_validation(self):
        form = CustomUserCreationForm(
            data={
                "email": "user@example.com",
                "password1": "StrongPass123!",
                "password2": "DifferentPass123!",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)

    def test_password_validator_validation(self):
        form = CustomUserCreationForm(
            data={
                "email": "user@example.com",
                "password1": "password",
                "password2": "password",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password2", form.errors)
