BATCH_CHOICES = (
    ('first', '১ম বর্ষ'),
    ('second', '২য় বর্ষ'),
)

BATCH_LABELS = dict(BATCH_CHOICES)

YEAR_GROUPS = BATCH_CHOICES


def academic_year_key(class_name):
    normalized = (class_name or '').casefold().translate(str.maketrans('০১২৩৪৫৬৭৮৯', '0123456789'))
    normalized = ' '.join(normalized.replace('-', ' ').replace('_', ' ').split())
    normalized = f' {normalized} '
    first_year_markers = (
        ' 1st year ', ' first year ', ' year 1 ', ' class 11 ', ' class xi ',
        ' hsc xi ', ' 1ম বর্ষ ', ' প্রথম বর্ষ ', ' 1ম বছর ', ' প্রথম বছর ',
    )
    second_year_markers = (
        ' 2nd year ', ' second year ', ' year 2 ', ' class 12 ', ' class xii ',
        ' hsc xii ', ' 2য় বর্ষ ', ' ২য় বর্ষ ', ' দ্বিতীয় বর্ষ ', ' 2য় বছর ', ' দ্বিতীয় বছর ',
    )
    if any(marker in normalized for marker in first_year_markers):
        return 'first'
    if any(marker in normalized for marker in second_year_markers):
        return 'second'
    return 'other'
