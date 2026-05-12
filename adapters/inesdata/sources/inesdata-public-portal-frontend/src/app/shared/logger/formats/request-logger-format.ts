import { HttpRequest } from '@angular/common/http';
import { RequestLoggerFormatModel } from '../../models/logger-format.model';

/**
 * Request logger format
 */
export class RequestLoggerFormat {

  private static BLANK: string = " ";
  private static URI_REGEX: string = "^https?:\/\/[A-Za-z0-9:.]*([\/]{1}.*\/?)$";
  private static URI_REGEX_POSITION: number = 1;
  private static HOST_REGEX: string = "^(?:https?:\/\/)?(?:[^@\/\n]+@)?(?:www\.)?([^:\/\n]+)";
  private static HOST_REGEX_POSITION: number = 1;
  private static HTTP_REQUEST_METADATA_POSITION: number = 0;

  /**
   * Get the format model of request metadata.
   *
   * @param aditional input arguments provided in the logger
   * @returns string request format
   */
  public static getRequestFormatModel(aditional: any[]): RequestLoggerFormatModel {

    if (!aditional || aditional.length < 1 || !(aditional[this.HTTP_REQUEST_METADATA_POSITION] instanceof HttpRequest)) {
      return undefined;
    }

    return {
      remoteHost: this.getRequestRemoteHost(aditional[this.HTTP_REQUEST_METADATA_POSITION]),
      requestUri: this.getRequestUri(aditional[this.HTTP_REQUEST_METADATA_POSITION]),
      requestUrl: aditional[this.HTTP_REQUEST_METADATA_POSITION].url,
      userAgent: window.navigator.userAgent,
      method: aditional[this.HTTP_REQUEST_METADATA_POSITION].method
    }
  }

  /**
   * Get the request URI
   *
   * @param request HTTP request
   * @returns URI
   */
  private static getRequestUri(request: HttpRequest<any>): string {
    let uri = request.url.match(this.URI_REGEX);
    return uri !== null && uri.length > 1 ? uri[this.URI_REGEX_POSITION] : this.BLANK;
  }

  /**
   * Get the request remote host
   *
   * @param request HTTP request
   * @returns Remote host
   */
  private static getRequestRemoteHost(request: HttpRequest<any>): string {
    let host = request.url.match(this.HOST_REGEX);
    return host !== null && host.length > 1 ? host[this.HOST_REGEX_POSITION] : this.BLANK;
  }
}
