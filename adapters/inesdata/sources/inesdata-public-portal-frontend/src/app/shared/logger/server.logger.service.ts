import { HttpRequest } from '@angular/common/http';
import { Injectable } from '@angular/core';
import { INGXLoggerMetadata, NGXLoggerServerService } from "ngx-logger";
import { LoggerFormat } from './formats/logger-format';

@Injectable()
export class ServerLoggerService extends NGXLoggerServerService {

  private CONTENT_TYPE: string = 'Content-Type'
  private APPLICATION_JSON: string = 'application/json'
  private AUTHORIZATION: string = 'Authorization'
  private BEARER: string = 'Bearer '
  private TOKEN_KEY: string = 'jwt_token'


  /**
   * Customse the body sent to the API
   * @param metadata the data provided by NGXLogger
   * @returns the body customised
   */
  public customiseRequestBody(metadata: INGXLoggerMetadata): any {
    return this.getJsonFormatMetadata(metadata)
  }

  /**
   * Edits HttpRequest object before sending request to server
   *
   * @param httpRequest default request object
   * @returns altered httprequest
   */
  public alterHttpRequest(httpRequest: HttpRequest<any>): HttpRequest<any> {
    httpRequest = httpRequest.clone({
      setHeaders:
      {
        [this.CONTENT_TYPE]: this.APPLICATION_JSON,
        //[this.AUTHORIZATION]: token ? this.BEARER +  sessionStorage.getItem(this.TOKEN_KEY) : '' //Uncomment this line if your application require jwt authentication
      },
    });

    return httpRequest;
  }

  /**
   * Get metadata in JSON format
   *
   * @param metadata Metadata info
   * @returns JSON
   */
  private getJsonFormatMetadata(metadata: INGXLoggerMetadata): string {

    return JSON.stringify(LoggerFormat.getFormatModel(metadata), function (key, value) {

      if (value && typeof value === 'object') {

        var replacement = {};
        for (var key in value) {
          if (Object.hasOwnProperty.call(value, key)) {
            replacement[key.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`)] = value[key];
          }
        }

        return replacement;
      }

      return value;
    })
  }
}
