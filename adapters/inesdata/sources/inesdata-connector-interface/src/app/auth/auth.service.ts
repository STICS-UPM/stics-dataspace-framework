import { environment } from 'src/environments/environment';
import { Injectable, EventEmitter } from '@angular/core';
import { JwtHelperService } from '@auth0/angular-jwt';
import { Member } from '../shared/models/member.model';
import { Router } from '@angular/router';
import { BehaviorSubject } from 'rxjs';
import { filter } from 'rxjs/operators';
import { OAuthService, NullValidationHandler, AuthConfig, TokenResponse } from 'angular-oauth2-oidc';

@Injectable({
  providedIn: 'root'
})
export class AuthService {
  authConfig: AuthConfig = {
    issuer: environment.runtime.oauth2.issuer,
    redirectUri: window.location.origin + environment.runtime.oauth2.redirectPath,
    clientId: environment.runtime.oauth2.clientId,
    scope: environment.runtime.oauth2.scope,
    responseType: environment.runtime.oauth2.responseType,
    useSilentRefresh: false,
    requireHttps: false,
    showDebugInformation: environment.runtime.oauth2.showDebugInformation
  };

  member: Member;
  jwtHelper: JwtHelperService = new JwtHelperService();
  userChange: EventEmitter<Member> = new EventEmitter();

  private isAuthenticatedSubject$ = new BehaviorSubject<boolean>(false);
  public isAuthenticated$ = this.isAuthenticatedSubject$.asObservable();

  private isDoneLoadingSubject$ = new BehaviorSubject<boolean>(false);
  public isDoneLoading$ = this.isDoneLoadingSubject$.asObservable();

  constructor(private router: Router, public oauthService: OAuthService) {
    this.configureOAuth();

    if (this.oauthService.hasValidAccessToken()) {
      this.createMember();
    }
  }

  private configureOAuth() {
    this.oauthService.configure(this.authConfig);
    this.oauthService.tokenValidationHandler = new NullValidationHandler();

    this.oauthService.events.subscribe(_ => {
      this.isAuthenticatedSubject$.next(this.oauthService.hasValidAccessToken());
    });

    this.oauthService.events
      .pipe(filter(e => e.type === 'token_received'))
      .subscribe(() => {
        this.createMember();
        this.userChange.emit(this.getCurrentMember());
      });

    this.oauthService.events
      .pipe(filter(e => ['session_terminated', 'session_error'].includes(e.type)))
      .subscribe(() => this.login());

    this.oauthService.events.pipe(filter(e => e.type === 'session_changed'))
      .subscribe(() => this.logout());
  }

  public runInitialLoginSequence(): Promise<void> {
    return this.oauthService.loadDiscoveryDocument()
      .then(() => this.oauthService.tryLoginCodeFlow())
      .then(() => {
        if (this.oauthService.hasValidAccessToken()) {
          return Promise.resolve();
        }

        return undefined;
      })
      .then(() => {
        this.isDoneLoadingSubject$.next(true);
      })
      .catch(() => this.isDoneLoadingSubject$.next(true));
  }

  public login(): void {
    this.removeSession();
    this.oauthService.initLoginFlow();
  }

  public isAuthenticated(): boolean {
    return this.oauthService.hasValidAccessToken();
  }

  public getAccessToken(): string {
    return this.oauthService.getAccessToken();
  }

  public getRefreshToken(): string {
    return this.oauthService.getRefreshToken();
  }

  public isRefreshTokenExpired(): boolean {
    const refreshToken = this.getRefreshToken();

    if (!refreshToken) {
      this.login();
      return true;
    }

    return this.jwtHelper.isTokenExpired(refreshToken);
  }

  public hasValidToken(): boolean {
    return this.oauthService.hasValidAccessToken();
  }

  public getCurrentMember(): Member {
    return this.member;
  }

  public createMember(): void {
    this.member = {} as Member;

    if (this.oauthService.getIdentityClaims() != null) {
      const claims = this.oauthService.getIdentityClaims() as any;
      this.member.name = claims.name;
      this.member.email = claims.email;
      this.member.username = claims.preferred_username;
      this.member.id = claims.sub;
      this.member.firstName = claims.given_name;
      this.member.lastName = claims.family_name;
    }

    if (this.oauthService.getAccessToken() != null) {
      const decodedToken = this.jwtHelper.decodeToken(this.oauthService.getAccessToken());
      const clientId = environment.runtime.oauth2.clientId;
      if (clientId) {
        this.member.roles = decodedToken['realm_access']['roles'];
      }
    }
  }

  public logout(): void {
    this.oauthService.revokeTokenAndLogout();
    this.removeSession();
    this.router.navigate(['']);
  }

  private removeSession(): void {
    this.member = null;
    this.userChange.emit(null);
    sessionStorage.removeItem(environment.jwt.storageKey);
    sessionStorage.removeItem(environment.jwt.storageRefreshKey);
  }

  getUserChangeEmitter() {
    return this.userChange;
  }

  public refreshToken(): Promise<TokenResponse | void> {
    return this.oauthService.refreshToken().catch(() => {
      this.logout(); // Redirige al usuario al logout en caso de error
      return Promise.resolve(); // Devuelve una promesa vacía para evitar loops
    });
  }
}
