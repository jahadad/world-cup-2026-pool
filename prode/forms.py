from django import forms
from django.conf import settings
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Tournament


class TournamentForm(forms.ModelForm):
    class Meta:
        model = Tournament
        fields = ["name"]
        labels = {"name": "League name"}
        widgets = {"name": forms.TextInput(attrs={"placeholder": "e.g. Office Legends"})}


class RegisterForm(UserCreationForm):
    first_name = forms.CharField(
        label="Your name", max_length=30,
        help_text="How others will see you on the leaderboard.",
    )
    invite_code = forms.CharField(label="Invite code")

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].help_text = "No spaces. Letters and numbers are fine."

    def clean_invite_code(self):
        # Vale el código general del sitio o el código de cualquier torneo:
        # quien tiene un link de torneo ya fue invitado por alguien.
        code = self.cleaned_data["invite_code"].strip()
        if code.upper() == settings.PRODE_INVITE_CODE.upper():
            return code
        if Tournament.objects.filter(code__iexact=code).exists():
            return code
        raise forms.ValidationError("Wrong invite code. Ask whoever invited you.")
