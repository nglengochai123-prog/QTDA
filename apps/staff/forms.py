from django import forms

from apps.accounts.models import ACTIVE_ROLES, User
from apps.core import numbers

from .models import Employee


class EmployeeForm(forms.ModelForm):
    roles = forms.MultipleChoiceField(label="Vai trò đảm nhận được", choices=ACTIVE_ROLES,
                                      widget=forms.CheckboxSelectMultiple)
    username = forms.CharField(label="Tên đăng nhập", required=False,
                               help_text="Để trống thì dùng số điện thoại. Chỉ dùng khi tạo mới.")

    class Meta:
        model = Employee
        fields = ["full_name", "phone", "roles", "hourly_wage", "status"]
        formfield_callback = numbers.formfield

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:  # hiện đúng các vai trò đang có hiệu lực
            self.initial["roles"] = self.instance.effective_roles()

    def clean_username(self):
        username = self.cleaned_data.get("username")
        if self.instance.pk is None:
            username = username or self.cleaned_data.get("phone") or self.data.get("phone")
            if username and User.objects.filter(username=username).exists():
                raise forms.ValidationError("Tên đăng nhập đã được dùng.")
        return username
