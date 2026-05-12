import { TestBed } from '@angular/core/testing';
import { TranslateLoader, TranslateModule, TranslateService } from '@ngx-translate/core';
import { LoggerTestingModule } from 'ngx-logger/testing';
import { Observable, of } from 'rxjs';
import { LanguageService } from '../services/language.service';
import { BoolToYesNoPipe } from './bool-to-yes-no.pipe';

const translations: any = {
  labels: {
    yes: 'yes',
    no: 'no'
  }
};
class FakeLoader implements TranslateLoader {
  getTranslation(lang: string): Observable<any> {
    return of(translations);
  }
}

describe('BoolToYesNoPipe', () => {
  beforeEach(() =>
    TestBed.configureTestingModule({
      imports: [
        TranslateModule.forRoot({
          loader: { provide: TranslateLoader, useClass: FakeLoader }
        }),
        LoggerTestingModule
      ],
      providers: [TranslateService]
    })
  );

  it('create an instance', () => {
    const pipe: BoolToYesNoPipe = new BoolToYesNoPipe(TestBed.inject(LanguageService));
    expect(pipe).toBeTruthy();
  });

  it('return yes', () => {
    const pipe: BoolToYesNoPipe = new BoolToYesNoPipe(TestBed.inject(LanguageService));
    expect(pipe.transform(true)).toEqual('yes');
  });

  it('return no', () => {
    const pipe: BoolToYesNoPipe = new BoolToYesNoPipe(TestBed.inject(LanguageService));
    expect(pipe.transform(false)).toEqual('no');
  });
});
