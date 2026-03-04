import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Router } from '@angular/router';
import { BehaviorSubject, Observable, throwError } from 'rxjs';
import { tap, catchError } from 'rxjs/operators';
import { of } from 'rxjs';
import { environment } from '../../../environments/environment';

export interface User {
  id: number;
  username: string;
  connectorId: string;
  displayName: string;
  role?: 'consumer' | 'provider';
}

export interface LoginResponse {
  success: boolean;
  token: string;
  user: User;
}

/**
 * Authentication Service
 * 
 * Handles user authentication using JWT tokens
 * Supports multi-tenant connector system (conn-oeg-demo, conn-edmundo-demo, etc.)
 */
@Injectable({
  providedIn: 'root'
})
export class AuthService {
  private httpClient = inject(HttpClient);
  private router = inject(Router);
  
  private readonly AUTH_URL = environment.runtime.managementApiUrl;
  private readonly TOKEN_KEY = 'ml_assets_auth_token';
  private readonly USER_KEY = 'ml_assets_current_user';
  private readonly DEV_AUTH_ENABLED = !!environment.runtime?.devAuth?.enabled;
  private readonly DEV_USERS: Array<{ username: string; password: string; connectorId: string; displayName: string; role: 'consumer' | 'provider' }> = [
    {
      username: 'user-conn-user1-demo',
      password: 'user1123',
      connectorId: 'consumer',
      displayName: 'User One',
      role: 'consumer'
    },
    {
      username: 'user-conn-user2-demo',
      password: 'user2123',
      connectorId: 'provider',
      displayName: 'User Two',
      role: 'provider'
    }
  ];
  
  private isAuthenticatedSubject = new BehaviorSubject<boolean>(this.hasToken());
  public isAuthenticated$ = this.isAuthenticatedSubject.asObservable();
  
  private currentUserSubject = new BehaviorSubject<User | null>(this.getStoredUser());
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor() {
    // Check if stored token is still valid on init
    if (this.hasToken()) {
      this.verifyToken();
    }
  }

  /**
   * Login with username and password
   */
  login(username: string, password: string): Observable<LoginResponse> {
    if (this.DEV_AUTH_ENABLED) {
      const match = this.DEV_USERS.find(u => u.username === username && u.password === password);
      if (!match) {
        return throwError(() => ({ error: { message: 'Invalid username or password' } }));
      }

      const response: LoginResponse = {
        success: true,
        token: `dev-token-${match.username}`,
        user: {
          id: 1,
          username: match.username,
          connectorId: match.connectorId,
          displayName: match.displayName,
          role: match.role
        }
      };

      const normalizedUser = this.normalizeUser(response.user);
      this.setToken(response.token);
      this.setUser(normalizedUser);
      this.isAuthenticatedSubject.next(true);
      this.currentUserSubject.next(normalizedUser);
      return of({ ...response, user: normalizedUser });
    }

    const url = `${this.AUTH_URL}/auth/login`;
    console.log('[Auth] Attempting login to:', url);
    console.log('[Auth] AUTH_URL:', this.AUTH_URL);
    
    return this.httpClient.post<LoginResponse>(url, { username, password }).pipe(
      tap(response => {
        if (response.success && response.token) {
          const normalizedUser = this.normalizeUser(response.user);
          this.setToken(response.token);
          this.setUser(normalizedUser);
          this.isAuthenticatedSubject.next(true);
          this.currentUserSubject.next(normalizedUser);
          console.log(`[Auth] User ${username} logged in successfully as ${normalizedUser.connectorId} (${normalizedUser.role})`);
        }
      }),
      catchError(error => {
        console.error('[Auth] Login failed:', error);
        return throwError(() => error);
      })
    );
  }

  /**
   * Logout current user
   */
  logout(): void {
    const url = `${this.AUTH_URL}/auth/logout`;
    const token = this.getToken();

    if (token && !this.DEV_AUTH_ENABLED) {
      // Call backend logout endpoint (optional)
      this.httpClient.post(url, {}).subscribe({
        next: () => console.log('[Auth] Logout successful'),
        error: (error) => console.error('[Auth] Logout error:', error)
      });
    }
    
    this.clearAuth();
    this.router.navigate(['/login']);
  }

  /**
   * Verify current token is still valid
   */
  verifyToken(): void {
    if (this.DEV_AUTH_ENABLED) {
      const user = this.getStoredUser();
      if (user) {
        this.currentUserSubject.next(user);
        this.isAuthenticatedSubject.next(true);
      } else {
        this.clearAuth();
      }
      return;
    }
    const url = `${this.AUTH_URL}/auth/me`;
    
    this.httpClient.get<{ success: boolean; user: User }>(url).subscribe({
      next: (response) => {
        if (response.success && response.user) {
          const normalizedUser = this.normalizeUser(response.user);
          this.setUser(normalizedUser);
          this.currentUserSubject.next(normalizedUser);
          this.isAuthenticatedSubject.next(true);
        } else {
          this.clearAuth();
        }
      },
      error: (error) => {
        console.error('[Auth] Token verification failed:', error);
        this.clearAuth();
      }
    });
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return this.hasToken();
  }

  /**
   * Get current user
   */
  getCurrentUser(): User | null {
    return this.currentUserSubject.value;
  }

  /**
   * Get current user's connector ID
   */
  getConnectorId(): string | null {
    const user = this.getCurrentUser();
    return user ? user.connectorId : null;
  }

  getUserRole(): 'consumer' | 'provider' {
    const user = this.getCurrentUser();
    if (!user) {
      return 'consumer';
    }
    return this.normalizeUser(user).role || 'consumer';
  }

  /**
   * Get JWT token
   */
  getToken(): string | null {
    return localStorage.getItem(this.TOKEN_KEY);
  }

  /**
   * Check if token exists
   */
  private hasToken(): boolean {
    return !!localStorage.getItem(this.TOKEN_KEY);
  }

  /**
   * Store JWT token
   */
  private setToken(token: string): void {
    localStorage.setItem(this.TOKEN_KEY, token);
  }

  /**
   * Store user information
   */
  private setUser(user: User): void {
    localStorage.setItem(this.USER_KEY, JSON.stringify(user));
  }

  /**
   * Get stored user
   */
  private getStoredUser(): User | null {
    const userJson = localStorage.getItem(this.USER_KEY);
    if (!userJson) return null;
    
    try {
      return this.normalizeUser(JSON.parse(userJson));
    } catch {
      return null;
    }
  }

  private normalizeUser(user: User): User {
    const role = user.role || this.inferRole(user);
    return { ...user, role };
  }

  private inferRole(user: User): 'consumer' | 'provider' {
    const roleSource = `${user.connectorId} ${user.username} ${user.displayName}`.toLowerCase();
    if (roleSource.includes('provider')) {
      return 'provider';
    }
    return 'consumer';
  }

  /**
   * Clear authentication data
   */
  private clearAuth(): void {
    localStorage.removeItem(this.TOKEN_KEY);
    localStorage.removeItem(this.USER_KEY);
    this.isAuthenticatedSubject.next(false);
    this.currentUserSubject.next(null);
  }
}
