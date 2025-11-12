from django import forms
from .models import Contestant, Participation, Team, Program

class ContestantForm(forms.ModelForm):
    class Meta:
        model = Contestant
        fields = ['name']




from .models import Contestant, Team, Category

class ContestantForm(forms.ModelForm):
    class Meta:
        model = Contestant
        fields = ['name', 'team', 'category']

class TeamCategoryForm(forms.Form):
    team = forms.ModelChoiceField(queryset=Team.objects.all())
    category = forms.ModelChoiceField(queryset=Category.objects.all())

# forms.py
from django import forms
from .models import Participation, Team, Category, Contestant, Program
class ParticipationForm(forms.Form):
    team = forms.ModelChoiceField(queryset=Team.objects.all(), required=True)
    category = forms.ModelChoiceField(queryset=Category.objects.all(), required=True)
    contestant = forms.ModelChoiceField(queryset=Contestant.objects.none(), required=True)
    programs = forms.ModelMultipleChoiceField(
        queryset=Program.objects.none(),
        widget=forms.CheckboxSelectMultiple,  # You can use SelectMultiple if you prefer dropdown
        required=True
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

        if user and user.role == 'team':
            if hasattr(user, 'team'):
                self.fields['team'].initial = user.team
                self.fields['team'].widget = forms.HiddenInput()
            else:
                self.fields['team'].queryset = Team.objects.none()

        # Load choices dynamically
        if 'team' in self.data and 'category' in self.data:
            try:
                team_id = int(self.data.get('team'))
                category_id = int(self.data.get('category'))

                self.fields['contestant'].queryset = Contestant.objects.filter(
                    team_id=team_id, category_id=category_id
                ).order_by('name')

                self.fields['programs'].queryset = Program.objects.filter(
                    category_id=category_id
                ).order_by('name')

            except (ValueError, TypeError):
                pass


from django.contrib.auth.models import User

class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ['user', 'name']
        widgets = {
            'user': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }


# Add this to your forms.py

from django import forms
from .models import Participation

class MarkEntryForm(forms.ModelForm):
    class Meta:
        model = Participation
        fields = ['marks','code_letter']
        widgets = {
            'marks': forms.NumberInput(attrs={
                'class': 'marks-input',
                'min': '0',
                'max': '100',
                'step': '0.01',
                'placeholder': '0.00'
            }),
            'code_letter': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '...'}),
        }
    
    def clean_marks(self):
        marks = self.cleaned_data.get('marks')
        if marks is not None:
            if marks < 0:
                raise forms.ValidationError("Marks cannot be negative.")
            if marks > 100:
                raise forms.ValidationError("Marks cannot exceed 100.")
        return marks
    
from django import forms
from .models import Participation, Program

class MarksForm(forms.ModelForm):
    class Meta:
        model = Participation
        fields = ['marks', 'rank', 'grade']
        widgets = {
            'marks': forms.NumberInput(attrs={'class': 'form-control', 'min': 0}),
            'rank': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'grade': forms.Select(
                choices=[('', '---'), ('A', 'A'), ('B', 'B'), ('C', 'C')],
                attrs={'class': 'form-control'}
            ),
        }

class BulkMarksForm(forms.Form):
    """Form for adding marks to multiple participants at once"""
    
    def __init__(self, participations, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        for participation in participations:
            # Create fields for each participation
            self.fields[f'marks_{participation.id}'] = forms.IntegerField(
                label=f"{participation.contestant.name} - Marks",
                required=False,
                initial=participation.marks,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 0})
            )
            
            self.fields[f'rank_{participation.id}'] = forms.IntegerField(
                label=f"{participation.contestant.name} - Rank",
                required=False,
                initial=participation.rank,
                widget=forms.NumberInput(attrs={'class': 'form-control', 'min': 1})
            )
            
            self.fields[f'grade_{participation.id}'] = forms.ChoiceField(
                label=f"{participation.contestant.name} - Grade",
                choices=[('', '---'), ('A', 'A'), ('B', 'B'), ('C', 'C')],
                required=False,
                initial=participation.grade,
                widget=forms.Select(attrs={'class': 'form-control'})
            )
