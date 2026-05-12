from django.db import models
from django.utils import timezone


class User(models.Model):
    username = models.CharField(max_length=255, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    first_name = models.CharField(max_length=255, blank=True)
    last_name = models.CharField(max_length=255, blank=True)
    role = models.CharField(max_length=50, default='student')  # student | admin | recruiter
    created_at = models.DateTimeField(default=timezone.now)

    # Required by Django REST Framework's IsAuthenticated permission
    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def is_active(self):
        return True

    def __str__(self):
        return self.username


class AuthToken(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='tokens')
    token = models.CharField(max_length=128, unique=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Token for {self.user.username}"


class Resume(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='resumes')
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=1024, blank=True)
    raw_text = models.TextField(blank=True)
    status = models.CharField(max_length=50, default='pending')
    ats_score = models.FloatField(null=True, blank=True)
    summary = models.TextField(blank=True)
    skills = models.JSONField(default=list, blank=True)
    missing_skills = models.JSONField(default=list, blank=True)
    suggestions = models.JSONField(default=list, blank=True)
    experience = models.JSONField(default=list, blank=True)
    education = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.file_name


class Job(models.Model):
    title = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    location = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    requirements = models.JSONField(default=list, blank=True)
    employment_type = models.CharField(max_length=100, blank=True, default='Full-time')
    posted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='posted_jobs')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.title} @ {self.company}"


class JobApplication(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('reviewing', 'Reviewing'),
        ('shortlisted', 'Shortlisted'),
        ('rejected', 'Rejected'),
        ('offered', 'Offered'),
    ]
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name='applications')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='applications')
    resume = models.ForeignKey(Resume, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending')
    cover_letter = models.TextField(blank=True)
    applied_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('job', 'user')

    def __str__(self):
        return f"{self.user.username} → {self.job.title}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)
    category = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.title


class MockInterview(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='interviews')
    role = models.CharField(max_length=255, blank=True)
    questions = models.JSONField(default=list, blank=True)
    score = models.FloatField(null=True, blank=True)
    feedback = models.TextField(blank=True)
    completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Interview for {self.user.username} ({self.role})"


class ChatMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_messages')
    role = models.CharField(max_length=20)  # user | assistant
    content = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['created_at']


class LearningProgress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='learning')
    topic = models.CharField(max_length=255)
    score = models.IntegerField(default=0)
    total = models.IntegerField(default=0)
    completed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.user.username} - {self.topic}"
