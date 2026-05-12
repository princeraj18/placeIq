import json
import os
import urllib.request as urllib_request
import urllib.error as urllib_error
from datetime import datetime

from django.conf import settings
from django.core.files.storage import default_storage
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .auth import (
    TokenAuthentication, create_token, create_user, invalidate_token,
    serialize_user, verify_user,
)
from .models import (
    ChatMessage, Job, JobApplication, LearningProgress,
    MockInterview, Notification, Resume, User,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _gemini_key():
    return os.getenv('GEMINI_API_KEY', '') or getattr(settings, 'GEMINI_API_KEY', '')


def _call_ai(messages, tools=None, tool_choice=None):
    api_key = _gemini_key()
    if not api_key:
        raise ValueError('NO_API_KEY')

    payload = {'model': 'google/gemini-2.5-flash-preview', 'max_tokens': 2000, 'messages': messages}
    if tools:
        payload['tools'] = tools
    if tool_choice:
        payload['tool_choice'] = tool_choice

    data = json.dumps(payload).encode()
    req = urllib_request.Request(
        'https://ai.gateway.lovable.dev/v1/chat/completions',
        data=data,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )
    with urllib_request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def _extract_tool_args(result):
    try:
        choices = result.get('choices', [])
        if choices:
            message = choices[0].get('message', {})
            tool_calls = message.get('tool_calls', [])
            if tool_calls:
                args = tool_calls[0].get('function', {}).get('arguments')
                return json.loads(args) if args else None
    except Exception:
        pass
    return None


def _extract_text(result):
    try:
        return result['choices'][0]['message']['content']
    except Exception:
        return ''


def _strip_json(text):
    return text.strip().lstrip('```json').lstrip('```').rstrip('```').strip()


def _has_key():
    return bool(_gemini_key())


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        username = data.get('username') or data.get('email', '')
        email = data.get('email', '')
        password = data.get('password', '')
        first_name = data.get('first_name', '') or data.get('displayName', '')
        last_name = data.get('last_name', '')

        if not username or not email or not password:
            return Response({'detail': 'username, email and password are required.'}, status=400)
        if len(password) < 8:
            return Response({'detail': 'Password must be at least 8 characters.'}, status=400)

        user = create_user(username, email, password, first_name, last_name)
        if user is None:
            # Try matching email as username
            try:
                existing = User.objects.get(email=email)
                return Response({'detail': 'An account with this email already exists.'}, status=400)
            except User.DoesNotExist:
                return Response({'detail': 'Username already taken. Try a different one.'}, status=400)

        token = create_token(user)
        return Response({'token': token, 'user': serialize_user(user)}, status=201)


class LoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        identifier = request.data.get('username') or request.data.get('email', '')
        password = request.data.get('password', '')

        if not identifier or not password:
            return Response({'detail': 'Email/username and password are required.'}, status=400)

        # Try username directly
        user = verify_user(identifier, password)

        # Try by email
        if not user:
            try:
                u = User.objects.get(email=identifier)
                user = verify_user(u.username, password)
            except User.DoesNotExist:
                pass

        if not user:
            return Response({'detail': 'Invalid email or password.'}, status=400)

        token = create_token(user)
        return Response({'token': token, 'user': serialize_user(user)})


class LogoutView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        auth = request.META.get('HTTP_AUTHORIZATION', '')
        if ' ' in auth:
            invalidate_token(auth.split(' ', 1)[1])
        return Response(status=204)


class MeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(serialize_user(request.user))

    def patch(self, request):
        user = request.user
        for field in ('first_name', 'last_name', 'email'):
            if field in request.data:
                setattr(user, field, request.data[field])
        user.save()
        return Response(serialize_user(user))


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def _serialize_resume(r, include_raw=False):
    d = {
        'id': r.id,
        'file_name': r.file_name,
        'file_path': r.file_path,
        'status': r.status,
        'ats_score': r.ats_score,
        'summary': r.summary,
        'skills': r.skills or [],
        'missing_skills': r.missing_skills or [],
        'suggestions': r.suggestions or [],
        'experience': r.experience or [],
        'education': r.education or [],
        'created_at': r.created_at.isoformat(),
    }
    if include_raw:
        d['raw_text'] = r.raw_text or ''
    return d


class UploadResumeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response({'detail': 'No file uploaded.'}, status=400)
        if uploaded.size > 10 * 1024 * 1024:
            return Response({'detail': 'File too large (max 10MB).'}, status=400)
        dest_path = os.path.join(
            'resumes', str(request.user.id),
            f"{int(datetime.utcnow().timestamp() * 1000)}-{uploaded.name.replace(' ', '_')}"
        )
        saved_path = default_storage.save(dest_path, uploaded)
        file_url = request.build_absolute_uri(settings.MEDIA_URL + saved_path)
        return Response({'file_path': saved_path, 'file_url': file_url}, status=201)


class ResumeListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        resumes = Resume.objects.filter(user=request.user).order_by('-created_at')
        return Response([_serialize_resume(r) for r in resumes])

    def post(self, request):
        data = request.data
        resume = Resume.objects.create(
            user=request.user,
            file_name=data.get('file_name', 'resume'),
            file_path=data.get('file_path', ''),
            raw_text=(data.get('raw_text', '') or '')[:60000],
            status=data.get('status', 'pending'),
        )
        return Response(_serialize_resume(resume), status=201)


class ResumeDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def _get(self, pk, user):
        try:
            return Resume.objects.get(pk=pk, user=user)
        except Resume.DoesNotExist:
            return None

    def get(self, request, pk):
        r = self._get(pk, request.user)
        if not r:
            return Response({'detail': 'Not found.'}, status=404)
        return Response(_serialize_resume(r, include_raw=True))

    def patch(self, request, pk):
        r = self._get(pk, request.user)
        if not r:
            return Response({'detail': 'Not found.'}, status=404)
        for field in ('file_name', 'status', 'ats_score', 'summary', 'skills',
                      'missing_skills', 'suggestions', 'experience', 'education'):
            if field in request.data:
                setattr(r, field, request.data[field])
        r.save()
        return Response(_serialize_resume(r))

    def delete(self, request, pk):
        r = self._get(pk, request.user)
        if not r:
            return Response({'detail': 'Not found.'}, status=404)
        if r.file_path:
            try:
                default_storage.delete(r.file_path)
            except Exception:
                pass
        r.delete()
        return Response(status=204)


class AnalyzeResumeView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        raw_text = (request.data.get('raw_text') or '').strip()
        if len(raw_text) < 10:
            return Response({'detail': 'raw_text required (min 10 chars).'}, status=400)

        try:
            resume = Resume.objects.get(pk=pk, user=request.user)
        except Resume.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        # Save raw text immediately
        resume.raw_text = raw_text[:60000]
        resume.status = 'analyzing'
        resume.save()

        if not _has_key():
            # Fallback local analysis (no AI key)
            parsed = _local_resume_analysis(raw_text)
        else:
            tool = {
                'type': 'function',
                'function': {
                    'name': 'submit_resume_analysis',
                    'description': 'Submit structured ATS resume analysis.',
                    'parameters': {
                        'type': 'object',
                        'properties': {
                            'ats_score': {'type': 'integer', 'minimum': 0, 'maximum': 100},
                            'summary': {'type': 'string'},
                            'skills': {'type': 'array', 'items': {'type': 'string'}},
                            'missing_skills': {'type': 'array', 'items': {'type': 'string'}},
                            'suggestions': {'type': 'array', 'items': {'type': 'string'}},
                            'experience': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'title': {'type': 'string'},
                                        'company': {'type': 'string'},
                                        'duration': {'type': 'string'},
                                    },
                                },
                            },
                            'education': {
                                'type': 'array',
                                'items': {
                                    'type': 'object',
                                    'properties': {
                                        'degree': {'type': 'string'},
                                        'institution': {'type': 'string'},
                                        'year': {'type': 'string'},
                                    },
                                },
                            },
                        },
                        'required': ['ats_score', 'summary', 'skills', 'missing_skills',
                                     'suggestions', 'experience', 'education'],
                    },
                },
            }
            messages = [
                {
                    'role': 'system',
                    'content': (
                        'You are an expert ATS (Applicant Tracking System) and senior technical recruiter. '
                        'Analyze the resume thoroughly. Give an honest ats_score 0-100. '
                        'skills: all technologies/tools demonstrated. '
                        'missing_skills: important skills absent from the resume for a modern tech role. '
                        'suggestions: 4-6 specific, actionable improvements to the resume. '
                        'Extract all experience and education entries.'
                    ),
                },
                {'role': 'user', 'content': f'Analyze this resume:\n\n{raw_text[:50000]}'},
            ]
            try:
                result = _call_ai(messages, tools=[tool],
                                  tool_choice={'type': 'function', 'function': {'name': 'submit_resume_analysis'}})
                parsed = _extract_tool_args(result)
                if not parsed:
                    parsed = _local_resume_analysis(raw_text)
            except Exception:
                parsed = _local_resume_analysis(raw_text)

        resume.status = 'analyzed'
        resume.ats_score = parsed.get('ats_score', 50)
        resume.summary = parsed.get('summary', '')
        resume.skills = parsed.get('skills', [])
        resume.missing_skills = parsed.get('missing_skills', [])
        resume.suggestions = parsed.get('suggestions', [])
        resume.experience = parsed.get('experience', [])
        resume.education = parsed.get('education', [])
        resume.save()

        Notification.objects.create(
            user=request.user,
            title='Resume analysis complete',
            message=f'Your resume "{resume.file_name}" scored {resume.ats_score}/100.',
            category='resume',
        )
        return Response({'ok': True, 'analysis': parsed})


def _local_resume_analysis(text):
    """Keyword-based fallback analysis when no AI key is configured."""
    text_lower = text.lower()

    tech_skills = [
        'python', 'java', 'javascript', 'typescript', 'react', 'vue', 'angular',
        'node.js', 'django', 'flask', 'fastapi', 'spring', 'sql', 'postgresql',
        'mysql', 'mongodb', 'redis', 'docker', 'kubernetes', 'aws', 'gcp', 'azure',
        'git', 'linux', 'rest api', 'graphql', 'html', 'css', 'c++', 'c#', 'go',
        'rust', 'swift', 'kotlin', 'tensorflow', 'pytorch', 'scikit-learn', 'pandas',
        'numpy', 'machine learning', 'deep learning', 'data analysis', 'tableau',
        'power bi', 'excel', 'agile', 'scrum', 'jira', 'ci/cd', 'jenkins', 'github actions',
    ]

    found = [s for s in tech_skills if s in text_lower]
    common_missing = ['docker', 'kubernetes', 'aws', 'ci/cd', 'typescript', 'graphql']
    missing = [s for s in common_missing if s not in text_lower][:4]

    # Rough scoring
    score = min(90, 30 + len(found) * 4)
    has_numbers = any(c.isdigit() for c in text)
    has_bullets = '•' in text or '-' in text or '*' in text
    has_links = 'github' in text_lower or 'linkedin' in text_lower
    if has_numbers: score += 5
    if has_bullets: score += 5
    if has_links: score += 5
    score = min(95, score)

    suggestions = [
        'Add quantifiable achievements (e.g., "Improved performance by 40%") to each role.',
        'Include a GitHub profile link and relevant project URLs.',
        'Add a concise professional summary at the top of your resume.',
        'Tailor your resume keywords to match each job description.',
        'Keep resume to 1 page for under 3 years experience.',
    ]
    if not has_links:
        suggestions.insert(0, 'Add your GitHub and LinkedIn profile links.')

    return {
        'ats_score': score,
        'summary': f'Resume contains {len(found)} recognizable technical skills. '
                   f'{"Good use of metrics." if has_numbers else "Add more quantifiable results."} '
                   f'(Note: Full AI analysis requires a Gemini API key.)',
        'skills': found[:20],
        'missing_skills': missing,
        'suggestions': suggestions[:5],
        'experience': [],
        'education': [],
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def _serialize_job(job, user=None):
    applied = False
    app_status = None
    if user:
        app = JobApplication.objects.filter(job=job, user=user).first()
        if app:
            applied = True
            app_status = app.status
    return {
        'id': job.id,
        'title': job.title,
        'company': job.company,
        'location': job.location,
        'description': job.description,
        'requirements': job.requirements or [],
        'employment_type': job.employment_type,
        'is_active': job.is_active,
        'posted_by': job.posted_by.username if job.posted_by else '',
        'created_at': job.created_at.isoformat(),
        'applied': applied,
        'app_status': app_status,
    }


class JobListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        search = request.query_params.get('search', '').lower()
        jobs = Job.objects.filter(is_active=True).order_by('-created_at')
        if search:
            jobs = [j for j in jobs if search in j.title.lower() or search in j.company.lower()
                    or search in (j.location or '').lower()]
        else:
            jobs = list(jobs)
        return Response([_serialize_job(j, request.user) for j in jobs])

    def post(self, request):
        if request.user.role not in ('admin', 'recruiter'):
            return Response({'detail': 'Only admins/recruiters can post jobs.'}, status=403)
        data = request.data
        job = Job.objects.create(
            title=data.get('title', ''),
            company=data.get('company', ''),
            location=data.get('location', ''),
            description=data.get('description', ''),
            requirements=data.get('requirements', []),
            employment_type=data.get('employment_type', 'Full-time'),
            posted_by=request.user,
        )
        return Response(_serialize_job(job, request.user), status=201)


class JobDetailView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        return Response(_serialize_job(job, request.user))

    def patch(self, request, pk):
        if request.user.role not in ('admin', 'recruiter'):
            return Response({'detail': 'Forbidden.'}, status=403)
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        for field in ('title', 'company', 'location', 'description',
                      'requirements', 'employment_type', 'is_active'):
            if field in request.data:
                setattr(job, field, request.data[field])
        job.save()
        return Response(_serialize_job(job, request.user))

    def delete(self, request, pk):
        if request.user.role not in ('admin', 'recruiter'):
            return Response({'detail': 'Forbidden.'}, status=403)
        try:
            job = Job.objects.get(pk=pk)
        except Job.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        job.delete()
        return Response(status=204)


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

class ApplyJobView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            job = Job.objects.get(pk=pk, is_active=True)
        except Job.DoesNotExist:
            return Response({'detail': 'Job not found or no longer active.'}, status=404)

        resume = None
        resume_id = request.data.get('resume_id')
        if resume_id:
            try:
                resume = Resume.objects.get(pk=resume_id, user=request.user)
            except Resume.DoesNotExist:
                pass

        app, created = JobApplication.objects.get_or_create(
            job=job, user=request.user,
            defaults={'resume': resume, 'cover_letter': request.data.get('cover_letter', '')},
        )
        if not created:
            return Response({'detail': 'You have already applied to this job.'}, status=400)

        Notification.objects.create(
            user=request.user,
            title=f'Applied to {job.title}',
            message=f'Your application for {job.title} at {job.company} was submitted successfully.',
            category='job',
        )
        return Response({'id': app.id, 'status': app.status}, status=201)


class MyApplicationsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        apps = JobApplication.objects.filter(user=request.user).select_related('job').order_by('-applied_at')
        return Response([{
            'id': a.id,
            'job_id': a.job_id,
            'job_title': a.job.title,
            'company': a.job.company,
            'location': a.job.location,
            'employment_type': a.job.employment_type,
            'status': a.status,
            'applied_at': a.applied_at.isoformat(),
        } for a in apps])


# ---------------------------------------------------------------------------
# AI Career Chat
# ---------------------------------------------------------------------------

class ChatView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        msgs = ChatMessage.objects.filter(user=request.user).order_by('created_at')[:100]
        return Response([{
            'role': m.role,
            'content': m.content,
            'created_at': m.created_at.isoformat(),
        } for m in msgs])

    def post(self, request):
        user_message = (request.data.get('message') or '').strip()
        if not user_message:
            return Response({'detail': 'message required.'}, status=400)

        ChatMessage.objects.create(user=request.user, role='user', content=user_message)

        if not _has_key():
            reply = _local_chat_response(user_message, request.user)
        else:
            history = list(ChatMessage.objects.filter(user=request.user).order_by('created_at')[:20])
            messages = [
                {
                    'role': 'system',
                    'content': (
                        'You are PlaceIQ\'s AI Career Assistant — a helpful, encouraging career coach '
                        'specializing in student placements, resume writing, interview prep, and skill development. '
                        'Give concise, actionable advice. Use bullet points when helpful. '
                        f'The user\'s name is {request.user.first_name or request.user.username}.'
                    ),
                }
            ] + [{'role': m.role, 'content': m.content} for m in history]

            try:
                result = _call_ai(messages)
                reply = _extract_text(result) or 'Sorry, I could not generate a response right now.'
            except Exception as e:
                reply = _local_chat_response(user_message, request.user)

        ChatMessage.objects.create(user=request.user, role='assistant', content=reply)
        return Response({'reply': reply})

    def delete(self, request):
        ChatMessage.objects.filter(user=request.user).delete()
        return Response(status=204)


def _local_chat_response(message, user):
    """Rule-based fallback chat when no API key is set."""
    msg = message.lower()
    name = user.first_name or user.username

    if any(w in msg for w in ['resume', 'cv', 'ats']):
        return (
            f"Hi {name}! Here are key resume tips:\n\n"
            "• **Quantify everything** — e.g., 'Reduced load time by 40%' beats 'Improved performance'\n"
            "• **Match keywords** from the job description — ATS systems scan for these\n"
            "• **Keep it to 1 page** if under 3 years experience\n"
            "• **Add GitHub & LinkedIn** links at the top\n"
            "• **Action verbs** — Built, Designed, Led, Implemented, Optimized\n\n"
            "Upload your resume in the Resumes section for a full ATS score! 🎯\n\n"
            "*(Add a GEMINI_API_KEY to .env for full AI-powered advice)*"
        )
    elif any(w in msg for w in ['interview', 'question', 'prepare']):
        return (
            f"Great question, {name}! Interview preparation tips:\n\n"
            "• **STAR method** — Situation, Task, Action, Result for behavioral questions\n"
            "• **Research the company** — Know their product, mission, and recent news\n"
            "• **Prepare 3-5 stories** that showcase leadership, problem-solving, and teamwork\n"
            "• **Ask thoughtful questions** — 'What does success look like in this role?'\n"
            "• **Practice out loud** — Use our Mock Interview feature!\n\n"
            "Head to the Interview section to practice with AI-generated questions 🎤"
        )
    elif any(w in msg for w in ['skill', 'learn', 'course', 'roadmap']):
        return (
            f"Skills to focus on, {name}:\n\n"
            "**For Software Engineering:**\n"
            "• DSA (LeetCode — 100+ problems)\n"
            "• System Design (Grokking the System Design Interview)\n"
            "• One framework deeply (React/Django/Spring)\n\n"
            "**For Data Science:**\n"
            "• Python + Pandas + NumPy\n"
            "• SQL (very important!)\n"
            "• ML fundamentals (scikit-learn)\n\n"
            "Use the Roadmap Generator for a personalized learning path! 🗺️"
        )
    elif any(w in msg for w in ['salary', 'negotiat', 'offer', 'package']):
        return (
            f"Salary negotiation advice, {name}:\n\n"
            "• **Never give a number first** — ask what the role's budget is\n"
            "• **Research market rates** — use Levels.fyi, Glassdoor, LinkedIn Salary\n"
            "• **Negotiate the whole package** — base, bonus, equity, learning budget\n"
            "• **Always get the offer in writing** before making any decisions\n"
            "• **It's OK to ask for time** — 'Can I have 48 hours to consider this?'\n\n"
            "Remember: negotiating is expected and professional! 💪"
        )
    elif any(w in msg for w in ['job', 'placement', 'apply', 'company']):
        return (
            f"Job search strategy, {name}:\n\n"
            "• **Apply broadly** — aim for 5-10 applications per week\n"
            "• **Referrals work best** — 40% of hires come through referrals\n"
            "• **LinkedIn is key** — connect with employees at target companies\n"
            "• **Tailor your resume** for each application (at least the summary)\n"
            "• **Follow up** after applying and after interviews\n\n"
            "Browse open positions in the Jobs section! 💼"
        )
    else:
        return (
            f"Hi {name}! I'm your PlaceIQ AI Career Assistant 🤖\n\n"
            "I can help you with:\n"
            "• **Resume tips** — ATS optimization, formatting, content\n"
            "• **Interview prep** — STAR method, common questions, behavioral answers\n"
            "• **Skill roadmaps** — What to learn for your target role\n"
            "• **Job search** — Application strategy, networking, referrals\n"
            "• **Salary negotiation** — How to get the best offer\n\n"
            "What would you like help with today?\n\n"
            "*(Add a GEMINI_API_KEY to .env for full AI-powered responses)*"
        )


# ---------------------------------------------------------------------------
# AI Career Roadmap
# ---------------------------------------------------------------------------

class CareerRoadmapView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        target_role = (request.data.get('target_role') or '').strip()
        current_skills = request.data.get('current_skills', [])
        experience_level = request.data.get('experience_level', 'beginner')

        if not target_role:
            return Response({'detail': 'target_role required.'}, status=400)

        if not _has_key():
            return Response(_local_roadmap(target_role, experience_level, current_skills))

        messages = [
            {
                'role': 'system',
                'content': (
                    'You are a senior technical career coach. Generate a detailed, actionable learning roadmap. '
                    'Return ONLY a valid JSON object with keys: '
                    '"title" (string), "phases" (array of {phase: string, duration: string, '
                    'topics: array of strings, resources: array of strings}), '
                    '"timeline" (string), "key_skills" (array of strings). No markdown, no extra text.'
                ),
            },
            {
                'role': 'user',
                'content': f'Create a learning roadmap for: {target_role}. '
                           f'Current skills: {", ".join(current_skills) or "none"}. '
                           f'Level: {experience_level}.',
            },
        ]
        try:
            result = _call_ai(messages)
            text = _strip_json(_extract_text(result))
            roadmap = json.loads(text)
        except (json.JSONDecodeError, Exception):
            roadmap = _local_roadmap(target_role, experience_level, current_skills)

        return Response(roadmap)


def _local_roadmap(role, level, current_skills):
    role_lower = role.lower()
    if 'data' in role_lower or 'ml' in role_lower or 'machine' in role_lower:
        phases = [
            {'phase': 'Foundations', 'duration': '6-8 weeks',
             'topics': ['Python basics', 'NumPy & Pandas', 'Data visualization', 'Statistics fundamentals'],
             'resources': ['Python.org docs', 'Kaggle Learn', 'Khan Academy Stats']},
            {'phase': 'Core ML', 'duration': '8-10 weeks',
             'topics': ['Supervised learning', 'Unsupervised learning', 'scikit-learn', 'Model evaluation'],
             'resources': ['Hands-On ML (Géron)', 'fast.ai', 'Kaggle competitions']},
            {'phase': 'Advanced & Deployment', 'duration': '8-10 weeks',
             'topics': ['Deep learning (PyTorch/TensorFlow)', 'MLOps basics', 'SQL for data', 'Cloud ML (AWS SageMaker)'],
             'resources': ['Deep Learning Specialization (Coursera)', 'Full Stack Deep Learning']},
        ]
        key_skills = ['Python', 'SQL', 'scikit-learn', 'TensorFlow/PyTorch', 'Pandas', 'Statistics', 'Data Visualization']
        timeline = '6-8 months'
    elif 'frontend' in role_lower or 'react' in role_lower or 'ui' in role_lower:
        phases = [
            {'phase': 'HTML, CSS & JS Fundamentals', 'duration': '4-6 weeks',
             'topics': ['HTML5 semantics', 'CSS Flexbox & Grid', 'JavaScript ES6+', 'DOM manipulation'],
             'resources': ['MDN Web Docs', 'The Odin Project', 'javascript.info']},
            {'phase': 'React & Modern Tools', 'duration': '6-8 weeks',
             'topics': ['React hooks & state', 'React Router', 'TypeScript basics', 'REST API integration'],
             'resources': ['React docs (react.dev)', 'TypeScript Handbook', 'Scrimba React course']},
            {'phase': 'Production Skills', 'duration': '6-8 weeks',
             'topics': ['Testing (Jest, RTL)', 'Performance optimization', 'Webpack/Vite', 'CI/CD basics'],
             'resources': ['Testing Library docs', 'Web.dev', 'Frontend Masters']},
        ]
        key_skills = ['HTML/CSS', 'JavaScript', 'TypeScript', 'React', 'Git', 'REST APIs', 'Testing']
        timeline = '4-6 months'
    else:
        phases = [
            {'phase': 'Core Programming', 'duration': '6-8 weeks',
             'topics': ['Chosen language (Python/Java/JS)', 'OOP & design patterns', 'Git & GitHub', 'CLI & Linux basics'],
             'resources': ['Official language docs', 'CS50 (Harvard)', 'Pro Git book']},
            {'phase': 'Backend & Databases', 'duration': '8-10 weeks',
             'topics': ['REST API design', 'SQL databases (PostgreSQL)', 'Authentication & security', 'One backend framework'],
             'resources': ['Django/Spring/Express docs', 'PostgreSQL Tutorial', 'OWASP Top 10']},
            {'phase': 'System Design & DevOps', 'duration': '6-8 weeks',
             'topics': ['System design fundamentals', 'Docker & containers', 'Cloud basics (AWS/GCP)', 'CI/CD pipelines'],
             'resources': ['Grokking System Design', 'Docker docs', 'AWS Free Tier']},
        ]
        key_skills = ['Python/Java', 'SQL', 'REST APIs', 'Docker', 'Git', 'System Design', 'Cloud']
        timeline = '5-7 months'

    return {
        'title': f'{role} — Learning Roadmap',
        'phases': phases,
        'timeline': timeline,
        'key_skills': key_skills,
        'note': 'Add GEMINI_API_KEY for a fully personalized AI-generated roadmap.',
    }


# ---------------------------------------------------------------------------
# AI Skill Gap
# ---------------------------------------------------------------------------

class SkillGapView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        target_role = (request.data.get('target_role') or '').strip()
        resume_id = request.data.get('resume_id')

        if not target_role:
            return Response({'detail': 'target_role required.'}, status=400)

        current_skills = []
        if resume_id:
            try:
                resume = Resume.objects.get(pk=resume_id, user=request.user)
                current_skills = resume.skills or []
            except Resume.DoesNotExist:
                pass

        if not _has_key():
            return Response(_local_skill_gap(target_role, current_skills))

        messages = [
            {
                'role': 'system',
                'content': (
                    'You are a technical recruiter expert. Analyze skill gaps. '
                    'Return ONLY JSON with: '
                    '"matched_skills" (array of strings), '
                    '"missing_skills" (array of {skill: string, priority: "high"|"medium"|"low", why: string}), '
                    '"match_score" (integer 0-100), '
                    '"recommendation" (string). No markdown.'
                ),
            },
            {
                'role': 'user',
                'content': f'Target role: {target_role}. Current skills: {", ".join(current_skills) or "none provided"}.',
            },
        ]
        try:
            result = _call_ai(messages)
            text = _strip_json(_extract_text(result))
            data = json.loads(text)
        except Exception:
            data = _local_skill_gap(target_role, current_skills)

        return Response(data)


def _local_skill_gap(role, current_skills):
    current_lower = [s.lower() for s in current_skills]
    role_lower = role.lower()

    role_map = {
        'frontend': ['html', 'css', 'javascript', 'typescript', 'react', 'vue', 'git', 'rest api', 'testing', 'responsive design'],
        'backend': ['python', 'java', 'node.js', 'sql', 'rest api', 'docker', 'git', 'authentication', 'databases', 'aws'],
        'fullstack': ['html', 'css', 'javascript', 'react', 'node.js', 'sql', 'git', 'docker', 'rest api', 'deployment'],
        'data': ['python', 'sql', 'pandas', 'numpy', 'scikit-learn', 'statistics', 'data visualization', 'machine learning', 'jupyter'],
        'ml': ['python', 'tensorflow', 'pytorch', 'scikit-learn', 'statistics', 'linear algebra', 'sql', 'mlops', 'data processing'],
        'devops': ['linux', 'docker', 'kubernetes', 'ci/cd', 'terraform', 'aws', 'monitoring', 'bash scripting', 'git'],
    }

    required = []
    for key, skills in role_map.items():
        if key in role_lower:
            required = skills
            break
    if not required:
        required = ['python', 'git', 'sql', 'rest api', 'docker', 'communication', 'problem solving', 'linux']

    matched = [s for s in current_lower if any(r in s or s in r for r in required)]
    missing_skills_raw = [r for r in required if not any(r in c or c in r for c in current_lower)]

    prio_map = {0: 'high', 1: 'high', 2: 'medium', 3: 'medium', 4: 'low', 5: 'low'}
    missing = [
        {'skill': s, 'priority': prio_map.get(i, 'low'), 'why': f'Essential for {role} positions in most companies.'}
        for i, s in enumerate(missing_skills_raw[:6])
    ]

    score = int((len(matched) / max(len(required), 1)) * 100)

    return {
        'matched_skills': matched,
        'missing_skills': missing,
        'match_score': score,
        'recommendation': (
            f'You match {score}% of typical {role} requirements. '
            f'Focus on acquiring {missing[0]["skill"] if missing else "advanced skills"} first. '
            'Add a GEMINI_API_KEY for a detailed AI-powered gap analysis.'
        ),
    }


# ---------------------------------------------------------------------------
# Mock Interview
# ---------------------------------------------------------------------------

class InterviewView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        interviews = MockInterview.objects.filter(user=request.user).order_by('-created_at')[:20]
        return Response([{
            'id': i.id,
            'role': i.role,
            'score': i.score,
            'feedback': i.feedback,
            'completed': i.completed,
            'questions': i.questions,
            'created_at': i.created_at.isoformat(),
        } for i in interviews])

    def post(self, request):
        role = (request.data.get('role') or 'Software Engineer').strip()
        num_questions = min(int(request.data.get('num_questions', 5)), 10)

        if not _has_key():
            questions = _local_interview_questions(role, num_questions)
        else:
            messages = [
                {
                    'role': 'system',
                    'content': (
                        f'You are a senior technical interviewer. Generate {num_questions} realistic interview questions for a {role} role. '
                        f'Mix behavioral, technical, and situational questions. '
                        f'Return ONLY JSON: {{"questions": [array of {num_questions} question strings]}}. No markdown.'
                    ),
                },
                {'role': 'user', 'content': f'Generate {num_questions} interview questions for: {role}'},
            ]
            try:
                result = _call_ai(messages)
                text = _strip_json(_extract_text(result))
                data = json.loads(text)
                questions = data.get('questions', [])
                if not questions:
                    questions = _local_interview_questions(role, num_questions)
            except Exception:
                questions = _local_interview_questions(role, num_questions)

        interview = MockInterview.objects.create(
            user=request.user,
            role=role,
            questions=[{'question': q, 'answer': '', 'feedback': ''} for q in questions],
        )
        return Response({'id': interview.id, 'role': interview.role, 'questions': questions}, status=201)


def _local_interview_questions(role, n):
    role_lower = role.lower()

    behavioral = [
        'Tell me about yourself and your journey into this field.',
        'Describe a challenging project you worked on. What was your approach?',
        'Give an example of a time you worked effectively in a team.',
        'Tell me about a time you disagreed with a colleague. How did you handle it?',
        'What is your greatest technical achievement so far?',
        'Describe a situation where you had to learn a new technology quickly.',
    ]

    technical_map = {
        'frontend': [
            'What is the difference between `==` and `===` in JavaScript?',
            'Explain the concept of closures in JavaScript with an example.',
            'What are React hooks and why were they introduced?',
            'How does the browser render a webpage? Walk me through the critical rendering path.',
            'Explain CSS specificity and how to resolve conflicts.',
        ],
        'backend': [
            'Explain REST API design principles and HTTP methods.',
            'What is database indexing and when should you use it?',
            'What is the difference between SQL and NoSQL databases?',
            'Explain authentication vs authorization. How do JWTs work?',
            'What is N+1 query problem and how do you solve it?',
        ],
        'data': [
            'Explain the difference between supervised and unsupervised learning.',
            'What is overfitting and how do you prevent it?',
            'Explain the bias-variance tradeoff.',
            'What metrics would you use to evaluate a classification model?',
            'How would you handle missing data in a dataset?',
        ],
        'default': [
            'What are the SOLID principles in software design?',
            'Explain time and space complexity. What is Big O notation?',
            'What is a REST API? How does it differ from GraphQL?',
            'Explain what happens when you type a URL in the browser.',
            'What is version control? How does Git branching work?',
        ],
    }

    tech_qs = technical_map.get(
        next((k for k in technical_map if k in role_lower), 'default'),
        technical_map['default']
    )

    all_qs = tech_qs + behavioral
    return all_qs[:n]


class InterviewFeedbackView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            interview = MockInterview.objects.get(pk=pk, user=request.user)
        except MockInterview.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        answers = request.data.get('answers', [])
        if not answers:
            return Response({'detail': 'answers required.'}, status=400)

        if not _has_key():
            feedback_data = _local_interview_feedback(answers, interview.role)
        else:
            qa_text = '\n\n'.join([f"Q: {a.get('question', '')}\nA: {a.get('answer', '')}" for a in answers])
            messages = [
                {
                    'role': 'system',
                    'content': (
                        'You are an expert technical interviewer. Evaluate the candidate\'s interview answers critically but fairly. '
                        'Return ONLY JSON: {"overall_score": 0-100, "overall_feedback": string, '
                        '"per_question": [{"feedback": string, "score": 0-10, "improvement": string}]}. No markdown.'
                    ),
                },
                {'role': 'user', 'content': f'Role: {interview.role}\n\n{qa_text}'},
            ]
            try:
                result = _call_ai(messages)
                text = _strip_json(_extract_text(result))
                feedback_data = json.loads(text)
            except Exception:
                feedback_data = _local_interview_feedback(answers, interview.role)

        interview.score = feedback_data.get('overall_score', 0)
        interview.feedback = feedback_data.get('overall_feedback', '')
        interview.completed = True

        questions = interview.questions
        per_q = feedback_data.get('per_question', [])
        for i, q in enumerate(questions):
            if i < len(answers):
                q['answer'] = answers[i].get('answer', '')
            if i < len(per_q):
                q['feedback'] = per_q[i].get('feedback', '')
                q['score'] = per_q[i].get('score', 0)
        interview.questions = questions
        interview.save()

        Notification.objects.create(
            user=request.user,
            title='Interview feedback ready',
            message=f'Your {interview.role} interview scored {interview.score}/100.',
            category='interview',
        )
        return Response(feedback_data)


def _local_interview_feedback(answers, role):
    per_q = []
    total = 0
    for a in answers:
        answer = (a.get('answer') or '').strip()
        words = len(answer.split())
        if words < 5:
            score = 2
            fb = 'Very brief answer. Try to elaborate with specific examples using the STAR method.'
        elif words < 30:
            score = 5
            fb = 'Decent start but could be more detailed. Add a specific example or quantifiable result.'
        elif words < 80:
            score = 7
            fb = 'Good answer with reasonable detail. Consider adding concrete metrics or outcomes.'
        else:
            score = 8
            fb = 'Strong, detailed answer. Well done!'
        total += score
        per_q.append({'feedback': fb, 'score': score, 'improvement': 'Use the STAR method for behavioral answers.'})

    overall = int((total / max(len(answers) * 10, 1)) * 100)
    return {
        'overall_score': overall,
        'overall_feedback': (
            f'You scored {overall}/100 in this {role} mock interview. '
            + ('Great performance! Keep practicing to maintain this standard.' if overall >= 70
               else 'Good effort! Focus on adding specific examples and measurable outcomes to your answers. '
                    'Practice the STAR method (Situation, Task, Action, Result).')
            + ' Add a GEMINI_API_KEY for detailed AI feedback on each answer.'
        ),
        'per_question': per_q,
    }


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifs = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
        return Response([{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'is_read': n.is_read,
            'category': n.category,
            'created_at': n.created_at.isoformat(),
        } for n in notifs])

    def patch(self, request, pk=None):
        if pk:
            Notification.objects.filter(user=request.user).update(is_read=True)
        else:
            Notification.objects.filter(user=request.user).update(is_read=True)
        return Response({'ok': True})


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProfileView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        resumes = Resume.objects.filter(user=user)
        best = resumes.order_by('-ats_score').first()
        return Response({
            **serialize_user(user),
            'resume_count': resumes.count(),
            'best_ats_score': best.ats_score if best else None,
            'applications_count': JobApplication.objects.filter(user=user).count(),
            'interviews_count': MockInterview.objects.filter(user=user, completed=True).count(),
            'learning_count': LearningProgress.objects.filter(user=user).count(),
        })

    def patch(self, request):
        user = request.user
        for field in ('first_name', 'last_name', 'email'):
            if field in request.data:
                setattr(user, field, request.data[field])
        user.save()
        return Response(serialize_user(user))


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdminUsersView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'admin':
            return Response({'detail': 'Forbidden.'}, status=403)
        users = User.objects.all().order_by('-created_at')
        return Response([{
            **serialize_user(u),
            'resume_count': Resume.objects.filter(user=u).count(),
            'app_count': JobApplication.objects.filter(user=u).count(),
        } for u in users])

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'detail': 'Forbidden.'}, status=403)
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        if 'role' in request.data:
            user.role = request.data['role']
            user.save()
        return Response(serialize_user(user))


class AdminStatsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'admin':
            return Response({'detail': 'Forbidden.'}, status=403)
        from django.db.models import Avg
        avg = Resume.objects.filter(status='analyzed').aggregate(avg=Avg('ats_score'))['avg']
        return Response({
            'total_users': User.objects.count(),
            'total_resumes': Resume.objects.count(),
            'total_jobs': Job.objects.count(),
            'total_applications': JobApplication.objects.count(),
            'analyzed_resumes': Resume.objects.filter(status='analyzed').count(),
            'avg_ats_score': round(avg, 1) if avg else 0,
            'pending_applications': JobApplication.objects.filter(status='pending').count(),
            'completed_interviews': MockInterview.objects.filter(completed=True).count(),
        })


class AdminApplicationsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'admin':
            return Response({'detail': 'Forbidden.'}, status=403)
        apps = JobApplication.objects.select_related('job', 'user').order_by('-applied_at')[:100]
        return Response([{
            'id': a.id,
            'job_title': a.job.title,
            'company': a.job.company,
            'applicant': f'{a.user.first_name} {a.user.last_name}'.strip() or a.user.username,
            'email': a.user.email,
            'status': a.status,
            'applied_at': a.applied_at.isoformat(),
        } for a in apps])

    def patch(self, request, pk):
        if request.user.role != 'admin':
            return Response({'detail': 'Forbidden.'}, status=403)
        try:
            app = JobApplication.objects.get(pk=pk)
        except JobApplication.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)
        if 'status' in request.data:
            app.status = request.data['status']
            app.save()
            Notification.objects.create(
                user=app.user,
                title=f'Application update: {app.job.title}',
                message=f'Your application for {app.job.title} at {app.job.company} is now {app.status}.',
                category='job',
            )
        return Response({'id': app.id, 'status': app.status})


# ---------------------------------------------------------------------------
# Learning / MCQ
# ---------------------------------------------------------------------------

class MCQView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        topic = (request.data.get('topic') or 'General Knowledge').strip()
        count = min(int(request.data.get('count', 5)), 10)

        if not _has_key():
            return Response(_local_mcq(topic, count))

        messages = [
            {
                'role': 'system',
                'content': (
                    f'You are an expert quiz generator. Create {count} multiple-choice questions on the topic: {topic}. '
                    'Each question must have exactly 4 options. '
                    'Return ONLY JSON: {"questions": [{"question": string, "options": [4 strings], '
                    '"answer": integer (0-3 index of correct option), "explanation": string}]}. No markdown.'
                ),
            },
            {'role': 'user', 'content': f'Generate {count} MCQ questions on: {topic}'},
        ]
        try:
            result = _call_ai(messages)
            text = _strip_json(_extract_text(result))
            data = json.loads(text)
            if not data.get('questions'):
                data = _local_mcq(topic, count)
        except Exception:
            data = _local_mcq(topic, count)

        return Response(data)

    def patch(self, request):
        topic = request.data.get('topic', 'quiz')
        score = int(request.data.get('score', 0))
        total = int(request.data.get('total', 0))
        LearningProgress.objects.create(user=request.user, topic=topic, score=score, total=total)
        return Response({'ok': True})


def _local_mcq(topic, count):
    banks = {
        'python': [
            {'question': 'Which of the following is used to define a function in Python?',
             'options': ['function', 'def', 'func', 'define'], 'answer': 1,
             'explanation': '`def` is the keyword used to define a function in Python.'},
            {'question': 'What does the `len()` function return?',
             'options': ['The sum of elements', 'The number of elements', 'The last element', 'The type of the list'],
             'answer': 1, 'explanation': '`len()` returns the number of items in an object.'},
            {'question': 'Which data type is immutable in Python?',
             'options': ['List', 'Dictionary', 'Set', 'Tuple'], 'answer': 3,
             'explanation': 'Tuples are immutable — they cannot be changed after creation.'},
            {'question': 'What is the output of `2 ** 3` in Python?',
             'options': ['6', '8', '5', '9'], 'answer': 1,
             'explanation': '`**` is the exponentiation operator. 2³ = 8.'},
            {'question': 'Which keyword is used to handle exceptions?',
             'options': ['catch', 'except', 'handle', 'error'], 'answer': 1,
             'explanation': 'Python uses `except` blocks (in a `try/except` statement) to handle exceptions.'},
        ],
        'javascript': [
            {'question': 'Which method adds an element to the end of an array?',
             'options': ['push()', 'pop()', 'shift()', 'unshift()'], 'answer': 0,
             'explanation': '`push()` adds one or more elements to the end of an array.'},
            {'question': 'What does `===` check in JavaScript?',
             'options': ['Only value', 'Only type', 'Value and type', 'Reference equality'],
             'answer': 2, 'explanation': '`===` is strict equality — it checks both value and type.'},
            {'question': 'What is a closure in JavaScript?',
             'options': ['A loop construct', 'A function with access to its outer scope', 'An error handler', 'A promise'],
             'answer': 1, 'explanation': 'A closure is a function that has access to variables from its outer (enclosing) scope.'},
            {'question': 'Which of these is NOT a JavaScript data type?',
             'options': ['undefined', 'boolean', 'float', 'symbol'], 'answer': 2,
             'explanation': 'JavaScript has no `float` type. Numbers are all the `number` type.'},
            {'question': 'What does `Array.prototype.map()` return?',
             'options': ['The original array', 'A new array', 'A boolean', 'undefined'],
             'answer': 1, 'explanation': '`map()` returns a new array with the results of calling a function on each element.'},
        ],
        'sql': [
            {'question': 'Which SQL statement is used to retrieve data?',
             'options': ['GET', 'SELECT', 'FETCH', 'READ'], 'answer': 1,
             'explanation': '`SELECT` is used to query data from a database.'},
            {'question': 'Which JOIN returns all rows from both tables?',
             'options': ['INNER JOIN', 'LEFT JOIN', 'RIGHT JOIN', 'FULL OUTER JOIN'], 'answer': 3,
             'explanation': 'FULL OUTER JOIN returns all rows from both tables, with NULLs where no match exists.'},
            {'question': 'What does GROUP BY do?',
             'options': ['Sorts results', 'Groups rows with the same values', 'Filters rows', 'Joins tables'],
             'answer': 1, 'explanation': 'GROUP BY groups rows that have the same values, often used with aggregate functions.'},
            {'question': 'Which aggregate function counts non-NULL values?',
             'options': ['SUM()', 'COUNT()', 'AVG()', 'MAX()'], 'answer': 1,
             'explanation': 'COUNT() counts the number of non-NULL values in a column.'},
            {'question': 'What does DISTINCT do in a SELECT statement?',
             'options': ['Sorts results', 'Removes duplicate rows', 'Filters NULLs', 'Limits results'],
             'answer': 1, 'explanation': 'DISTINCT removes duplicate rows from query results.'},
        ],
    }

    topic_lower = topic.lower()
    bank = next((v for k, v in banks.items() if k in topic_lower), None)

    if bank:
        import random
        questions = bank[:count]
    else:
        questions = [
            {'question': f'What is a key principle of {topic}?',
             'options': ['Simplicity', 'Complexity', 'Redundancy', 'Ambiguity'], 'answer': 0,
             'explanation': f'Simplicity is a core principle in {topic}.'},
            {'question': f'Which approach is best when learning {topic}?',
             'options': ['Read passively', 'Practice actively', 'Memorize only', 'Skip fundamentals'], 'answer': 1,
             'explanation': 'Active practice is the most effective way to learn any technical subject.'},
        ]
        questions = (questions * 5)[:count]

    return {
        'questions': questions[:count],
        'note': 'Add GEMINI_API_KEY for AI-generated questions on any topic.',
    }


class LearningHistoryView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        history = LearningProgress.objects.filter(user=request.user).order_by('-completed_at')[:50]
        return Response([{
            'id': h.id,
            'topic': h.topic,
            'score': h.score,
            'total': h.total,
            'percentage': round(h.score / h.total * 100) if h.total else 0,
            'completed_at': h.completed_at.isoformat(),
        } for h in history])
