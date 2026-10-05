/**
 * توابع هشدار صوتی و ویبره هنگام اتمام زمان سخنران یا ورود به زمان اضافه.
 * از Web Audio API و navigator.vibrate استاندارد استفاده می‌کند بدون نیاز به هیچ فایل خارجی.
 */

class SoundAlertManager {
  private audioCtx: AudioContext | null = null;

  public prepare() {
    try { this.initCtx(); } catch { /* sound may be unavailable */ }
  }

  private initCtx() {
    if (!this.audioCtx) {
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioContextClass) {
        this.audioCtx = new AudioContextClass();
      }
    }
    if (this.audioCtx && this.audioCtx.state === 'suspended') {
      void this.audioCtx.resume();
    }
  }

  public playTurnAlert() {
    this.playTimeUpBeep();
    if (typeof window !== 'undefined') {
      window.setTimeout(() => this.playTimeUpBeep(), 500);
      window.setTimeout(() => this.playTimeUpBeep(), 1_000);
    }
  }

  public playTimeUpBeep() {
    try {
      this.initCtx();
      if (!this.audioCtx) return;

      const ctx = this.audioCtx;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      // دوتُن صوتی دلنشین و متمایز هشدار (880Hz سپس 440Hz)
      const now = ctx.currentTime;
      osc.frequency.setValueAtTime(880, now);
      osc.frequency.setValueAtTime(440, now + 0.15);

      gain.gain.setValueAtTime(0.3, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.45);

      osc.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now);
      osc.stop(now + 0.45);
    } catch {
      // مرورگر اجازه پخش نداده یا سایلنت است
    }

    // ویبره روی دستگاه‌های همراه پشتیبانی‌کننده
    try {
      if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
        navigator.vibrate([200, 100, 200]);
      }
    } catch {
      // نادیده گرفتن در صورت عدم پشتیبانی
    }
  }
}

export const alertManager = new SoundAlertManager();
