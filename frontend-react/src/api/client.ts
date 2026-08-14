import axios, { type AxiosInstance, type AxiosError } from 'axios';
import { authorizationHeader, handleUnauthorized } from '@/auth/oidc';

// Default to same-origin so Vite dev proxy handles /api consistently.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';

/**
 * Create configured Axios instance
 */
const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120000, // 2 minutes for chat streaming
  headers: {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  },
});

/**
 * Request interceptor - add auth headers if needed
 */
apiClient.interceptors.request.use(
  (config) => {
    Object.assign(config.headers, authorizationHeader());
    return config;
  },
  (error) => Promise.reject(error)
);

/**
 * Response interceptor - handle common errors
 */
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    // Aborted debounce/navigation requests are expected during rapid form
    // edits. They are handled by the caller and should not look like a
    // network failure in browser diagnostics.
    if (axios.isCancel(error) || error.code === 'ERR_CANCELED') {
      return Promise.reject(error);
    }
    if (error.response) {
      // Server responded with error status
      const status = error.response.status;
      
      switch (status) {
        case 401:
          handleUnauthorized();
          break;
        case 429:
          console.error('Rate limit exceeded');
          break;
        case 500:
          console.error('Internal server error');
          break;
        case 503:
          console.error('Service unavailable');
          break;
        default:
          console.error(`API error: ${status}`);
      }
    } else if (error.request) {
      // Request made but no response
      console.error('Network error - no response from server');
    } else {
      // Something else happened
      console.error('Request error:', error.message);
    }
    
    return Promise.reject(error);
  }
);

export default apiClient;
