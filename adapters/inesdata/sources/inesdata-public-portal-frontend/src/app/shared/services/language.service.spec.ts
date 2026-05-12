import { TestBed } from '@angular/core/testing';
import { TranslateService, TranslateLoader, TranslateModule } from '@ngx-translate/core';
import { LanguageService } from './language.service';
import { Observable, of } from 'rxjs';
import { LoggerTestingModule } from 'ngx-logger/testing';

const translations: any = {};
class FakeLoader implements TranslateLoader {
  getTranslation(lang: string): Observable<any> {
    return of(translations);
  }
}

describe('LanguageService', () => {
  beforeEach(() => TestBed.configureTestingModule({
    imports: [
      TranslateModule.forRoot({
        loader: { provide: TranslateLoader, useClass: FakeLoader },
      }),
      LoggerTestingModule
    ],
    providers: [
      TranslateService
    ]
  }));

  it('should be created', () => {
    const service: LanguageService = TestBed.get(LanguageService);
    expect(service).toBeTruthy();
  });
});
