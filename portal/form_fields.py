import json

from django import forms

from .curriculum import (
    CURRICULUM,
    SUBJECT_CHOICES,
    chapter_choices,
    paper_choices,
)


def configure_curriculum_fields(form):
    if 'subject' not in form.fields:
        return

    subject_field = form.fields['subject']
    subject_name = form.add_prefix('subject')
    paper_name = form.add_prefix('paper')
    subject = form.data.get(subject_name) if form.is_bound else form.initial.get('subject', '')
    paper = form.data.get(paper_name) if form.is_bound else form.initial.get('paper', '')
    subject = subject or getattr(form.instance, 'subject', '')
    paper = paper or getattr(form.instance, 'paper', '')

    subject_choices = list(SUBJECT_CHOICES)
    existing_subject = getattr(form.instance, 'subject', '')
    if existing_subject and existing_subject not in dict(subject_choices):
        subject_choices.append((existing_subject, existing_subject))
    subject_field.widget = forms.Select(attrs={
        **subject_field.widget.attrs,
        'data-curriculum': json.dumps(
            CURRICULUM,
            ensure_ascii=False,
        ),
    })
    subject_field = forms.ChoiceField(
        label=subject_field.label,
        required=True,
        choices=[('', 'বিষয় নির্বাচন করুন'), *subject_choices],
        widget=subject_field.widget,
    )
    form.fields['subject'] = subject_field

    existing_paper = getattr(form.instance, 'paper', '')
    available_papers = list(paper_choices(subject))
    if subject == existing_subject and existing_paper and existing_paper not in dict(available_papers):
        available_papers.append((existing_paper, existing_paper))
    paper_field = form.fields['paper']
    form.fields['paper'] = forms.ChoiceField(
        label=paper_field.label,
        required=paper_field.required,
        choices=[('', 'পত্র নির্বাচন করুন'), *available_papers],
        help_text=paper_field.help_text,
    )

    chapter_field = form.fields['chapter']
    available_chapters = list(chapter_choices(subject, paper))
    existing_chapter = getattr(form.instance, 'chapter', '')
    if (
        subject == existing_subject
        and paper == existing_paper
        and existing_chapter
        and existing_chapter not in dict(available_chapters)
    ):
        available_chapters.append((existing_chapter, existing_chapter))
    form.fields['chapter'] = forms.ChoiceField(
        label=chapter_field.label,
        required=chapter_field.required,
        choices=[('', 'অধ্যায় নির্বাচন করুন'), *available_chapters],
        help_text=chapter_field.help_text,
    )
