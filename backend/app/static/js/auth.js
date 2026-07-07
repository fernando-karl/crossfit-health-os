// CrossFit Health OS - Authentication JavaScript

// JWT validation helper
function isTokenExpired(token) {
    // Check token structure first
    if (!token || token.split('.').length !== 3) {
        return true;  // Invalid structure = expired
    }

    try {
        const payload = JSON.parse(atob(token.split('.')[1]));

        // Check if exp field exists
        if (!payload.exp) {
            return true;  // No expiration = expired (be safe)
        }

        const exp = payload.exp * 1000;
        return Date.now() > exp;
    } catch {
        return true;  // Parse error = expired
    }
}

// Utils object with authentication helpers (delegates to CHOS.auth when loaded)
const AuthUtils = {
    /**
     * Check if user is authenticated
     * @returns {boolean} True if user has valid access token or recoverable refresh
     */
    isAuthenticated: function() {
        if (window.CHOS && CHOS.auth) {
            return CHOS.auth.isAuthenticated();
        }

        const accessToken = localStorage.getItem('access_token');
        const refreshToken = localStorage.getItem('refresh_token');

        if (refreshToken && (!accessToken || isTokenExpired(accessToken))) {
            return true;
        }

        if (!accessToken) {
            return false;
        }

        if (isTokenExpired(accessToken)) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user');
            return false;
        }

        return true;
    },

    /**
     * Get current user from localStorage
     * @returns {object|null} User object or null
     */
    getUser: function() {
        try {
            const userStr = localStorage.getItem('user');
            return userStr ? JSON.parse(userStr) : null;
        } catch {
            return null;
        }
    },

    /**
     * Get access token
     * @returns {string|null} Access token or null
     */
    getAccessToken: function() {
        return localStorage.getItem('access_token');
    },

    /**
     * Logout user - clear all auth data
     */
    logout: function() {
        if (window.CHOS && CHOS.auth && CHOS.auth.logout) {
            CHOS.auth.logout();
            return;
        }
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
    }
};

// On auth pages: if session is recoverable, refresh silently then redirect
$(document).ready(function() {
    const currentPath = window.location.pathname;
    const authPages = ['/login', '/register', '/forgot-password'];

    if (!authPages.includes(currentPath)) return;

    function redirectIfAuthenticated() {
        if (!AuthUtils.isAuthenticated()) return;

        if (window.CHOS && CHOS.auth && CHOS.auth.ensureSession) {
            CHOS.auth.ensureSession().then(function() {
                const params = new URLSearchParams(window.location.search);
                const dest = params.get('redirect');
                const safeDest = dest && dest.startsWith('/') && !dest.startsWith('//') ? dest : '/dashboard';
                window.location.href = safeDest;
            }).catch(function() {
                if (window.CHOS && CHOS.auth) CHOS.auth.clearStoredAuth();
            });
            return;
        }

        window.location.href = '/dashboard';
    }

    redirectIfAuthenticated();
});
