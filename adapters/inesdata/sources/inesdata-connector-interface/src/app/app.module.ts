import { NgModule} from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';

import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { BrowserAnimationsModule } from '@angular/platform-browser/animations';

import { LayoutModule } from '@angular/cdk/layout';
import { MAT_FORM_FIELD_DEFAULT_OPTIONS } from '@angular/material/form-field';
import { CONNECTOR_CATALOG_API, CONNECTOR_MANAGEMENT_API, DATA_ADDRESS_TYPES } from "./shared/utils/app.constants";
import { HTTP_INTERCEPTORS, HttpClientModule } from "@angular/common/http";
import { Oauth2Interceptor } from "./shared/interceptors/aouth2.interceptor";
import { environment } from "../environments/environment";
import { EdcConnectorClient } from "@think-it-labs/edc-connector-client";
import { SharedModule } from './shared/shared.module';
import { resolveOauthAllowedUrls } from './shared/utils/model-observer-runtime';

import { AuthService } from './auth/auth.service';
import { JwtHelperService, JwtModule, JWT_OPTIONS } from '@auth0/angular-jwt';
import { OAuthModule } from 'angular-oauth2-oidc';
import { JsonFormsModule } from '@jsonforms/angular';
import { JsonFormsAngularMaterialModule } from '@jsonforms/angular-material';

export function jwtOptionsFactory(authService: AuthService) {
  const jwtHelper: JwtHelperService = new JwtHelperService();
  return {
    tokenGetter: async (): Promise<string> => {
      let accessToken = authService.getAccessToken();

      // Si el accessToken existe y está expirado
      if (accessToken !== null && jwtHelper.isTokenExpired(accessToken)) {
        try {
          // Intentar refrescar el token
          const token = await authService.refreshToken();

          if (token && token.access_token) {
            // Retornar el nuevo access token
            return token.access_token;
          } else {
            // Si no se obtiene un nuevo token, lanzar un error o redirigir al login
            authService.login();
            return '';
          }
        } catch (error) {
          console.error('Error refreshing token:', error);
          authService.login();
          return '';
        }
      }

      // Si el accessToken es válido, retornarlo
      return accessToken || '';
    },
    allowedDomains: environment.jwt.allowedDomains,
    disallowedRoutes: environment.jwt.disallowedRoutes
  };
}


@NgModule({
  imports: [
    BrowserModule,
    AppRoutingModule,
    BrowserAnimationsModule,
    LayoutModule,
    SharedModule,
    HttpClientModule,
    JsonFormsModule,
    JsonFormsAngularMaterialModule,
    JwtModule.forRoot({
      jwtOptionsProvider: {
        provide: JWT_OPTIONS,
        useFactory: jwtOptionsFactory,
        deps: [AuthService]
      }
    }),
    OAuthModule.forRoot({
      resourceServer: {
        allowedUrls: resolveOauthAllowedUrls(environment.runtime),
        // Add Auth header with Bearer token to all requests
        sendAccessToken: true
      }
    })
  ],
  declarations: [
    AppComponent
  ],
  providers: [
    AuthService,
    {provide: MAT_FORM_FIELD_DEFAULT_OPTIONS, useValue: {appearance: 'outline'}},
    {
      provide: CONNECTOR_MANAGEMENT_API,
      useFactory: () => environment.runtime.managementApiUrl
    },
    {
      provide: CONNECTOR_CATALOG_API,
      useFactory: () => environment.runtime.catalogUrl
    },
    {
      provide: 'HOME_CONNECTOR_STORAGE_ACCOUNT',
      useFactory: () => environment.runtime.storageAccount
    },
    {
      provide: 'STORAGE_TYPES',
      useFactory: () => [{id: DATA_ADDRESS_TYPES.httpData, name: DATA_ADDRESS_TYPES.httpData}, {id: DATA_ADDRESS_TYPES.amazonS3, name: 'ExternalStoreS3'}, {id: DATA_ADDRESS_TYPES.inesDataStore, name: 'PIONERA Store'}],
    },
    {
      provide: 'TRANSFER_TYPES',
      useFactory: () => [{id: DATA_ADDRESS_TYPES.amazonS3, name: 'ExternalStoreS3'}, {id: DATA_ADDRESS_TYPES.inesDataStore, name: 'PIONERA Store'}],
    },
    { provide: HTTP_INTERCEPTORS, useClass: Oauth2Interceptor, multi: true },
    {
      provide: EdcConnectorClient,
      useFactory: () => {
        return new EdcConnectorClient.Builder()
          .managementUrl(environment.runtime.managementApiUrl)
          .build();
      }
    }
  ],
  bootstrap: [AppComponent]
})
export class AppModule {
}
