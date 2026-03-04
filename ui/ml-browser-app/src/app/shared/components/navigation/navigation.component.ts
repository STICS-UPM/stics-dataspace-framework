import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { BreakpointObserver, Breakpoints } from '@angular/cdk/layout';
import { Observable } from 'rxjs';
import { map, shareReplay } from 'rxjs/operators';

import { MatToolbarModule } from '@angular/material/toolbar';
import { MatSidenavModule } from '@angular/material/sidenav';
import { MatListModule } from '@angular/material/list';
import { MatIconModule } from '@angular/material/icon';
import { MatButtonModule } from '@angular/material/button';
import { MatMenuModule } from '@angular/material/menu';

import { AuthService } from '../../services/auth.service';

/**
 * Navigation/Layout Component
 * 
 * Provides the main application frame with:
 * - Top toolbar with title
 * - Side navigation drawer with menu items
 * - Responsive layout (drawer toggles on mobile)
 * - Router outlet for page content
 */
@Component({
  selector: 'app-navigation',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatToolbarModule,
    MatSidenavModule,
    MatListModule,
    MatIconModule,
    MatButtonModule,
    MatMenuModule
  ],
  templateUrl: './navigation.component.html',
  styleUrl: './navigation.component.scss'
})
export class NavigationComponent {
  private breakpointObserver = inject(BreakpointObserver);
  public authService = inject(AuthService);

  isHandset$: Observable<boolean> = this.breakpointObserver.observe(Breakpoints.Handset)
    .pipe(
      map(result => result.matches),
      shareReplay()
    );

  /**
   * Navigation menu items
   */
  menuItems = [
    {
      path: '/ml-assets',
      label: 'IA Assets Browser',
      icon: 'model_training'
    },
    {
      path: '/infer',
      label: 'Model Execution',
      icon: 'play_circle'
    },
    {
      path: '/assets/create',
      label: 'Create IA Asset',
      icon: 'add_circle'
    },
    {
      path: '/catalog',
      label: 'Catalog',
      icon: 'storage'
    },
    {
      path: '/contracts',
      label: 'Contracts',
      icon: 'description'
    }
  ];

  appTitle = 'IA Models Browser';

  /**
   * Logout user
   */
  logout(): void {
    this.authService.logout();
  }
}
