from django.urls import path
from . import views

urlpatterns = [
    # Auth
    path('auth/register/', views.RegisterView.as_view()),
    path('auth/login/', views.LoginView.as_view()),
    path('auth/logout/', views.LogoutView.as_view()),
    path('auth/me/', views.MeView.as_view()),

    # Resumes
    path('uploads/resumes/', views.UploadResumeView.as_view()),
    path('resumes/', views.ResumeListCreateView.as_view()),
    path('resumes/<int:pk>/', views.ResumeDetailView.as_view()),
    path('resumes/<int:pk>/analyze/', views.AnalyzeResumeView.as_view()),

    # Jobs
    path('jobs/', views.JobListCreateView.as_view()),
    path('jobs/<int:pk>/', views.JobDetailView.as_view()),
    path('jobs/<int:pk>/apply/', views.ApplyJobView.as_view()),
    path('applications/', views.MyApplicationsView.as_view()),

    # AI Features
    path('ai/chat/', views.ChatView.as_view()),
    path('ai/roadmap/', views.CareerRoadmapView.as_view()),
    path('ai/skill-gap/', views.SkillGapView.as_view()),

    # Interviews
    path('interviews/', views.InterviewView.as_view()),
    path('interviews/<int:pk>/feedback/', views.InterviewFeedbackView.as_view()),

    # Notifications
    path('notifications/', views.NotificationsView.as_view()),
    path('notifications/<int:pk>/read/', views.NotificationsView.as_view()),

    # Profile
    path('profile/', views.ProfileView.as_view()),
    path('profile/update/', views.ProfileView.as_view()),

    # Admin
    path('admin/users/', views.AdminUsersView.as_view()),
    path('admin/users/<int:pk>/', views.AdminUsersView.as_view()),
    path('admin/stats/', views.AdminStatsView.as_view()),
    path('admin/applications/', views.AdminApplicationsView.as_view()),
    path('admin/applications/<int:pk>/', views.AdminApplicationsView.as_view()),

    # Learning
    path('learn/mcq/', views.MCQView.as_view()),
    path('learn/history/', views.LearningHistoryView.as_view()),
]
