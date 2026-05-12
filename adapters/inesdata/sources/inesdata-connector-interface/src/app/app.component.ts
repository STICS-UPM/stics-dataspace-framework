import { Component, OnInit } from '@angular/core';
import { Title } from '@angular/platform-browser';
import { ActivatedRoute, NavigationEnd, Router } from '@angular/router';
import { filter, map } from 'rxjs/operators';
import { AuthService } from './auth/auth.service';
import { environment } from "../environments/environment";

/**
 * Main app component
 */
@Component({
  selector: 'app-root',
  templateUrl: './app.component.html'
})
export class AppComponent implements OnInit {

    /**
   * Component constructor
   *
   * @param router Router service
   * @param titleService Title service
   * @param activatedRoute ActivatedRoute service
   * @param authService Auth service
   */
  constructor(
    private router: Router,
    private titleService: Title,
    private activatedRoute: ActivatedRoute,
    public authService: AuthService) {
      this.authService.runInitialLoginSequence();
  }

  ngOnInit(): void {
    const appTitle = this.titleService.getTitle();
    this.router
      .events
      .pipe(
        filter(event => event instanceof NavigationEnd),
        map(() => {
          const child = this.activatedRoute.firstChild;
          if (child?.snapshot.data['title']) {
            return child.snapshot.data['title'];
          }
          return appTitle;
        })
      ).subscribe((title: string) => {
        this.titleService.setTitle(title);
      });
  }
}
