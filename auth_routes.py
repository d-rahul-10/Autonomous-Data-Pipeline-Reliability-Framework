"""
Authentication routes for PipelineIQ.
Provides signup, login, logout, and user info endpoints.
"""

from flask import Blueprint, request, jsonify, current_app, make_response
from auth import AuthManager, AuthError, require_auth

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')


def get_auth_manager() -> AuthManager:
    return current_app.config['AUTH_MANAGER']


@auth_bp.post('/signup')
def signup():
    """Register a new user."""
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match'}), 400

    if len(password) < 8:
        return jsonify({'error': 'Password must be at least 8 characters'}), 400

    auth_manager = get_auth_manager()
    try:
        user = auth_manager.create_user(email, password)
        token = auth_manager.generate_token(user)

        response = jsonify({
            'user': user.to_dict(),
            'token': token,
            'message': 'Account created successfully'
        })
        response.set_cookie('auth_token', token, httponly=True, secure=False,
                            samesite='Lax', max_age=24*60*60)
        return response, 201
    except AuthError as e:
        return jsonify({'error': e.message}), e.status_code


@auth_bp.post('/login')
def login():
    """Authenticate a user and return a JWT token."""
    data = request.get_json(silent=True) or {}
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    auth_manager = get_auth_manager()
    try:
        user = auth_manager.authenticate(email, password)
        token = auth_manager.generate_token(user)

        response = jsonify({
            'user': user.to_dict(),
            'token': token,
            'message': 'Login successful'
        })
        response.set_cookie('auth_token', token, httponly=True, secure=False,
                            samesite='Lax', max_age=24*60*60)
        return response
    except AuthError as e:
        return jsonify({'error': e.message}), e.status_code


@auth_bp.post('/logout')
def logout():
    """Log out the current user (client-side token removal)."""
    response = jsonify({'message': 'Logged out successfully'})
    response.set_cookie('auth_token', '', httponly=True, secure=False,
                        samesite='Lax', max_age=0, expires=0)
    return response


@auth_bp.get('/me')
@require_auth
def me():
    """Get current authenticated user info."""
    from flask import g
    user = getattr(g, 'current_user', None)
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    return jsonify({'user': user.to_dict()})


@auth_bp.post('/refresh')
@require_auth
def refresh():
    """Refresh the JWT token."""
    from flask import g
    user = getattr(g, 'current_user', None)
    if not user:
        return jsonify({'error': 'Not authenticated'}), 401

    auth_manager = get_auth_manager()
    token = auth_manager.generate_token(user)

    response = jsonify({'token': token, 'message': 'Token refreshed'})
    response.set_cookie('auth_token', token, httponly=True, secure=False,
                        samesite='Lax', max_age=24*60*60)
    return response