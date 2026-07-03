from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib import messages
from django.db.models import Q
from accounts.models import User
from alumni.models import School
from connections.models import Connection

def home(request):
    # If user is already authenticated, redirect to dashboard
    # Otherwise, redirect to login page
    if request.user.is_authenticated:
        return redirect('dashboard')
    return redirect('login')

def login_view(request):
    """Custom login view that handles phone_or_email authentication"""
    if request.user.is_authenticated:
        return redirect('dashboard')
    
    if request.method == 'POST':
        phone_or_email = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        
        # Try to authenticate
        user = authenticate(request, username=phone_or_email, password=password)
        
        if user is not None:
            login(request, user)
            return redirect('dashboard')
        else:
            # Check if user exists for better error messaging
            try:
                User.objects.get(phone_or_email=phone_or_email)
                messages.error(request, 'Invalid password. Please check your password and try again.')
            except User.DoesNotExist:
                messages.error(request, f'No account found for {phone_or_email}. Please register first.')
    
    return render(request, 'login.html')

def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        phone_or_email = request.POST.get('phone_or_email')
        full_name = request.POST.get('full_name')
        password = request.POST.get('password')
        agree_terms = request.POST.get('agree_terms')

        if not agree_terms:
            messages.error(request, 'You must accept the Terms of Use, Privacy and Data Usage Policy to create an account.')
            return render(request, 'register.html')

        try:
            user = User.objects.create_user(phone_or_email, password, full_name=full_name)
            login(request, user)
            return redirect('dashboard')
        except Exception as e:
            messages.error(request, f'Registration failed: {str(e)}')
            return render(request, 'register.html')
    return render(request, 'register.html')

def terms(request):
    return render(request, 'terms.html')

def dashboard(request):
    if not request.user.is_authenticated:
        return redirect('login')

    user = request.user
    accepted_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='accepted')
    ).select_related('requester', 'receiver')

    pending_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='pending')
    ).select_related('requester', 'receiver')

    cohort_users = User.objects.none()
    cohort_count = 0
    if user.secondary_school and user.secondary_completion_year:
        cohort_users = User.objects.filter(
            secondary_school=user.secondary_school,
            secondary_completion_year=user.secondary_completion_year
        ).exclude(id=user.id)[:4]
        cohort_count = User.objects.filter(
            secondary_school=user.secondary_school,
            secondary_completion_year=user.secondary_completion_year
        ).exclude(id=user.id).count()

    connections_count = accepted_connections.count()
    pending_count = pending_connections.count()

    return render(request, 'dashboard.html', {
        'user': user,
        'connections_count': connections_count,
        'pending_count': pending_count,
        'cohort_count': cohort_count,
        'cohort_users': cohort_users,
        'identity_score': user.identity_score,
        'identity_score_suggestions': user.identity_score_suggestions[:4],
        'accepted_connections': accepted_connections,
    })

def profile(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method == 'POST':
        user = request.user
        user.full_name = request.POST.get('full_name', user.full_name)
        user.bio = request.POST.get('bio', user.bio)
        user.current_role = request.POST.get('current_role', user.current_role)
        user.current_location = request.POST.get('current_location', user.current_location)
        
        # Educational background
        primary_school_id = request.POST.get('primary_school')
        if primary_school_id:
            try:
                user.primary_school = School.objects.get(id=primary_school_id, school_type='primary')
            except School.DoesNotExist:
                user.primary_school = None
        else:
            user.primary_school = None
        user.primary_completion_year = request.POST.get('primary_completion_year') or None
        
        secondary_school_id = request.POST.get('secondary_school')
        if secondary_school_id:
            try:
                user.secondary_school = School.objects.get(id=secondary_school_id, school_type='secondary')
            except School.DoesNotExist:
                user.secondary_school = None
        else:
            user.secondary_school = None
        user.secondary_completion_year = request.POST.get('secondary_completion_year') or None
        
        user.high_school = request.POST.get('high_school', user.high_school)
        user.high_school_completion_year = request.POST.get('high_school_completion_year') or None

        tertiary_school_id = request.POST.get('tertiary_school')
        if tertiary_school_id:
            try:
                user.tertiary_school = School.objects.get(id=tertiary_school_id, school_type='university')
            except School.DoesNotExist:
                user.tertiary_school = None
        else:
            user.tertiary_school = None
        user.tertiary_completion_year = request.POST.get('tertiary_completion_year') or None

        user.employment_status = request.POST.get('employment_status', user.employment_status)
        user.company_name = request.POST.get('company_name', user.company_name)

        # Handle avatar upload
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
        user.save()
        messages.success(request, 'Profile updated successfully!')
        return redirect('dashboard')
    primary_schools = School.objects.filter(school_type='primary').order_by('name')
    secondary_schools = School.objects.filter(school_type='secondary').order_by('name')
    tertiary_schools = School.objects.filter(school_type='university').order_by('name')
    return render(request, 'profile.html', {
        'user': request.user,
        'primary_schools': primary_schools,
        'secondary_schools': secondary_schools,
        'tertiary_schools': tertiary_schools,
        'employment_status_choices': User.EMPLOYMENT_STATUS_CHOICES,
    })

def schools(request):
    if not request.user.is_authenticated:
        return redirect('login')
    # For now, returning empty opportunities list as template has mock data
    # In future, this can be populated from an Opportunities model
    return render(request, 'schools.html', {'user': request.user})

def connections(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user
    accepted_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='accepted')
    ).select_related('requester', 'receiver')
    pending_connections = Connection.objects.filter(
        (Q(requester=user) | Q(receiver=user)) & Q(status='pending')
    ).select_related('requester', 'receiver')

    return render(request, 'connections.html', {
        'connections': accepted_connections,
        'pending_connections': pending_connections,
        'accepted_count': accepted_connections.count(),
        'pending_count': pending_connections.count(),
    })

def select_school(request, school_id):
    if not request.user.is_authenticated:
        return redirect('login')
    try:
        school = School.objects.get(id=school_id)
        user = request.user
        user.school = school
        user.save()
        messages.success(request, f'School updated to {school.name}')
        return redirect('profile')
    except School.DoesNotExist:
        messages.error(request, 'School not found.')
        return redirect('schools')

def cohort(request):
    if not request.user.is_authenticated:
        return redirect('login')
    user = request.user
    cohort_users = User.objects.none()
    cohort_count = 0
    
    if user.secondary_school and user.secondary_completion_year:
        cohort_users = User.objects.filter(
            secondary_school=user.secondary_school,
            secondary_completion_year=user.secondary_completion_year
        ).exclude(id=user.id)
        cohort_count = cohort_users.count()
    
    return render(request, 'cohort.html', {
        'cohort_users': cohort_users,
        'cohort_count': cohort_count,
        'user': user
    })

def onboarding(request):
    if not request.user.is_authenticated:
        return redirect('login')
    if request.method == 'POST':
        user = request.user
        school_id = request.POST.get('school')
        graduation_year = request.POST.get('graduation_year')
        if school_id and graduation_year:
            try:
                user.secondary_school = School.objects.get(id=school_id, school_type='secondary')
                user.secondary_completion_year = int(graduation_year)
                user.onboarding_complete = True
                user.save()
                messages.success(request, 'Onboarding completed!')
                return redirect('dashboard')
            except (School.DoesNotExist, ValueError):
                messages.error(request, 'Invalid school or graduation year.')
        else:
            messages.error(request, 'Please fill all fields.')
    schools = School.objects.filter(school_type='secondary').order_by('name')
    return render(request, 'onboarding.html', {'schools': schools})