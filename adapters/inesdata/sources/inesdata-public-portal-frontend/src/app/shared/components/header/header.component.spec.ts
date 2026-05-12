import { ComponentFixture, TestBed, waitForAsync } from '@angular/core/testing';
import { HeaderComponent } from './header.component';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { MenubarModule } from 'primeng/menubar';
import { MenuService } from 'src/app/shared/services/menu.service';
import { RouterTestingModule } from '@angular/router/testing';
import { TranslateLoader, TranslateModule } from '@ngx-translate/core';
import { Observable, of } from 'rxjs';
import { LoggerTestingModule } from 'ngx-logger/testing';

class MockMenuService {
  mainMenu = [];

  getMenu(): Observable<any> {
    return of([{
      label: 'Home',
      routerLink: '/home',
      id: 1,
      command: () => {}
    }]);
  }
}

const translations: any = {};
class FakeLoader implements TranslateLoader {
  getTranslation(lang: string): Observable<any> {
    return of(translations);
  }
}

describe('HeaderComponent', () => {
  let component: HeaderComponent;
  let fixture: ComponentFixture<HeaderComponent>;

  beforeEach(waitForAsync(() => {
    TestBed.configureTestingModule({
      declarations: [ HeaderComponent ],
      imports: [
        HttpClientTestingModule,
        MenubarModule,
        RouterTestingModule,
        TranslateModule.forRoot({
          loader: { provide: TranslateLoader, useClass: FakeLoader },
        }),
        LoggerTestingModule
      ],
      providers: [
        { provide: MenuService, useClass: MockMenuService }
      ]
    })
    .compileComponents();
  }));

  beforeEach(() => {
    fixture = TestBed.createComponent(HeaderComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('header should contain the logo', () => {
    component.ngOnInit();
    fixture.detectChanges();

    const compiled = fixture.debugElement.nativeElement;
    expect(compiled.querySelector('img')).not.toBeNull();
  });

  it('should populate menu on init', () => {
    component.ngOnInit();
    fixture.detectChanges();
    expect(component.menu).toBeDefined();
    expect(component.menu.length).toBeGreaterThan(0);
  });
});
