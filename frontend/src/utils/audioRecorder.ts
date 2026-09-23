export interface RecorderOptions {
  timesliceMs?: number;
  onChunk: (chunk: Blob, seq: number) => Promise<void>;
  onError?: (err: Error) => void;
}

export class AudioRecorder {
  private mediaStream: MediaStream | null = null;
  private mediaRecorder: MediaRecorder | null = null;
  private nextSeq = 0;
  private uploadChain: Promise<void> = Promise.resolve();
  private uploadError: Error | null = null;
  private stopPromise: Promise<void> | null = null;

  static isSupported(): boolean {
    return Boolean(navigator?.mediaDevices?.getUserMedia && window?.MediaRecorder);
  }

  static getSupportedMimeType(): string {
    const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus', 'audio/wav'];
    return candidates.find((type) => window.MediaRecorder?.isTypeSupported?.(type)) || '';
  }

  async start(options: RecorderOptions): Promise<string> {
    if (!AudioRecorder.isSupported()) throw new Error('قابلیت ضبط صدا در مرورگر شما پشتیبانی نمی‌شود.');
    this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    const mimeType = AudioRecorder.getSupportedMimeType() || 'audio/webm';
    const bitsPerSecond = 32000;
    try {
      this.mediaRecorder = new MediaRecorder(this.mediaStream, { mimeType, audioBitsPerSecond: bitsPerSecond });
    } catch (err) {
      this.mediaStream.getTracks().forEach((track) => track.stop());
      this.mediaStream = null;
      throw new Error('فرمت ضبط صدا در این مرورگر پشتیبانی نمی‌شود.');
    }

    this.nextSeq = 0;
    this.uploadChain = Promise.resolve();
    this.uploadError = null;

    this.mediaRecorder.ondataavailable = (event) => {
      if (!event.data || event.data.size === 0 || this.uploadError) return;
      const seq = this.nextSeq++;
      // Strictly serialize uploads so the backend sequence contract can never be violated.
      this.uploadChain = this.uploadChain.then(() => options.onChunk(event.data, seq)).catch((err: any) => {
        const error = err instanceof Error ? err : new Error('آپلود تکهٔ ضبط ناموفق بود.');
        this.uploadError ||= error;
        options.onError?.(error);
      });
    };
    this.mediaRecorder.onerror = (event: any) => {
      const error = new Error(event.error?.message || 'خطای ضبط صدا');
      this.uploadError ||= error;
      options.onError?.(error);
    };
    this.mediaRecorder.start(options.timesliceMs || 5000);
    return mimeType;
  }

  pause() {
    if (this.mediaRecorder?.state === 'recording') this.mediaRecorder.pause();
  }

  resume() {
    if (this.mediaRecorder?.state === 'paused') this.mediaRecorder.resume();
  }

  async stop(): Promise<void> {
    const recorder = this.mediaRecorder;
    if (!recorder) {
      await this.uploadChain;
      if (this.uploadError) throw this.uploadError;
      return;
    }
    if (recorder.state === 'inactive') {
      await this.uploadChain;
      if (this.uploadError) throw this.uploadError;
      return;
    }
    if (this.stopPromise) return this.stopPromise;

    this.stopPromise = new Promise<void>((resolve, reject) => {
      const finalize = async () => {
        try {
          await this.uploadChain;
          if (this.uploadError) throw this.uploadError;
          resolve();
        } catch (err) { reject(err); } finally {
          this.mediaStream?.getTracks().forEach((track) => track.stop());
          this.mediaStream = null;
          this.mediaRecorder = null;
          this.stopPromise = null;
        }
      };
      recorder.onstop = () => { void finalize(); };
      try { recorder.stop(); } catch (err) { reject(err); }
    });
    return this.stopPromise;
  }

  getState(): RecordingState | 'inactive' {
    return this.mediaRecorder ? this.mediaRecorder.state : 'inactive';
  }
}
