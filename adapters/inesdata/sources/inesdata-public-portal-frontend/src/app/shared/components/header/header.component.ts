import { Component } from '@angular/core';
import { BehaviorSubject } from 'rxjs';
import { MenuService } from 'src/app/shared/services/menu.service';
import { LanguageService } from '../../services/language.service';
import { LoadMenuStatusService } from '../../services/load-menu-status.service';

/**
 * Header component
 */
@Component({
  selector: 'app-header',
  templateUrl: './header.component.html',
  styleUrls: ['./header.component.scss']
})
export class HeaderComponent {
	menu: any;
	private fetch$ = new BehaviorSubject(null);
  /**
   * Component constructor
   *
   * @param menuService Menu service
   * @param languageService Language service
   */
  constructor(
    public menuService: MenuService,
    public languageService: LanguageService,
		private loadStatusService: LoadMenuStatusService
  ) {}

	ngOnInit(): void {
		this.menuService.getMenu().subscribe(results => {
					this.menu = results;
					this.loadStatusService.setLoaded(true);
				});
	}
}
