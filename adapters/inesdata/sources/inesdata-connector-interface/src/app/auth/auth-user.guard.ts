import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, RouterStateSnapshot, Router } from '@angular/router';
import { Observable } from 'rxjs';
import { filter, map, tap } from 'rxjs/operators';
import { AuthService } from './auth.service';

@Injectable({
  providedIn: 'root'
})
export class AuthUserGuard {

  private isAuthenticated: boolean;

  constructor(public authService: AuthService, private router: Router) {
    this.authService.isAuthenticated$.subscribe(i => this.isAuthenticated = i);
  }

  canActivate(next: ActivatedRouteSnapshot, state: RouterStateSnapshot): Observable<boolean> | Promise<boolean> | boolean {
    return this.authService.isDoneLoading$
      .pipe(
        filter(isDone => isDone),
        tap(() => {
          if (!this.isAuthenticated) {
            this.authService.login();
          }
        }),
        map(() => this.isAuthenticated)
      );
  }
}

