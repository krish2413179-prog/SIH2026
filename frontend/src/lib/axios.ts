/**
 * Axios instance.
 *
 * AUTH IS TEMPORARILY DISABLED — no Bearer token is attached and 401
 * responses are passed through without redirecting to /auth/login.
 * TODO: re-enable with MetaMask wallet-signature auth.
 */

import axios from 'axios';

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || '/api/v1',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 30_000,
});

export default apiClient;
