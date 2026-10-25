from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

from .year_groups import BATCH_CHOICES


MAX_RESOURCE_SIZE = 20 * 1024 * 1024


def validate_resource_size(file):
    if file.size > MAX_RESOURCE_SIZE:
        raise ValidationError('ফাইলের আকার ২০ মেগাবাইটের বেশি হতে পারবে না।')


class UserProfile(models.Model):
    class Role(models.TextChoices):
        TEACHER = 'teacher', 'শিক্ষক'
        STUDENT = 'student', 'শিক্ষার্থী'

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    role = models.CharField('ভূমিকা', max_length=10, choices=Role.choices, default=Role.TEACHER)
    phone = models.CharField('মোবাইল নম্বর', max_length=20, blank=True)

    class Meta:
        verbose_name = 'ব্যবহারকারী প্রোফাইল'
        verbose_name_plural = 'ব্যবহারকারী প্রোফাইল'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} · {self.get_role_display()}'


class Routine(models.Model):
    class YearGroup(models.TextChoices):
        FIRST = 'first', '১ম বর্ষ'
        SECOND = 'second', '২য় বর্ষ'

    class Weekday(models.IntegerChoices):
        SATURDAY = 5, 'শনিবার'
        SUNDAY = 6, 'রবিবার'
        MONDAY = 0, 'সোমবার'
        TUESDAY = 1, 'মঙ্গলবার'
        WEDNESDAY = 2, 'বুধবার'
        THURSDAY = 3, 'বৃহস্পতিবার'
        FRIDAY = 4, 'শুক্রবার'

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_routines',
        limit_choices_to={'profile__role': UserProfile.Role.TEACHER},
    )
    class_name = models.CharField('শ্রেণি/ব্যাচ', max_length=60)
    year_group = models.CharField(
        'বর্ষ',
        max_length=10,
        choices=YearGroup.choices,
        default=YearGroup.FIRST,
    )
    weekday = models.PositiveSmallIntegerField('বার', choices=Weekday.choices)
    start_time = models.TimeField('শুরুর সময়')
    end_time = models.TimeField('শেষের সময়')
    subject = models.CharField('বিষয়', max_length=100)
    paper = models.CharField('পত্র', max_length=100, blank=True)
    chapter = models.CharField('অধ্যায়', max_length=120, blank=True)
    is_revision = models.BooleanField('রিভিশন ক্লাস', default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['weekday', 'start_time']
        verbose_name = 'ক্লাস রুটিন'
        verbose_name_plural = 'ক্লাস রুটিন'

    def __str__(self):
        return f'{self.class_name} · {self.get_weekday_display()} · {self.subject}'

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'ক্লাস শেষের সময় শুরুর সময়ের পরে হতে হবে।'})


class TeacherAttendance(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'অনুমোদনের অপেক্ষায়'
        APPROVED = 'approved', 'উপস্থিত'
        ABSENT = 'absent', 'অনুপস্থিত'
        REJECTED = 'rejected', 'অনুমোদিত হয়নি'

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_attendance_records',
        limit_choices_to={'profile__role': UserProfile.Role.TEACHER},
    )
    routine = models.ForeignKey(
        Routine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teacher_attendance_records',
    )
    date = models.DateField('তারিখ', default=timezone.localdate)
    status = models.CharField('অবস্থা', max_length=10, choices=Status.choices)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_teacher_attendance',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-date', 'teacher__first_name', 'teacher__username']
        constraints = [
            models.UniqueConstraint(fields=['teacher', 'date'], name='unique_teacher_attendance_per_day'),
        ]
        verbose_name = 'শিক্ষকের উপস্থিতি'
        verbose_name_plural = 'শিক্ষকের উপস্থিতি'

    def __str__(self):
        return f'{self.teacher} · {self.date} · {self.get_status_display()}'


class SupportSessionAttendance(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='support_session_attendances',
        limit_choices_to={'profile__role': UserProfile.Role.TEACHER},
        verbose_name='শিক্ষক',
    )
    date = models.DateField('যোগদানের তারিখ', default=timezone.localdate)
    joined_at = models.DateTimeField('যোগদানের সময়', auto_now_add=True)

    class Meta:
        ordering = ['-date', 'teacher__first_name', 'teacher__username']
        constraints = [
            models.UniqueConstraint(
                fields=['teacher', 'date'],
                name='unique_teacher_support_session_per_day',
            ),
        ]
        verbose_name = 'সাপোর্ট সেশনে শিক্ষকের যোগদান'
        verbose_name_plural = 'সাপোর্ট সেশনে শিক্ষকদের যোগদান'

    def __str__(self):
        return f'{self.teacher} · {self.date}'


class ClassSession(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='class_sessions',
        limit_choices_to={'profile__role': UserProfile.Role.TEACHER},
    )
    class_name = models.CharField('শ্রেণি/ব্যাচ', max_length=60)
    year_group = models.CharField('বর্ষ', max_length=10, choices=BATCH_CHOICES, default='first')
    date = models.DateField('ক্লাসের তারিখ')
    start_time = models.TimeField('শুরুর সময়', blank=True, null=True)
    end_time = models.TimeField('শেষের সময়', blank=True, null=True)
    subject = models.CharField('বিষয়', max_length=100)
    paper = models.CharField('পত্র', max_length=100, blank=True)
    chapter = models.CharField('অধ্যায়', max_length=120)
    topic = models.CharField('টপিক', max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date', '-start_time']
        verbose_name = 'পরিচালিত ক্লাস'
        verbose_name_plural = 'পরিচালিত ক্লাস'

    def __str__(self):
        return f'{self.class_name} · {self.date} · {self.subject} · {self.chapter}'

    def clean(self):
        if self.start_time and self.end_time and self.end_time <= self.start_time:
            raise ValidationError({'end_time': 'ক্লাস শেষের সময় শুরুর সময়ের পরে হতে হবে।'})


class ClassSessionProgress(models.Model):
    session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        related_name='student_progress',
        verbose_name='পরিচালিত ক্লাস',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='class_session_progress',
        verbose_name='শিক্ষার্থী',
    )
    is_completed = models.BooleanField('পড়া সম্পন্ন', default=False)
    problem_description = models.TextField('যে সমস্যার মুখোমুখি হয়েছে', blank=True, max_length=1500)
    updated_at = models.DateTimeField('সর্বশেষ হালনাগাদ', auto_now=True)

    class Meta:
        ordering = ['student__name']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'student'],
                name='unique_class_session_progress_per_student',
            ),
        ]
        verbose_name = 'শিক্ষার্থীর পড়ার অগ্রগতি'
        verbose_name_plural = 'শিক্ষার্থীদের পড়ার অগ্রগতি'

    def __str__(self):
        return f'{self.student.name} · {self.session.subject} · {self.session.date}'


class LearningMaterial(models.Model):
    class Kind(models.TextChoices):
        SHEET = 'sheet', 'ক্লাস শিট'
        BOOK = 'book', 'বই'
        IMPORTANT = 'important', 'গুরুত্বপূর্ণ ফাইল'

    title = models.CharField('শিরোনাম', max_length=150)
    kind = models.CharField('ফাইলের ধরন', max_length=12, choices=Kind.choices)
    class_name = models.CharField('শ্রেণি/ব্যাচ', max_length=60, blank=True, help_text='ফাঁকা রাখলে সব শিক্ষার্থী দেখতে পাবে।')
    year_group = models.CharField(
        'বর্ষ',
        max_length=10,
        choices=[('', 'সব বর্ষ'), *BATCH_CHOICES],
        blank=True,
        default='',
    )
    subject = models.CharField('বিষয়', max_length=100)
    paper = models.CharField('পত্র', max_length=100, blank=True)
    chapter = models.CharField('অধ্যায়', max_length=120, blank=True)
    description = models.CharField('সংক্ষিপ্ত বিবরণ', max_length=300, blank=True)
    file = models.FileField(
        'ফাইল',
        upload_to='learning_materials/%Y/%m/',
        blank=True,
        validators=[
            FileExtensionValidator(['pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png']),
            validate_resource_size,
        ],
    )
    external_url = models.URLField('বাহ্যিক লিংক', blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='learning_materials',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'শিক্ষাসামগ্রী'
        verbose_name_plural = 'শিক্ষাসামগ্রী'

    def __str__(self):
        return f'{self.title} · {self.get_kind_display()}'

    def clean(self):
        if not self.file and not self.external_url:
            raise ValidationError('একটি ফাইল আপলোড করুন অথবা বাহ্যিক লিংক দিন।')


class StudentFeeRecord(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='fee_records',
        verbose_name='শিক্ষার্থী',
    )
    month = models.CharField('মাস', max_length=7, help_text='YYYY-MM')
    monthly_fee = models.DecimalField('মাসিক বেতন', max_digits=12, decimal_places=2, default=0)
    amount_paid = models.DecimalField('পরিশোধ', max_digits=12, decimal_places=2, default=0)
    note = models.CharField('নোট', max_length=240, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_fee_records',
        verbose_name='রেকর্ড করেছেন',
    )
    created_at = models.DateTimeField('তৈরি হয়েছে', auto_now_add=True)
    updated_at = models.DateTimeField('হালনাগাদ হয়েছে', auto_now=True)

    class Meta:
        ordering = ['student__name', '-month']
        verbose_name = 'শিক্ষার্থীর বেতন রেকর্ড'
        verbose_name_plural = 'শিক্ষার্থীদের বেতন রেকর্ড'
        constraints = [
            models.UniqueConstraint(fields=['student', 'month'], name='unique_student_fee_month'),
        ]

    def __str__(self):
        return f'{self.student.name} · {self.month} · {self.amount_paid} / {self.monthly_fee}'

    @property
    def due_amount(self):
        return max(self.monthly_fee - self.amount_paid, Decimal('0.00'))


class StudentFeedback(models.Model):
    class Category(models.TextChoices):
        CLASS_REQUEST = 'class_request', 'অতিরিক্ত ক্লাসের অনুরোধ'
        TOPIC_HELP = 'topic_help', 'কোনো টপিক বুঝতে সমস্যা'
        TEACHER_CLASS = 'teacher_class', 'কোনো ক্লাস বুঝতে সমস্যা'
        BACKUP_CLASS = 'backup_class', 'ব্যাকআপ ক্লাসের অনুরোধ'
        OTHER = 'other', 'অন্যান্য মতামত'

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='feedback_entries',
        verbose_name='শিক্ষার্থী',
    )
    category = models.CharField('মতামতের ধরন', max_length=20, choices=Category.choices)
    message = models.TextField('বিস্তারিত', max_length=1500)
    created_at = models.DateTimeField('জমা দেওয়ার সময়', auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'শিক্ষার্থীর মতামত'
        verbose_name_plural = 'শিক্ষার্থীদের মতামত'

    def __str__(self):
        return f'{self.student.name} · {self.get_category_display()}'


class StudentStudyPreference(models.Model):
    student = models.OneToOneField(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='study_preference',
    )
    hsc_year = models.PositiveSmallIntegerField(default=2027)
    subjects = models.JSONField(default=list, blank=True)
    exam_date = models.DateField('পরবর্তী পরীক্ষার তারিখ', null=True, blank=True)
    preferred_study_hours = models.PositiveSmallIntegerField(default=2)
    session_duration_minutes = models.PositiveSmallIntegerField(default=60)
    break_duration_minutes = models.PositiveSmallIntegerField(default=15)
    weekly_target_hours = models.PositiveSmallIntegerField(default=10)
    rest_days = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'শিক্ষার্থীর পড়ার পছন্দ'
        verbose_name_plural = 'শিক্ষার্থীদের পড়ার পছন্দ'

    def __str__(self):
        return f'{self.student.name} · Study preferences'


class StudentScheduleInterval(models.Model):
    class Kind(models.TextChoices):
        AVAILABLE = 'available', 'পড়ার সময়'
        COLLEGE = 'college', 'কলেজ'
        COACHING = 'coaching', 'কোচিং'

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='study_schedule_intervals',
    )
    weekday = models.PositiveSmallIntegerField(choices=Routine.Weekday.choices)
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.AVAILABLE)
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        ordering = ['weekday', 'start_time']
        indexes = [models.Index(fields=['student', 'weekday'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_time__gt=models.F('start_time')),
                name='study_interval_end_after_start',
            ),
        ]

    def __str__(self):
        return f'{self.student.name} · {self.get_weekday_display()} · {self.start_time}-{self.end_time}'


class StudentChapterProgress(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'শুরু হয়নি'
        IN_PROGRESS = 'in_progress', 'চলছে'
        COMPLETED = 'completed', 'সম্পন্ন'

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='chapter_study_progress',
    )
    subject = models.CharField(max_length=100)
    paper = models.CharField(max_length=100, blank=True)
    chapter = models.CharField(max_length=120)
    topic = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NOT_STARTED)
    is_difficult = models.BooleanField(default=False)
    needs_revision = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['subject', 'paper', 'chapter', 'topic']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'subject', 'paper', 'chapter', 'topic'],
                name='unique_student_chapter_topic_progress',
            ),
        ]
        indexes = [models.Index(fields=['student', 'status'])]

    def __str__(self):
        return f'{self.student.name} · {self.subject} · {self.chapter}'


class TeacherStudyAssignment(models.Model):
    class TaskType(models.TextChoices):
        HOMEWORK = 'homework', 'Homework'
        LEARN = 'learn', 'Learn'
        REVISE = 'revise', 'Revise'
        MCQ = 'mcq', 'MCQ'
        CQ = 'cq', 'CQ'
        NUMERICAL = 'numerical', 'Numerical'
        MOCK_TEST = 'mock_test', 'Mock Test'

    class Priority(models.TextChoices):
        LOW = 'low', 'Low'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'High'
        MANDATORY = 'mandatory', 'Mandatory'

    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='study_assignments',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='teacher_study_assignments',
    )
    class_name = models.CharField(max_length=60, blank=True)
    year_group = models.CharField(max_length=10, choices=BATCH_CHOICES, blank=True)
    subject = models.CharField(max_length=100)
    paper = models.CharField(max_length=100, blank=True)
    chapter = models.CharField(max_length=120, blank=True)
    topic = models.CharField(max_length=120, blank=True)
    task_type = models.CharField(max_length=12, choices=TaskType.choices, default=TaskType.HOMEWORK)
    description = models.CharField(max_length=240)
    instructions = models.TextField(blank=True, max_length=2000)
    assigned_date = models.DateField(default=timezone.localdate)
    deadline = models.DateField()
    estimated_duration_minutes = models.PositiveSmallIntegerField(default=60)
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.NORMAL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['deadline', '-priority', '-created_at']
        indexes = [
            models.Index(fields=['year_group', 'class_name', 'deadline']),
            models.Index(fields=['student', 'deadline']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(student__isnull=False)
                    | (models.Q(class_name__gt='') & models.Q(year_group__gt=''))
                ),
                name='study_assignment_has_target',
            ),
        ]

    def __str__(self):
        return f'{self.subject} · {self.description}'


class TeacherAssignmentProgress(models.Model):
    assignment = models.ForeignKey(
        TeacherStudyAssignment,
        on_delete=models.CASCADE,
        related_name='student_progress',
    )
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='teacher_assignment_progress',
    )
    is_completed = models.BooleanField(default=False)
    reschedule_requested = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['assignment', 'student'],
                name='unique_teacher_assignment_student_progress',
            ),
        ]
        indexes = [models.Index(fields=['student', 'is_completed'])]

    def __str__(self):
        return f'{self.student.name} · {self.assignment}'


class WeeklyStudyPlan(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='weekly_study_plans',
    )
    week_start = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    generation_note = models.CharField(max_length=240, blank=True)
    question_bank = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-week_start']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'week_start'],
                name='unique_student_study_plan_week',
            ),
        ]
        indexes = [models.Index(fields=['student', '-week_start'])]

    def __str__(self):
        return f'{self.student.name} · week of {self.week_start}'


class StudyPlanTask(models.Model):
    class Source(models.TextChoices):
        AI = 'ai', 'AI Recommended'
        TEACHER = 'teacher', 'Teacher Assigned'

    class Status(models.TextChoices):
        NOT_STARTED = 'not_started', 'Not Started'
        IN_PROGRESS = 'in_progress', 'In Progress'
        COMPLETED = 'completed', 'Completed'
        SKIPPED = 'skipped', 'Skipped'
        RESCHEDULED = 'rescheduled', 'Rescheduled'

    plan = models.ForeignKey(WeeklyStudyPlan, on_delete=models.CASCADE, related_name='tasks')
    assignment = models.ForeignKey(
        TeacherStudyAssignment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='planned_tasks',
    )
    source = models.CharField(max_length=10, choices=Source.choices)
    task_type = models.CharField(max_length=12, choices=TeacherStudyAssignment.TaskType.choices)
    subject = models.CharField(max_length=100)
    paper = models.CharField(max_length=100, blank=True)
    chapter = models.CharField(max_length=120, blank=True)
    topic = models.CharField(max_length=120, blank=True)
    description = models.CharField(max_length=240)
    expected_outcome = models.CharField(max_length=240, blank=True)
    recommendation_reason = models.CharField(max_length=240, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    duration_minutes = models.PositiveSmallIntegerField()
    priority = models.CharField(max_length=12, choices=TeacherStudyAssignment.Priority.choices)
    status = models.CharField(max_length=14, choices=Status.choices, default=Status.NOT_STARTED)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_date', 'start_time', '-priority', 'pk']
        indexes = [models.Index(fields=['plan', 'scheduled_date', 'status'])]
        constraints = [
            models.UniqueConstraint(
                fields=['plan', 'assignment'],
                name='unique_assignment_in_study_plan',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(end_time__gt=models.F('start_time'))
                    | models.Q(start_time__isnull=True, end_time__isnull=True)
                ),
                name='study_task_end_after_start',
            ),
        ]

    def __str__(self):
        return f'{self.subject} · {self.description}'


class TopicPracticeSession(models.Model):
    class QuestionType(models.TextChoices):
        CQ = 'cq', 'সৃজনশীল (CQ)'
        MCQ = 'mcq', 'বহুনির্বাচনী (MCQ)'
        KO = 'ko', 'জ্ঞানমূলক (ক)'
        KHO = 'kho', 'অনুধাবনমূলক (খ)'

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='topic_practice_sessions',
    )
    subject = models.CharField(max_length=100)
    paper = models.CharField(max_length=100)
    chapter = models.CharField(max_length=120)
    topic = models.CharField(max_length=160)
    question_type = models.CharField(max_length=4, choices=QuestionType.choices)
    sources = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        indexes = [
            models.Index(fields=['student', '-created_at']),
            models.Index(fields=['student', 'subject', '-created_at']),
        ]

    def __str__(self):
        return f'{self.student.name} · {self.subject} · {self.topic}'


class TopicPracticeQuestion(models.Model):
    class Status(models.TextChoices):
        UNMARKED = 'unmarked', 'এখনো mark করা হয়নি'
        PRACTICED = 'practiced', 'পড়েছি/সমাধান করেছি'
        NEEDS_HELP = 'needs_help', 'সমস্যা হয়েছে'

    session = models.ForeignKey(
        TopicPracticeSession,
        on_delete=models.CASCADE,
        related_name='questions',
    )
    sequence = models.PositiveIntegerField()
    prompt = models.TextField()
    choices = models.JSONField(default=list, blank=True)
    answer = models.TextField(blank=True)
    explanation = models.TextField(blank=True)
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.UNMARKED,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sequence', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'sequence'],
                name='unique_topic_practice_question_sequence',
            ),
        ]

    def __str__(self):
        return f'{self.session.topic} · #{self.sequence}'
