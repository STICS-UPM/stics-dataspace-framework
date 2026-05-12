import { INGXLoggerMetadata, NgxLoggerLevel } from 'ngx-logger';
import { environment } from 'src/environments/environment';
import { LoggerFormatModel } from '../../models/logger-format.model';
import { RequestLoggerFormat } from './request-logger-format';

/**
 * Logger format
 */
export class LoggerFormat {

  private static SEPARATOR: string = ":";
  private static EMPTY: string = "";
  private static FILEPATH_REGEX: string = "^(.+)\/([^\/]+)$";

  /**
   * Get the format model with the basic standard metadata
   *
   * @param metadata aditional information of logger interceptor
   * @returns string with standart format fulfilled
   */
  public static getFormatModel(metadata: INGXLoggerMetadata): LoggerFormatModel {
    return {
      timestamp: metadata.timestamp,
      msVersion: environment.info.version,
      msName: environment.info.name,
      level: NgxLoggerLevel[metadata.level],
      levelValue: metadata.level,
      appId: environment.info.app,
      class: this.getClass(metadata),
      package: this.getPackage(metadata),
      line: metadata.lineNumber + this.SEPARATOR + metadata.columnNumber,
      request: RequestLoggerFormat.getRequestFormatModel(metadata.additional),
      message: metadata.message
    }
  }

  private static getClass(metadata: INGXLoggerMetadata): string {
    let classNameArray = metadata.fileName ? metadata.fileName.match(this.FILEPATH_REGEX) : null;
    let className = classNameArray !== null && classNameArray.length > 1 ? classNameArray[classNameArray.length - 1] : metadata.fileName;
    return className;
  }

  private static getPackage(metadata: INGXLoggerMetadata): string {
    let packagePath = metadata.fileName ? metadata.fileName.match(this.FILEPATH_REGEX) : null;
    return packagePath !== null && packagePath.length > 1 ? packagePath[packagePath.length - 2] : metadata.fileName;
  }
}
