// CrossFit Health OS - Main JavaScript

// API base URL
const API_BASE = window.location.origin;

// Auth middleware — protected pages rely on CHOS.auth.ensureSession() via
// CHOS.initDashboard() in base.html. No duplicate redirect or 401 handler here
// (those conflicted with CHOS.api token refresh).

// Utility functions
const Utils = {
    // Show Bootstrap alert
    showAlert: function(container, message, type = 'info') {
        const alert = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        $(container).html(alert);
        
        // Auto-dismiss after 5 seconds
        setTimeout(function() {
            $(container).find('.alert').alert('close');
        }, 5000);
    },
    
    // Format date
    formatDate: function(dateString) {
        const date = new Date(dateString);
        return date.toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'long',
            day: 'numeric'
        });
    },
    
    // JWT validation helper
    isTokenExpired: function(token) {
        if (!token || token.split('.').length !== 3) return true;
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            if (!payload.exp) return true;
            return Date.now() > payload.exp * 1000;
        } catch {
            return true;
        }
    },

    // Check if user is authenticated (delegates to CHOS when available)
    isAuthenticated: function() {
        if (window.CHOS && CHOS.auth) {
            return CHOS.auth.isAuthenticated();
        }
        const token = localStorage.getItem('access_token');
        if (!token) return false;
        if (this.isTokenExpired(token)) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            return false;
        }
        return true;
    },
    
    // Get current user
    getCurrentUser: function() {
        if (window.CHOS && CHOS.auth) {
            return CHOS.auth.getUser();
        }
        const userStr = localStorage.getItem('user');
        return userStr ? JSON.parse(userStr) : null;
    }
};

// Global error handler
window.addEventListener('unhandledrejection', function(event) {
    console.error('Unhandled promise rejection:', event.reason);
});

// Smooth scroll for anchor links. Skip bare "#" / "#!" used as click stubs
// (Bootstrap dropdowns, button-as-link, etc.) — those aren't real fragments
// and jQuery throws "unrecognized expression: #" if we try to select them.
$(document).ready(function() {
    $('a[href^="#"]').on('click', function(e) {
        const href = this.getAttribute('href') || '';
        if (href.length < 2 || href === '#!' || href.includes(' ')) return;
        let target;
        try {
            target = $(href);
        } catch (_) {
            return;  // Invalid CSS selector — ignore.
        }
        if (target.length) {
            e.preventDefault();
            $('html, body').animate({
                scrollTop: target.offset().top - 80
            }, 500);
        }
    });
});

// Logout handler for pages that use the legacy #logout-btn wiring
$(document).ready(function() {
    $('#logout-btn').on('click', function(e) {
        e.preventDefault();
        if (window.CHOS && CHOS.auth && CHOS.auth.logout) {
            CHOS.auth.logout();
            return;
        }
        const token = localStorage.getItem('access_token');
        const refreshToken = localStorage.getItem('refresh_token');
        $.ajax({
            url: '/api/v1/auth/logout',
            type: 'POST',
            contentType: 'application/json',
            headers: token ? { 'Authorization': 'Bearer ' + token } : {},
            data: JSON.stringify({ refresh_token: refreshToken || null }),
            complete: function() {
                localStorage.removeItem('access_token');
                localStorage.removeItem('refresh_token');
                localStorage.removeItem('user');
                window.location.href = '/';
            }
        });
    });
    
    // Load user name from localStorage
    const userJson = localStorage.getItem('user');
    const user = userJson && userJson !== 'undefined' ? JSON.parse(userJson) : {};
    if (user.name) {
        $('#user-name').text(user.name);
    }
});
