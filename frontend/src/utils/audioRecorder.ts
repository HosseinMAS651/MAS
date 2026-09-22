export interface RecorderOptions {
  timesliceMs?: number;
  onChunk: (chunk: Blob, seq: number) => Promise<void>;
  onError?: (err: Error) => void;
}

export class AudioRecorder {
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private seq: number = 0;
  private isRecording: boolean = false;
  private mimeType: string = 'audio/webm';

  static isSupported(): boolean {
    return Boolean(navigator?.mediaDevices?.getUserMedia && window?.MediaRecorder);
  }

  static getSupportedMimeType(): string {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg;codecs=opus',
      'audio/wav',
    ];
    for (const c of candidates) {
      if (window.MediaRecorder?.isTypeSupported?.(c)) {
        return c;
      }
    }
    return '';
  }

  async start(options: RecorderOptions): Promise<string> {
    if (!AudioRecorder.isSupported()) {
      throw new Error('قابلیت ضبط صدا در مرورگر شما پشتیبانی نمی‌شود.');
    }

    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

    this.mimeType = AudioRecorder.getSupportedMimeType() || 'audio/webm';
    this.mediaRecorder = new MediaRecorder(this.mediaStream, {
      mimeType: this.mimeType,
      audioBitsPerSecond: 32000,
    });

    this.seq = 0;
    this.isRecording = true;

    this.mediaRecorder.ondataavailable = async (e: BlobEvent) => {
      if (e.data && e.data.size > 0 && this.isRecording) {
        this.seq += 1;
        try {
          await options.onChunk(e.data, this.seq);
        } catch (err: any) {
          if (options.onError) {
            options.onError(err);
          }
        }
      }
    };

    this.mediaRecorder.onerror = (e: any) => {
      if (options.onError) {
        options.onError(new Error(e.error?.message || 'خطای ضبط صدا'));
      }
    };

    // برش فایل به قطعات زمانی جهت آپلود جریانی و تاب‌آوری بالا
    this.mediaRecorder.start(options.timesliceMs || 5000);
    return this.mimeType;
  }

  pause() {
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.mediaRecorder.pause();
    }
  }

  resume() {
    if (this.mediaRecorder && this.mediaRecorder.state === 'paused') {
      this.mediaRecorder.resume();
    }
  }

  stop() {
    this.isRecording = false;
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      try {
        this.mediaRecorder.stop();
      } catch {}
    }
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
    }
    this.mediaRecorder = null;
  }

  getState(): RecordingState | 'inactive' {
    return this.mediaRecorder ? this.mediaRecorder.state : 'inactive';
  }
}
