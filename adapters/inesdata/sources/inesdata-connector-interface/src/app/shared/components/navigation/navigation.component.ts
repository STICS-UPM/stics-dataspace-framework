import { Component } from '@angular/core';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { Observable } from 'rxjs';
import { map, shareReplay } from 'rxjs/operators';
import { routes } from '../../../app-routing.module';
import { Title } from '@angular/platform-browser';
import { AuthService } from 'src/app/auth/auth.service';
import { environment } from 'src/environments/environment';

@Component({
  selector: 'app-navigation',
  templateUrl: './navigation.component.html',
  styleUrls: ['./navigation.component.scss']
})
export class NavigationComponent {
  private readonly branding = (environment.runtime as any)?.branding || {};
  brandName = `${this.branding.name || 'PIONERA'}`.trim() || 'PIONERA';
  showBrandName = this.isTruthy(this.branding.showMenuText);

  isHandset$: Observable<boolean> = this.breakpointObserver.observe(Breakpoints.Handset)
    .pipe(
      map(result => result.matches),
      shareReplay()
    );

  routes = routes;

  constructor(
    public titleService: Title,
    private breakpointObserver: BreakpointObserver,
    private authService: AuthService) {
  }

  logout(){
    this.authService.logout()
  }

  private isTruthy(value: unknown): boolean {
    const normalized = `${value ?? 'true'}`.trim().toLowerCase();
    return !['false', '0', 'no', 'n', 'off'].includes(normalized);
  }
}
