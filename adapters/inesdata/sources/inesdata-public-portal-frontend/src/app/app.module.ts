import { AppConfigService } from "./app-config.service";
import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';

import { BrowserAnimationsModule } from '@angular/platform-browser/animations';
import { BrowserModule } from '@angular/platform-browser';
import {
	HttpClientModule,
	HttpClient,
	HTTP_INTERCEPTORS
} from '@angular/common/http';
import { APP_INITIALIZER, NgModule, ErrorHandler } from '@angular/core';

import { environment } from 'src/environments/environment';

//Translation
import {
	TranslateLoader,
	TranslateModule,
	TranslateService
} from '@ngx-translate/core';
import { TranslateHttpLoader } from '@ngx-translate/http-loader';

import { GlobalErrorHandlerService } from './shared/handlers/general-error-handler.service';
import { ServerErrorInterceptor } from './shared/interceptors/server-error.interceptor';
import { SpinnerService } from './shared/services/spinner.service';
import { SharedModule } from './shared/shared.module';

// Logger
import { LoggerModule } from 'ngx-logger';
import { WriteLoggerService } from './shared/logger/writer.logger.service';
import { ServerLoggerService } from './shared/logger/server.logger.service';
import { ASSET_TYPES } from "./shared/utils/app.constants";

/**
 * Ng module: App module
 */
@NgModule({
	declarations: [AppComponent],
	imports: [
		AppRoutingModule,
		BrowserAnimationsModule,
		BrowserModule,
		HttpClientModule,
		SharedModule,
		TranslateModule.forRoot({
			loader: {
				provide: TranslateLoader,
				useFactory: (http: HttpClient) => {
					return new TranslateHttpLoader(http, './assets/i18n/');
				},
				deps: [HttpClient]
			}
		}),
		LoggerModule.forRoot(
			{
				serverLoggingUrl: environment.logging.apiUrl,
				level: environment.logging.logLevel,
				serverLogLevel: environment.logging.serverLogLevel,
				disableConsoleLogging: environment.logging.disableNgxLogging,
				enableSourceMaps: environment.logging.enableSourceMaps
			},
			{
				writerProvider: {
					provide: 'TOKEN_LOGGER_WRITER_SERVICE',
					useClass: WriteLoggerService
				},
				serverProvider: {
					provide: 'TOKEN_LOGGER_SERVER_SERVICE',
					useClass: ServerLoggerService
				}
			}
		)
	],
	providers: [
		TranslateService,
		SpinnerService,
		{
			provide: HTTP_INTERCEPTORS,
			useClass: ServerErrorInterceptor,
			multi: true
		},
		{ provide: ErrorHandler, useClass: GlobalErrorHandlerService },
		{
      provide: APP_INITIALIZER,
      useFactory: (configService: AppConfigService) => () => configService.loadConfig(),
      deps: [AppConfigService],
      multi: true
    },
    {
      provide: 'ASSET_TYPES',
      useFactory: () => [{id: ASSET_TYPES.dataset, name: ASSET_TYPES.dataset}, {id: ASSET_TYPES.machineLearning, name: ASSET_TYPES.machineLearning}, {id: ASSET_TYPES.service, name: ASSET_TYPES.service}],
    }
	],
	bootstrap: [AppComponent]
})
export class AppModule { }
