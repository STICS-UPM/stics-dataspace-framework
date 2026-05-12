import { TestBed } from '@angular/core/testing';
import { HttpClientTestingModule } from '@angular/common/http/testing';
import { RouterTestingModule } from '@angular/router/testing';
import { MenuService } from './menu.service';
import { SharedTestModule } from '../shared-tests.module';
import { LoggerTestingModule } from 'ngx-logger/testing';

describe('MenuService', () => {
  beforeEach(() =>
    TestBed.configureTestingModule({
      imports: [
        SharedTestModule,
        HttpClientTestingModule,
        RouterTestingModule,
        LoggerTestingModule
      ]
    })
  );

  it('should be created', () => {
    const service: MenuService = TestBed.get(MenuService);
    expect(service).toBeTruthy();
  });
});
