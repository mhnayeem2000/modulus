import hashlib
import json

from .models import Routine


def get_teacher_routine_version(teacher):
    routines = list(
        Routine.objects.filter(teacher=teacher)
        .order_by('pk')
        .values_list(
            'pk',
            'teacher_id',
            'year_group',
            'weekday',
            'start_time',
            'end_time',
            'subject',
            'paper',
            'chapter',
            'is_revision',
        )
    )
    serialized_routines = json.dumps(routines, ensure_ascii=False, default=str)
    return hashlib.sha256(serialized_routines.encode('utf-8')).hexdigest()
