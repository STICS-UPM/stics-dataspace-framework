import { Injectable, Injector } from '@angular/core';
import { HttpEvent, HttpRequest, HttpHandler, HttpInterceptor, HttpErrorResponse } from '@angular/common/http';
import { Observable, throwError, from } from 'rxjs';
import { catchError, switchMap } from 'rxjs/operators';

import { AuthService } from 'src/app/auth/auth.service';

@Injectable()
export class Oauth2Interceptor implements HttpInterceptor {
  private static ERROR_INVALID_GRANT = 'invalid_grant';

  authService: AuthService;

  constructor(private readonly injector: Injector) {
  }

  intercept(request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    this.authService = this.injector.get(AuthService);

    console.debug('Referring a request to the resource ' + request.url, request);

    return next.handle(request).pipe(
      catchError((error: HttpErrorResponse) => this.handleError(error, request, next))
    );
  }

  handleError(error: HttpErrorResponse, request: HttpRequest<any>, next: HttpHandler): Observable<HttpEvent<any>> {
    switch (error.status) {
      case 400:
        console.debug('The request has not been correctly conformed; status code: ' + error.status, request, error);

        if (Oauth2Interceptor.ERROR_INVALID_GRANT === error.error[Object.keys(error.error)[0]]) {
          this.authService.isRefreshTokenExpired();
        }
        break;

      case 401:
        console.debug('The request has not been completed because it lacks valid authentication credentials for the requested resource; status code: ' + error.status, request, error);

        return from(this.authService.refreshToken()).pipe(
          switchMap((tokenResponse) => {
            if (tokenResponse && this.authService.hasValidToken()) {
              const authReq = request.clone({
                headers: request.headers.set('Authorization', `Bearer ${this.authService.getAccessToken()}`)
              });
              return next.handle(authReq);
            } else {
              this.authService.logout();
              return throwError(() => new Error('Token refresh failed and user has been logged out'));
            }
          }),
          catchError(() => {
            this.authService.logout();
            return throwError(() => error);
          })
        );

      // Otros casos (403, 404, etc.)
    }

    return throwError(() => error);
  }
}
