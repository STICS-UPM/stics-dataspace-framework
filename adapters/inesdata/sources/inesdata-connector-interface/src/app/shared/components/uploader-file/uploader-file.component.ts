import {Component, EventEmitter, Input, Output} from '@angular/core';

@Component({
  selector: 'app-uploader-file',
  templateUrl: './uploader-file.component.html',
  styleUrls: ['./uploader-file.component.scss']
})
export class UploaderFileComponent {

  files: any[] = [];

  @Input() isMultiple: boolean = false
  @Output() filesChange: EventEmitter<any[]> = new EventEmitter<any[]>()

  /**
   * on file drop handler
   */
  onFileDropped(event:any) {
    this.prepareFilesList(this.isMultiple?event:[event[0]]);
  }

  /**
   * handle file from browsing
   */
  fileBrowseHandler(event:any) {
    this.prepareFilesList(event.target.files);
  }

  /**
   * Delete file from files list
   * @param index (File index)
   */
  deleteFile(index: number) {
    this.files.splice(index, 1);
    this.filesChange.emit(this.files)
  }

  /**
   * Convert Files list to normal array list
   * @param files (Files List)
   */
  prepareFilesList(files: Array<File>) {
    for (const item of files) {
      this.files.push(item);
    }
    this.filesChange.emit(this.files)
  }

  /**
   * format bytes
   * @param bytes (File size in bytes)
   * @param decimals (Decimals point)
   */
  formatBytes(bytes:any, decimals:any) {
    if (bytes === 0) {
      return '0 Bytes';
    }
    const k = 1024;
    const dm = decimals <= 0 ? 0 : decimals || 2;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
  }
}
